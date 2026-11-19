#!/usr/bin/env python3
"""Linear issue INFRA-285: the batch runs only when the person says go, not on every push to landing.

Each case builds a throwaway repository (a bare "GitHub" remote and a checkout)
that opted in to the batch run, lands commits on `landing`, and runs the real
skills/work-on/batch-go.py as the foreman would when the person says go. gh is
a stand-in that logs every call. Where a go starts a run, the case then runs
the exact shell of the plan step (.github/workflows/batch-plan.yml) and the
move step (.github/workflows/batch-move.yml) with what GitHub would give them
for that go, so what is tested is what GitHub runs.

Scenario 1: pushes to landing start nothing; only the go does (the starter's
trigger is checked in batch-run-test.py).
Scenario 2: a go for a milestone tests the milestone's pile in one run, and a
green run moves main once.
Scenario 3: with no milestone, a go for a set of named issues does the same.
Scenario 4: the go starts the run then and there.
A pile holding commits of an issue the go did not name starts nothing, and the
refusal names each such commit and its issue.

Run from anywhere: python3 hooks/tests/batch-go-test.py
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
GO = os.path.join(PLUGIN, "skills", "work-on", "batch-go.py")
PLAN = os.path.join(PLUGIN, ".github", "workflows", "batch-plan.yml")
MOVE = os.path.join(PLUGIN, ".github", "workflows", "batch-move.yml")
STARTER_TEMPLATE = os.path.join(PLUGIN, "skills", "setup", "batch-starter.yml")
GATE = ".github/workflows/gate.yml"
STARTER = ".github/workflows/masthead-batch.yml"

OLD_STARTER = """name: Masthead batch
on:
  push:
    branches: [landing]
concurrency:
  group: masthead-batch
  cancel-in-progress: false
jobs:
  plan:
    uses: kyroco/masthead/.github/workflows/batch-plan.yml@main
  gate:
    needs: plan
    permissions: { contents: read }
    uses: ./.github/workflows/gate.yml
    secrets: inherit
"""


if not shutil.which("jq"):
    print("skipped: jq is not installed, and the batch plan step reads .claude/gate.json with it")
    sys.exit(77)

passed = 0
failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL " + label + ("\n     " + str(detail) if detail else ""))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def step_script(path, step_id):
    """The `run: |` block of the step with `id: <step_id>`, dedented, as GitHub runs it."""
    lines = read(path).splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"^\s+id:\s*" + re.escape(step_id) + r"\s*$", line))
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(\s+)run:\s*\|\s*$", lines[j])
        if m:
            indent, body = len(m.group(1)), []
            for line in lines[j + 1:]:
                if line.strip() and len(line) - len(line.lstrip()) <= indent:
                    break
                body.append(line)
            return textwrap.dedent("\n".join(body)) + "\n"
    raise SystemExit("step {} in {} has no run block".format(step_id, path))


ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="Worker", GIT_AUTHOR_EMAIL="w@example.com",
           GIT_COMMITTER_NAME="Worker", GIT_COMMITTER_EMAIL="w@example.com")


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("git {} failed: {}".format(" ".join(args), r.stderr))
    return r.stdout.strip()


def run_step(script, cwd, env):
    summary, output = os.path.join(cwd, "..", "summary.md"), os.path.join(cwd, "..", "output.txt")
    for path in (summary, output):
        open(path, "w").close()
    full = dict(ENV, GITHUB_STEP_SUMMARY=summary, GITHUB_OUTPUT=output)
    full.update(env)
    proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                          cwd=cwd, env=full, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr, read(summary), read(output)


class Repo:
    """A bare remote opted in to the batch run, a checkout of it, and a gh that logs each call."""

    def __init__(self, top, linear=True, opted_in=True, starter=None, gh_fails=""):
        self.top = top
        self.remote = os.path.join(top, "remote.git")
        self.work = os.path.join(top, "work")
        self.log = os.path.join(top, "gh-calls.jsonl")
        git(top, "init", "-q", "--bare", "-b", "main", self.remote)
        git(top, "clone", "-q", self.remote, self.work)
        git(self.work, "switch", "-q", "-c", "main")
        env = {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "INFRA"} if linear else {}
        self.write(".claude/settings.json", json.dumps({"env": env}))
        self.write(GATE, "name: Gate\non: [workflow_call, workflow_dispatch]\njobs:\n  gate:\n    runs-on: ubuntu-latest\n")
        self.write(".claude/gate.json", json.dumps({"workflow": GATE, "starts": ["workflow_call", "workflow_dispatch"]}))
        if starter is not None:
            self.write(STARTER, starter)
        elif opted_in:
            self.write(STARTER, read(STARTER_TEMPLATE).replace("__GATE_PERMISSIONS__", "{ contents: read }")
                       .replace("__GATE__", GATE))
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "Base")
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/landing")
        git(self.work, "switch", "-q", "-c", "landing", "--track", "origin/landing")
        self.base = git(self.work, "rev-parse", "HEAD")
        bin_dir = os.path.join(top, "bin")
        os.makedirs(bin_dir)
        shim = os.path.join(bin_dir, "gh")
        with open(shim, "w") as handle:
            handle.write("#!/usr/bin/env python3\nimport json, sys\n"
                         "with open({!r}, 'a') as h:\n    h.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                         "fail = {!r}\n"
                         "if fail:\n    sys.stderr.write(fail + '\\n')\n    sys.exit(1)\n".format(self.log, gh_fails))
        os.chmod(shim, 0o755)
        self.path = bin_dir + os.pathsep + os.environ.get("PATH", "")

    def write(self, rel, text):
        full = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as handle:
            handle.write(text)

    def land(self, message, name=None):
        name = name or re.sub(r"\W+", "-", message)[:40] + ".txt"
        self.write(name, message + "\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/landing")
        return git(self.work, "rev-parse", "HEAD")

    def go(self, *args):
        env = dict(ENV, PATH=self.path, CLAUDE_PROJECT_DIR=self.work)
        r = subprocess.run([sys.executable, GO, *args], cwd=self.work, env=env, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        if not os.path.exists(self.log):
            return []
        return [json.loads(line) for line in read(self.log).splitlines() if line.strip()]

    def ref(self, name):
        return git(self.remote, "rev-parse", "refs/heads/" + name)

    def inputs(self, call):
        return dict(call[i + 1].split("=", 1) for i, arg in enumerate(call) if arg == "-f")

    def run_batch(self, call, gate_result="success"):
        """What GitHub runs for this dispatch: the plan at landing's head as it is now, then the move."""
        job = os.path.join(self.top, "job")
        if os.path.exists(job):
            shutil.rmtree(job)
        os.makedirs(job)
        checkout = os.path.join(job, "checkout")
        git(job, "clone", "-q", self.remote, checkout)
        head = self.ref("landing")
        git(checkout, "checkout", "-q", head)
        inputs = self.inputs(call)
        ref = "refs/heads/" + call[call.index("--ref") + 1]
        code, out, summary, output = run_step(step_script(PLAN, "plan"), checkout, {
            "GITHUB_REF": ref, "GITHUB_SHA": head, "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REPOSITORY": "acme/shop", "STARTER_REF": "acme/shop/" + STARTER + "@" + ref,
            "GO_SHA": inputs.get("sha", ""), "GO_PILE": inputs.get("pile", ""), "GO_ISSUES": inputs.get("issues", "")})
        if code != 0:
            return "plan", code, out
        sha = output.strip().split("=", 1)[1]
        code, out, _, _ = run_step(step_script(MOVE, "move"), checkout,
                                   {"SHA": sha, "GATE_RESULT": gate_result, "GITHUB_REF": ref})
        return "move", code, out + summary


def dispatches(calls):
    return [c for c in calls if c[:2] == ["workflow", "run"]]


# ---- Scenario 1: pushes pile up on landing and start nothing -----------------------
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    for n in range(1, 4):
        repo.land("Build part {} (INFRA-{})".format(n, n))
    check("S1 three pushes to landing start nothing: no call to GitHub at all", repo.calls() == [], repo.calls())
    check("S1 main stays where it was while the pile grows", repo.ref("main") == repo.base)

# ---- Scenario 2: a go for a milestone ------------------------------------------
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    a = repo.land("Add the go script (INFRA-285)")
    b = repo.land("Give a hotfix its own pile\n\nFixes INFRA-286")
    c = repo.land("Follow up on the go script (INFRA-285)")
    code, out = repo.go("--milestone", "Batch on go", "INFRA-285", "INFRA-286", "INFRA-287")
    runs = dispatches(repo.calls())
    check("S2 a go for a milestone whose issues are the whole pile exits 0", code == 0, out)
    check("S2/S4 the go starts exactly one run, then and there", len(runs) == 1 and len(repo.calls()) == 1, repo.calls())
    call = runs[0] if runs else ["workflow", "run"]
    inputs = repo.inputs(call)
    check("S2 the run is the starter on landing", call[2:5] == ["masthead-batch.yml", "--ref", "landing"], call)
    check("S2 the run tests landing's last commit, the one the go checked", inputs.get("sha") == c, inputs)
    check("S2 the run says it is the milestone's go", inputs.get("pile") == "milestone Batch on go", inputs)
    check("S2 the run lists the issues on the pile", inputs.get("issues") == "INFRA-285 INFRA-286", inputs)
    check("S2 the go lists every commit of the pile", all(s[:9] in out for s in (a, b, c)), out)
    check("S2 the go says which named issue has nothing on the pile", "Nothing on the pile for INFRA-287" in out, out)
    where, code, out = repo.run_batch(call)
    check("S2 the plan lets the go's run start, and a green run moves main", where == "move" and code == 0, out)
    check("S2 a green run moves main once, to the whole pile", repo.ref("main") == c, repo.ref("main"))
    check("S2 the one move carries every commit of the pile",
          out.count("Main moves from") == 1 and all(s[:7] in out for s in (a, b, c)), out)

# A red run leaves main where it was (the move refuses anything but a passed Gate).
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    code, out = repo.go("--milestone", "Batch on go", "INFRA-285")
    where, code, out = repo.run_batch(dispatches(repo.calls())[0], gate_result="failure")
    check("S2 a red run does not move main", where == "move" and code != 0 and repo.ref("main") == repo.base, out)

# ---- Scenario 3: no milestone, a go for named issues ------------------------------
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    a = repo.land("Fix the login page (INFRA-301)")
    b = repo.land("refs INFRA-302\n\nTidy the sign-in copy")
    code, out = repo.go("INFRA-301", "infra-302")
    runs = dispatches(repo.calls())
    inputs = repo.inputs(runs[0]) if runs else {}
    check("S3 a go for named issues starts one run", code == 0 and len(runs) == 1, out)
    check("S3 the run names those issues as its pile", inputs.get("pile") == "issues INFRA-301 INFRA-302"
          and inputs.get("issues") == "INFRA-301 INFRA-302" and inputs.get("sha") == b, inputs)
    where, code, out = repo.run_batch(runs[0])
    check("S3 a green run moves main once, to the pile of those issues",
          where == "move" and code == 0 and repo.ref("main") == b and out.count("Main moves from") == 1, out)

# GitHub numbers work the same way.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top, linear=False)
    a = repo.land("Fix the login page (#12)")
    b = repo.land("Fixes #14\n\nTidy the copy, see #12 too")
    code, out = repo.go("#12", "14")
    runs = dispatches(repo.calls())
    check("S3 a repository whose issues live on GitHub names them by number",
          code == 0 and len(runs) == 1 and repo.inputs(runs[0]).get("issues") == "#12 #14", out)

# ---- A pile holding work the go did not name starts nothing ------------------------
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    other = repo.land("Start the next milestone (INFRA-310)")
    loose = repo.land("Bump a version")
    undo = repo.land("Undo part of INFRA-285 (INFRA-311)")
    code, out = repo.go("--milestone", "Batch on go", "INFRA-285")
    check("a go whose pile holds other issues' commits starts nothing", code != 0 and repo.calls() == [], out)
    check("the refusal says nothing starts and why main would carry them",
          "so nothing starts" in out and "would go to main too" in out, out)
    check("the refusal names each commit that does not belong, with its issue",
          "{} Start the next milestone (INFRA-310) (INFRA-310)".format(other[:9]) in out
          and "{} Undo part of INFRA-285 (INFRA-311) (INFRA-311)".format(undo[:9]) in out, out)
    check("the refusal names a commit that names no issue as such",
          "{} Bump a version (names no issue)".format(loose[:9]) in out, out)
    check("the refusal says what to do: name those issues too", "say go again with INFRA-310 INFRA-311 named too" in out,
          out)
    check("a commit naming the go's issue and another belongs to the other one, the last named",
          "Undo part of INFRA-285 (INFRA-311) (INFRA-311)" in out, out)
    check("main has not moved", repo.ref("main") == repo.base)

# Landing moving between the go and the run's start: the plan stops the run.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    code, out = repo.go("INFRA-285")
    late = repo.land("Start the next milestone (INFRA-310)")
    where, code, out = repo.run_batch(dispatches(repo.calls())[0])
    check("a commit landed after the go stops the run at the plan, and main does not move",
          where == "plan" and code != 0 and "Landing moved after the go" in out and repo.ref("main") == repo.base, out)

# ---- Nothing to go with ------------------------------------------------------------
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    code, out = repo.go("INFRA-285")
    check("with nothing on landing past main nothing starts", code != 0 and repo.calls() == []
          and "nothing to test" in out, out)
    repo.land("Add the go script (INFRA-285)")
    code, out = repo.go("--check", "INFRA-285")
    check("--check checks the pile and starts nothing", code == 0 and repo.calls() == [] and "nothing started" in out, out)
    code, out = repo.go("--milestone", "Batch on go")
    check("a go that names no issue starts nothing", code != 0 and repo.calls() == [] and "No issue was named" in out, out)
    code, out = repo.go("login-page")
    check("a word that is not an issue starts nothing", code != 0 and repo.calls() == [] and "is not an issue" in out, out)

with tempfile.TemporaryDirectory() as top:
    repo = Repo(top, opted_in=False)
    repo.land("Add the go script (INFRA-285)")
    code, out = repo.go("INFRA-285")
    check("a repository with no batch run starts nothing and says so",
          code != 0 and repo.calls() == [] and "has no batch run" in out, out)

with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    git(repo.work, "switch", "-q", "-c", "side", repo.base)
    repo.write("hot.txt", "hot\n")
    git(repo.work, "add", "-A")
    git(repo.work, "commit", "-q", "-m", "Hot fix (INFRA-290)")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/main")
    code, out = repo.go("INFRA-285")
    check("main holding a commit landing lacks starts nothing", code != 0 and repo.calls() == []
          and "Main holds a commit landing does not" in out, out)

# ---- Round 1 fixes ----------------------------------------------------------------
# s3-C1: a repository set up before INFRA-285 still holds the starter that runs on every push. GitHub
# would refuse a go to it, so the go stops first and says to write the starter again.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top, starter=OLD_STARTER)
    repo.land("Add the go script (INFRA-285)")
    code, out = repo.go("INFRA-285")
    check("s3-C1 a go in a repository whose starter still runs on every push starts nothing",
          code != 0 and repo.calls() == [], out)
    check("s3-C1 it says the starter is the older one and to write it again with /masthead:setup",
          "runs on every push to landing" in out and "/masthead:setup" in out, out)

# The go reaches GitHub, which refuses it, as it does when the starter is not on the default branch yet.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top, gh_fails="HTTP 404: Not Found (https://api.github.com/repos/acme/shop/actions/workflows/masthead-batch.yml/dispatches)")
    repo.land("Add the go script (INFRA-285)")
    code, out = repo.go("INFRA-285")
    check("s3-C1 a go GitHub refuses says so, with GitHub's words",
          code != 0 and "GitHub did not start the batch run" in out and "HTTP 404" in out, out)
    check("s3-C1 it says the starter must be on main before GitHub will start it by hand",
          "must be on main" in out, out)

# s3-J1: a commit naming another team's issue is named by that issue, not as naming none.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    other = repo.land("Fix the sign-in copy (ENG-5)")
    code, out = repo.go("INFRA-285")
    check("s3-J1 a commit of another team's issue stops the go and is named by its issue",
          code != 0 and repo.calls() == [] and "{} Fix the sign-in copy (ENG-5) (ENG-5)".format(other[:9]) in out, out)
    check("s3-J1 the refusal says to name that issue too", "say go again with ENG-5 named too" in out, out)
    code, out = repo.go("INFRA-285", "ENG-5")
    check("s3-J1 naming it too lets the go start", code == 0 and len(dispatches(repo.calls())) == 1, out)

# arch-1: after a red batch, the search's drop record and a worker's `git revert` of it bring a
# commit back. The record is the search's commit, no issue's work, and the revert of it belongs to
# the record's issue, the way batch-issues.py reads them, though git's message names no issue.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-301)")
    bad = repo.land("Add the hotfix pile (INFRA-303)")
    git(repo.work, "revert", "--no-edit", "--no-commit", bad)
    git(repo.work, "commit", "-q", "-m", "Drop {} from landing: it turned the batch red\n\n"
        "Masthead-Dropped: {}\nMasthead-Issue: INFRA-303\nMasthead-Failed-Check: gate / Tests\n".format(bad[:9], bad))
    record = git(repo.work, "rev-parse", "HEAD")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/landing")
    git(repo.work, "revert", "--no-edit", record)
    back = git(repo.work, "rev-parse", "HEAD")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/landing")
    code, out = repo.go("INFRA-301", "INFRA-303")
    check("arch-1 a drop record and the worker's revert of it belong to the dropped commit's issue, so the go starts",
          code == 0 and len(dispatches(repo.calls())) == 1, out)
    code, out = repo.go("INFRA-301")
    check("arch-1 without that issue named, the brought-back commit is named by the record's issue",
          code != 0 and "{} ".format(back[:9]) in out and "(INFRA-303)" in out
          and "names no issue" not in out, out)

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
