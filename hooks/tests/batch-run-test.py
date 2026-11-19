#!/usr/bin/env python3
"""Linear issue INFRA-270: one Gate run per batch on `landing`, and main moves only when it is green.

The batch run is two workflows in this repository, called by a starter file in
each repository (skills/setup/batch-starter.yml). The tests run the exact
shell each workflow step runs, read out of the workflow file, against
throwaway git repositories, so what is tested is what GitHub runs.

Scenario 1: the starter keeps one batch at a time and lets a newer push replace
the waiting one; the next run moves main once, over every commit landed meanwhile.
Scenario 2: a green Gate moves main to exactly the batch's last commit.
Scenario 3: a red Gate (or a cancelled or skipped one) leaves main where it was.
Scenario 4: the batch run runs the Gate stored in .claude/gate.json and never
works it out; with none stored it does not start and says so.

Run from anywhere: python3 hooks/tests/batch-run-test.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
PLAN = os.path.join(PLUGIN, ".github", "workflows", "batch-plan.yml")
MOVE = os.path.join(PLUGIN, ".github", "workflows", "batch-move.yml")
STARTER = os.path.join(PLUGIN, "skills", "setup", "batch-starter.yml")
GATE = ".github/workflows/gate.yml"

passed = 0
failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL " + label + ("\n     " + detail if detail else ""))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def step_script(path, step_id):
    """The `run: |` block of the step with `id: <step_id>`, dedented, as GitHub runs it."""
    lines = read(path).splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s+id:\s*" + re.escape(step_id) + r"\s*$", line):
            start = i
            break
    if start is None:
        raise SystemExit("no step with id {} in {}".format(step_id, path))
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(\s+)run:\s*\|\s*$", lines[j])
        if m:
            indent = len(m.group(1))
            body = []
            for line in lines[j + 1:]:
                if line.strip() and len(line) - len(line.lstrip()) <= indent:
                    break
                body.append(line)
            return textwrap.dedent("\n".join(body)) + "\n"
        if re.match(r"^\s+-\s", lines[j]):
            break
    raise SystemExit("step {} in {} has no run block".format(step_id, path))


def git(cwd, *args, check_ok=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="Worker", GIT_AUTHOR_EMAIL="w@example.com",
               GIT_COMMITTER_NAME="Worker", GIT_COMMITTER_EMAIL="w@example.com",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    out = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if check_ok and out.returncode != 0:
        raise SystemExit("git {} failed: {}".format(" ".join(args), out.stderr))
    return out.stdout.strip()


def commit(work, name):
    with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
        handle.write(name + "\n")
    git(work, "add", name)
    git(work, "commit", "-q", "-m", "Land " + name)
    return git(work, "rev-parse", "HEAD")


def run_script(script, cwd, env):
    summary = os.path.join(cwd, "..", "summary.md")
    output = os.path.join(cwd, "..", "output.txt")
    for path in (summary, output):
        open(path, "w").close()
    full = dict(os.environ, GITHUB_STEP_SUMMARY=summary, GITHUB_OUTPUT=output,
                GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                GIT_COMMITTER_NAME="Worker", GIT_COMMITTER_EMAIL="w@example.com")
    full.update(env)
    # GitHub runs a run block with `bash --noprofile --norc -eo pipefail {0}`.
    proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                          cwd=cwd, env=full, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr, read(summary), read(output)


class Repo:
    """A bare origin with main and landing, and a clone of it as the move job checks it out."""

    def __init__(self, top):
        self.origin = os.path.join(top, "origin.git")
        self.work = os.path.join(top, "work")
        self.job = os.path.join(top, "job", "checkout")
        git(top, "init", "-q", "--bare", "-b", "main", self.origin)
        git(top, "clone", "-q", self.origin, self.work)
        self.base = commit(self.work, "base.txt")
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/landing")
        git(self.work, "switch", "-q", "-c", "landing", "--track", "origin/landing")

    def land(self, *names):
        shas = [commit(self.work, n) for n in names]
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/landing")
        return shas

    def main(self):
        return git(self.origin, "rev-parse", "refs/heads/main")

    def move(self, sha, gate_result="success", ref="refs/heads/landing"):
        if os.path.exists(os.path.dirname(self.job)):
            shutil.rmtree(os.path.dirname(self.job))
        os.makedirs(os.path.dirname(self.job))
        git(os.path.dirname(self.job), "clone", "-q", self.origin, self.job)
        return run_script(step_script(MOVE, "move"), self.job,
                          {"SHA": sha, "GATE_RESULT": gate_result, "GITHUB_REF": ref})


# ---- Scenario 2: green moves main to the batch's last commit ----------------
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    b, c = repo.land("b.txt", "c.txt")
    code, out, summary, _ = repo.move(c)
    check("S2 a green batch's move exits 0", code == 0, out)
    check("S2 main points at the batch's last commit", repo.main() == c, "main is " + repo.main())
    check("S2 the summary names every commit the batch carried",
          "Land b.txt" in summary and "Land c.txt" in summary, summary)
    code, out, summary, _ = repo.move(c)
    check("S2 a second move of the same batch is a no-op", code == 0 and repo.main() == c, out)

# ---- Scenario 3: red leaves main where it was ---------------------------------
for result in ("failure", "cancelled", "skipped", ""):
    with tempfile.TemporaryDirectory() as top:
        repo = Repo(top)
        (c,) = repo.land("c.txt")
        code, out, _, _ = repo.move(c, gate_result=result)
        check("S3 a Gate that ended '{}' fails the move".format(result), code != 0, out)
        check("S3 main has not moved after a Gate that ended '{}'".format(result), repo.main() == repo.base,
              "main is " + repo.main())
        check("S3 the move says why main stayed ('{}')".format(result),
              "so main does not move" in out, out)

# The starter never runs the move after a red Gate: `move` needs `gate`, with no
# condition that would run it anyway, and passes the Gate's own result.
starter = read(STARTER)
move_job = starter.split("\n  move:\n", 1)[-1]
check("S3 the starter's move job waits on the Gate job",
      re.search(r"^    needs: \[plan, gate\]$", move_job, re.M) is not None, move_job)
check("S3 the starter's move job has no condition that runs it after a red Gate",
      re.search(r"^    if:", move_job, re.M) is None and "always()" not in starter, move_job)
check("S3 the starter passes the Gate job's own result to the move",
      "gate-result: ${{ needs.gate.result }}" in move_job, move_job)

# Main does not move when the batch is no longer on landing, or main holds a commit the batch does not.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    (c,) = repo.land("c.txt")
    git(repo.work, "switch", "-q", "-c", "side", repo.base)
    stray = commit(repo.work, "stray.txt")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/side")
    code, out, _, _ = repo.move(stray)
    check("S3 a commit not on landing is refused", code != 0 and repo.main() == repo.base, out)
    git(repo.work, "push", "-q", "origin", stray + ":refs/heads/main")
    code, out, _, _ = repo.move(c)
    check("S3 main holding a commit the batch lacks is refused, and main is left alone",
          code != 0 and repo.main() == stray and "would drop work" in out, out)
    code, out, _, _ = repo.move(c, ref="refs/heads/side")
    check("S3 a run off a branch other than landing never moves main", code != 0 and repo.main() == stray, out)
    code, out, _, _ = repo.move("main")
    check("S3 a sha that is not a full commit id is refused", code != 0 and repo.main() == stray, out)

# ---- Scenario 1: one run per batch, carrying everything landed meanwhile ------
check("S1 the starter starts on a push to landing only",
      re.search(r"^on:\n  push:\n    branches: \[landing\]\n", starter, re.M) is not None, starter)
check("S1 the starter keeps one batch at a time in one fixed group",
      re.search(r"^concurrency:\n  group: masthead-batch\n  cancel-in-progress: false\n", starter, re.M) is not None,
      starter)
check("S1 the starter runs the Gate once per run, after the plan",
      starter.count("uses: ./__GATE__") == 1 and re.search(r"^  gate:\n    needs: plan\n", starter, re.M) is not None,
      starter)
check("S1 main moves to the commit the plan names, the one the run started on",
      "sha: ${{ needs.plan.outputs.sha }}" in starter and 'echo "sha=$GITHUB_SHA"' in step_script(PLAN, "plan"))
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    (b,) = repo.land("b.txt")
    repo.move(b)
    # While the batch at b ran, three commits landed; the run that waited tests the newest.
    c, d, e = repo.land("c.txt", "d.txt", "e.txt")
    code, out, summary, _ = repo.move(e)
    check("S1 the next run moves main once, to the newest commit", code == 0 and repo.main() == e, out)
    check("S1 that one move carries every commit landed meanwhile, together",
          all("Land {}.txt".format(n) in summary for n in "cde") and "Land b.txt" not in summary, summary)

# ---- Scenario 4: the stored Gate, or no start ----------------------------------
PLAN_SCRIPT = step_script(PLAN, "plan")
SHA = "a" * 40


def plan(stored, gate_input=GATE, ref="refs/heads/landing", link=False):
    with tempfile.TemporaryDirectory() as top:
        checkout = os.path.join(top, "checkout")
        os.makedirs(os.path.join(checkout, ".claude"))
        path = os.path.join(checkout, ".claude", "gate.json")
        if stored is not None:
            target = os.path.join(top, "elsewhere.json") if link else path
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(stored if isinstance(stored, str) else json.dumps(stored))
            if link:
                os.symlink(target, path)
        # Workflows that would make a guess find something, to show none is looked at.
        os.makedirs(os.path.join(checkout, ".github", "workflows"))
        with open(os.path.join(checkout, ".github", "workflows", "gate.yml"), "w") as handle:
            handle.write("name: Gate\non: [pull_request, workflow_call]\n")
        return run_script(PLAN_SCRIPT, checkout, {"GATE_INPUT": gate_input, "GITHUB_REF": ref, "GITHUB_SHA": SHA})


code, out, summary, output = plan({"workflow": GATE, "starts": ["workflow_call", "workflow_dispatch"]})
check("S4 a stored Gate the starter runs lets the batch start", code == 0, out)
check("S4 the plan names the batch's commit for the Gate and the move", output.strip() == "sha=" + SHA, output)
check("S4 the plan says which stored Gate runs", GATE in summary and "as stored in .claude/gate.json" in summary, summary)

NONE = "No Gate is stored in .claude/gate.json, so the batch run does not start and main does not move."
code, out, summary, output = plan(None)
check("S4 with no Gate stored the batch run does not start", code != 0 and output.strip() == "", out)
check("S4 with no Gate stored it says so", NONE in out and NONE in summary, out)
code, out, _, output = plan({"workflow": GATE, "starts": ["workflow_call"]}, link=True)
check("S4 a gate.json that is a link is not a stored Gate", code != 0 and NONE in out and output.strip() == "", out)

for label, stored in (("no workflow named", {"starts": ["workflow_call"]}),
                      ("a workflow that is not text", {"workflow": 7, "starts": ["workflow_call"]}),
                      ("not JSON", "{not json"),
                      ("an empty file", "")):
    code, out, _, output = plan(stored)
    check("S4 gate.json with {} does not start the batch".format(label),
          code != 0 and output.strip() == "" and "does not start" in out, out)

code, out, _, output = plan({"workflow": GATE, "starts": ["workflow_dispatch"]})
check("S4 a stored Gate that workflow_call cannot start stops the batch and says so",
      code != 0 and output.strip() == "" and "cannot be started with workflow_call" in out, out)
code, out, _, output = plan({"workflow": ".github/workflows/checks.yml", "starts": ["workflow_call"]})
check("S4 a starter that runs a Gate other than the stored one does not start",
      code != 0 and output.strip() == "" and "runs only the stored Gate" in out, out)
code, out, _, output = plan({"workflow": GATE, "starts": ["workflow_call"]}, ref="refs/heads/feature")
check("S4 a batch run off landing does not start", code != 0 and output.strip() == "", out)

# ---- The starter calls this repository's workflows as they are written -------
plan_text, move_text = read(PLAN), read(MOVE)
check("the starter calls batch-plan.yml and batch-move.yml in kyroco/masthead",
      "uses: kyroco/masthead/.github/workflows/batch-plan.yml@" in starter
      and "uses: kyroco/masthead/.github/workflows/batch-move.yml@" in starter)
check("batch-plan.yml can be called, with the gate input the starter passes",
      "workflow_call:" in plan_text and re.search(r"^      gate:\n", plan_text, re.M)
      and "gate: __GATE__" in starter)
check("batch-move.yml can be called, with the inputs and secrets the starter passes",
      all(re.search(r"^      {}:\n".format(re.escape(k)), move_text, re.M)
          for k in ("sha", "gate-result", "BATCH_APP_ID", "BATCH_APP_PRIVATE_KEY")))
for path in (PLAN, MOVE):
    for step_id in {PLAN: ["plan"], MOVE: ["move"]}[path]:
        check("{} step {} puts no expression inside its shell".format(os.path.basename(path), step_id),
              "${{" not in step_script(path, step_id))

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
