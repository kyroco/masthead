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

    def land(self, message, name=None, branch="landing", onto=None, text=None):
        """A worker's landing: start from the newest pile (or `onto`), commit, push to the pile's branch."""
        git(self.work, "fetch", "-q", "origin")
        git(self.work, "switch", "-q", "--detach", onto or "origin/" + branch)
        name = name or re.sub(r"\W+", "-", message)[:40] + ".txt"
        self.write(name, (text if text is not None else message) + "\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/" + branch)
        return git(self.work, "rev-parse", "HEAD")

    def land_hotfix(self, message, name=None, text=None):
        """A hotfix worker: rebase onto what `--hotfix --base` prints, then push to hotfix (INFRA-286)."""
        code, out = self.go("--hotfix", "--base")
        if code != 0:
            raise SystemExit("--hotfix --base failed: " + out)
        return self.land(message, name=name, branch="hotfix", onto=out.splitlines()[0], text=text)

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
        """What GitHub runs for this dispatch: the plan at the pile's head as it is now, then the move."""
        job = os.path.join(self.top, "job")
        if os.path.exists(job):
            shutil.rmtree(job)
        os.makedirs(job)
        checkout = os.path.join(job, "checkout")
        git(job, "clone", "-q", self.remote, checkout)
        branch = call[call.index("--ref") + 1]
        head = self.ref(branch)
        git(checkout, "checkout", "-q", head)
        inputs = self.inputs(call)
        ref = "refs/heads/" + branch
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
          where == "plan" and code != 0 and "The landing branch moved after the go" in out and repo.ref("main") == repo.base, out)

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

# s3-J1 on a Fixes or refs line, and J-1: a word shaped like a key in a sentence is not an issue.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    fixes = repo.land("Tidy the sign-in copy\n\nFixes ENG-7")
    refs = repo.land("Move the sign-in copy\n\nrefs ENG-8")
    utf = repo.land("Fixes UTF-8 decoding of names")
    code, out = repo.go("INFRA-285")
    check("s3-J1 a Fixes line naming another team's issue names the commit by it",
          "{} Tidy the sign-in copy (ENG-7)".format(fixes[:9]) in out, out)
    check("s3-J1 a refs line naming another team's issue names the commit by it",
          "{} Move the sign-in copy (ENG-8)".format(refs[:9]) in out, out)
    check("J-1 a Fixes sentence holding a word shaped like a key (UTF-8) names no issue",
          "{} Fixes UTF-8 decoding of names (names no issue)".format(utf[:9]) in out and "UTF-8 named" not in out, out)
    check("J-1 the refusal asks to name only the real issues", "say go again with ENG-7 ENG-8 named too" in out, out)

# s3-J1, round 2: a key written in lower case on a refs line is read as that key, upper case, and
# never crashes the go.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    lower = repo.land("Tidy the copy\n\nrefs eng-8")
    code, out = repo.go("INFRA-285")
    check("s3-J1 a lower-case key of another team on a refs line gives a refusal, not a crash",
          code != 0 and "Traceback" not in out and repo.calls() == [], out)
    check("s3-J1 that commit is named by its key, upper case, and the refusal says to name it",
          "{} Tidy the copy (ENG-8)".format(lower[:9]) in out and "say go again with ENG-8 named too" in out, out)
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.land("Add the go script (INFRA-285)")
    repo.land("Follow up on the go script\n\nrefs infra-285")
    code, out = repo.go("INFRA-285")
    check("s3-J1 a lower-case key of the go's own issue on a refs line belongs to it, and the go starts",
          code == 0 and "Traceback" not in out and len(dispatches(repo.calls())) == 1, out)

# ==== INFRA-286: a hotfix has its own pile that lands and goes straight to main ====================
# Robert, November 19, 2026: "fine, figure out a way to make its own pile. On a hot fix, we land and push
# that fix to main."

def parents(repo, sha):
    return git(repo.remote, "rev-list", "--parents", "-n", "1", sha).split()[1:]


def on(repo, ancestor, sha):
    return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, sha], cwd=repo.remote,
                          env=ENV).returncode == 0


def shown(repo, sha, path):
    r = subprocess.run(["git", "show", "{}:{}".format(sha, path)], cwd=repo.remote, env=ENV,
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


# ---- Scenario 1: a hotfix lands apart from the milestone pile -------------------------------------
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    a = repo.land("Add the go script (INFRA-285)")
    b = repo.land("Follow up on the go script (INFRA-285)")
    code, out = repo.go("--hotfix", "--base")
    check("286-S1 with no hotfix waiting, a hotfix worker is told to build on main",
          code == 0 and out.splitlines()[0] == "origin/main" and "git push origin HEAD:hotfix" in out, out)
    hot = repo.land_hotfix("Stop the sign-in page crashing (INFRA-290)")
    check("286-S1 the hotfix lands on its own branch, hotfix", repo.ref("hotfix") == hot, repo.ref("hotfix"))
    check("286-S1 the hotfix pile is main plus the hotfix, with nothing of the milestone pile",
          parents(repo, hot) == [repo.base] and not on(repo, a, hot), parents(repo, hot))
    check("286-S1 the milestone pile on landing is untouched", repo.ref("landing") == b, repo.ref("landing"))
    check("286-S1 landing a hotfix starts nothing by itself", repo.calls() == [], repo.calls())
    code, out = repo.go("--hotfix", "--base")
    check("286-S1 while a hotfix waits on hotfix, the next hotfix worker is told to build on it",
          code == 0 and out.splitlines()[0] == "origin/hotfix", out)
    code, out = repo.go("--base")
    check("286-S1 a milestone worker is still told to build on landing", code == 0 and
          out.splitlines()[0] == "origin/landing", out)

    # ---- Scenario 2: the hotfix's own run is green, and main moves with only the hotfix in it ---------
    code, out = repo.go("--hotfix", "INFRA-290")
    runs = dispatches(repo.calls())
    call = runs[0] if runs else ["workflow", "run", "", "--ref", "hotfix"]
    inputs = repo.inputs(call)
    check("286-S2 the hotfix's go starts exactly one run", code == 0 and len(runs) == 1, out)
    check("286-S2 the run is the starter on hotfix, not on landing",
          call[2:5] == ["masthead-batch.yml", "--ref", "hotfix"], call)
    check("286-S2 the run tests the hotfix's last commit and says it is a hotfix",
          inputs.get("sha") == hot and inputs.get("pile") == "hotfix INFRA-290" and inputs.get("issues") == "INFRA-290",
          inputs)
    where, code, out = repo.run_batch(call)
    check("286-S2 the plan and the move accept a run on hotfix, and a green run moves main",
          where == "move" and code == 0, out)
    check("286-S2 main moves to the hotfix", repo.ref("main") == hot, repo.ref("main"))
    check("286-S2 main holds only the hotfix past where it was, nothing of the milestone pile",
          git(repo.remote, "rev-list", "{}..main".format(repo.base)).split() == [hot]
          and not on(repo, a, repo.ref("main")), out)
    code, out = repo.go("--hotfix", "--base")
    check("286-S2 once the hotfix is on main, the next hotfix builds on main again",
          code == 0 and out.splitlines()[0] == "origin/main", out)

    # ---- Scenario 3: the milestone pile is untouched, and a later go includes the hotfix -------------
    check("286-S3 after the hotfix moved main, landing is exactly the milestone pile it was",
          repo.ref("landing") == b and not on(repo, hot, b), repo.ref("landing"))
    code, out = repo.go("--check", "--milestone", "Batch on go", "INFRA-285")
    check("286-S3 --check says a go would bring main in first, and pushes and starts nothing",
          code == 0 and "a go first brings main into landing" in out and repo.ref("landing") == b
          and len(dispatches(repo.calls())) == 1, out)
    code, out = repo.go("--milestone", "Batch on go", "INFRA-285")
    runs = dispatches(repo.calls())
    head = repo.ref("landing")
    check("286-S3 a later go for the milestone starts, though the hotfix's issue is not one it names",
          code == 0 and len(runs) == 2, out)
    check("286-S3 the go brings main into landing with one merge on top of the untouched pile",
          parents(repo, head) == [b, hot] and "brought main into landing" in out, (parents(repo, head), out))
    check("286-S3 the merge names the hotfix's issue",
          git(repo.remote, "log", "-1", "--format=%s", head) == "Bring main into landing for the go (INFRA-290)",
          git(repo.remote, "log", "-1", "--format=%s", head))
    check("286-S3 the merge holds the pile and the hotfix",
          shown(repo, head, "Stop-the-sign-in-page-crashing-INFRA-290.txt") is not None
          and shown(repo, head, "Add-the-go-script-INFRA-285-.txt") is not None, head)
    check("286-S3 the run tests the merge, the pile with the hotfix", repo.inputs(runs[-1]).get("sha") == head
          and repo.inputs(runs[-1]).get("issues") == "INFRA-285", runs[-1])
    check("286-S3 the go lists the merge as bringing main in", "{} Bring main into landing for the go (INFRA-290) "
          "(brings main in)".format(head[:9]) in out, out)
    where, code, out = repo.run_batch(runs[-1])
    check("286-S3 a green run moves main to the pile and the hotfix together",
          where == "move" and code == 0 and repo.ref("main") == head and on(repo, hot, head) and on(repo, b, head), out)

# A later go with no new hotfix makes no merge: landing already holds main.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    a = repo.land("Add the go script (INFRA-285)")
    code, out = repo.go("INFRA-285")
    check("286 a go on a pile that holds main makes no merge", code == 0 and repo.ref("landing") == a
          and "brought main" not in out, out)

# The hotfix pile is checked like any pile: a commit of another issue on it stops the hotfix's go.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    hot = repo.land_hotfix("Stop the sign-in page crashing (INFRA-290)")
    other = repo.land("Start the next milestone (INFRA-310)", branch="hotfix")
    code, out = repo.go("--hotfix", "INFRA-290")
    check("286 a hotfix pile holding another issue's commit starts nothing and names it",
          code != 0 and repo.calls() == [] and "{} Start the next milestone (INFRA-310) (INFRA-310)".format(other[:9]) in out
          and "Hotfix holds 1 commit outside hotfix INFRA-290" in out, out)

with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    code, out = repo.go("--hotfix", "INFRA-290")
    check("286 a hotfix go with no hotfix branch on GitHub starts nothing and says to land it first",
          code != 0 and repo.calls() == [] and "GitHub has no hotfix branch" in out, out)
    code, out = repo.go("--hotfix", "--milestone", "Batch on go", "INFRA-290")
    check("286 a hotfix is not part of a milestone", code != 0 and repo.calls() == [] and "not part of a milestone" in out,
          out)

# A hotfix that touches the same lines as the pile: the go stops, pushes nothing, starts nothing.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    b = repo.land("Change the greeting (INFRA-285)", name="greeting.txt", text="hello from the milestone")
    hot = repo.land_hotfix("Fix the greeting (INFRA-290)", name="greeting.txt", text="hello from the hotfix")
    code, out = repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[0])
    code, out = repo.go("INFRA-285")
    check("286-S3 a pile and a hotfix changing the same lines stop the go and name the file",
          code != 0 and "change the same lines" in out and "greeting.txt" in out, out)
    check("286-S3 that stop pushes nothing to landing and starts no run",
          repo.ref("landing") == b and len(dispatches(repo.calls())) == 1, repo.calls())

# INFRA-274's push check on the merge: a hotfix's CI change alone needs no new OK, since the merge leaves
# the file as main has it. Both sides changing one CI file leaves the merge's file unlike either side, and
# the push check refuses that without an OK, so the go stops.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.write(".github/workflows/lint.yml", "\n".join("line {}".format(n) for n in range(1, 21)) + "\n")
    git(repo.work, "add", "-A")
    git(repo.work, "commit", "-q", "-m", "Add lint")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/landing")
    repo.base = repo.ref("main")
    lint = "\n".join("line {}".format(n) for n in range(1, 21))
    repo.land("Change the pile (INFRA-285)")
    repo.land_hotfix("Fix lint (INFRA-290)\n\nCI-change-OK: https://linear.app/x/issue/INFRA-290/x#comment-1",
                     name=".github/workflows/lint.yml", text=lint.replace("line 1\n", "line one\n", 1))
    repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[-1])
    code, out = repo.go("INFRA-285")
    check("286 a hotfix's CI change alone passes the push check on the merge, and the go starts",
          code == 0 and len(dispatches(repo.calls())) == 2, out)
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    lint = "\n".join("line {}".format(n) for n in range(1, 21))
    repo.write(".github/workflows/lint.yml", lint + "\n")
    git(repo.work, "add", "-A")
    git(repo.work, "commit", "-q", "-m", "Add lint")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/landing")
    repo.base = repo.ref("main")
    before = repo.land("Tune lint (INFRA-285)\n\nCI-change-OK: https://linear.app/x/issue/INFRA-285/x#comment-2",
                       name=".github/workflows/lint.yml", text=lint.replace("line 20", "line twenty"))
    repo.land_hotfix("Fix lint (INFRA-290)\n\nCI-change-OK: https://linear.app/x/issue/INFRA-290/x#comment-1",
                     name=".github/workflows/lint.yml", text=lint.replace("line 1\n", "line one\n", 1))
    repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[-1])
    code, out = repo.go("INFRA-285")
    check("286 a merge whose CI file differs from both sides stops the go at the push check",
          code != 0 and "push check refuses" in out and ".github/workflows/lint.yml" in out, out)
    check("286 that stop pushes nothing and starts nothing", repo.ref("landing") == before
          and len(dispatches(repo.calls())) == 1, out)

# The merge's push loses the race with a worker landing at the same moment: the go checks the new pile and
# makes the merge again on it, never forcing. GitHub is stood in for by a hook on the remote that lands a
# commit on landing just before the go's push is applied, once.
# git keeps a push's objects apart until its hooks pass and forbids a hook to move a ref, so the hook's
# own landing runs outside that, as another push would.
RACE_HOOK = """#!/bin/sh
[ -f "{marker}" ] && exit 0
touch "{marker}"
unset GIT_QUARANTINE_PATH GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES
old=$(git rev-parse refs/heads/landing)
new=$(git commit-tree "$old^{{tree}}" -p "$old" -m "{message}")
git update-ref refs/heads/landing "$new" "$old"
"""


def racing(repo, message):
    hook = os.path.join(repo.remote, "hooks", "pre-receive")
    with open(hook, "w") as handle:
        handle.write(RACE_HOOK.format(marker=os.path.join(repo.top, "raced"), message=message))
    os.chmod(hook, 0o755)


with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    b = repo.land("Add the go script (INFRA-285)")
    hot = repo.land_hotfix("Stop the sign-in page crashing (INFRA-290)")
    repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[-1])
    racing(repo, "Follow up on the go script (INFRA-285)")
    code, out = repo.go("INFRA-285")
    head = repo.ref("landing")
    racer = parents(repo, head)[0] if parents(repo, head) else ""
    check("286 a merge push that loses the race is made again on the new pile, and the go starts",
          code == 0 and "moved while the go pushed its merge" in out and len(dispatches(repo.calls())) == 2, out)
    check("286 the merge sits on the worker's commit that won the race, so nothing was forced over it",
          racer != b and parents(repo, racer) == [b] and parents(repo, head) == [racer, hot], (head, racer))
    check("286 the run tests the new merge", repo.inputs(dispatches(repo.calls())[-1]).get("sha") == head, out)

with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    b = repo.land("Add the go script (INFRA-285)")
    repo.land_hotfix("Stop the sign-in page crashing (INFRA-290)")
    repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[-1])
    racing(repo, "Start the next milestone (INFRA-310)")
    code, out = repo.go("INFRA-285")
    check("286 when the commit that won the race belongs to another issue, the go checks it and stops",
          code != 0 and "Start the next milestone (INFRA-310) (INFRA-310)" in out
          and len(dispatches(repo.calls())) == 1, out)

# ---- Round 1 fixes of INFRA-286 -----------------------------------------------------------------
# s2-J1: a milestone run and a hotfix run each have their own queue, so both can pass their Gate while
# the other moves main. The one whose move comes second must not read as a red batch: nothing in it is to
# blame. Its move says so and says to give the same go again, and that go brings main in and moves main.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    pile_tip = repo.land("Add the go script (INFRA-285)")
    repo.go("--milestone", "Batch on go", "INFRA-285")
    milestone = dispatches(repo.calls())[-1]
    hot = repo.land_hotfix("Stop the sign-in page crashing (INFRA-290)")
    repo.go("--hotfix", "INFRA-290")
    hotfix = dispatches(repo.calls())[-1]
    where, code, out = repo.run_batch(hotfix)
    check("s2-J1 setup: the hotfix's run moves main first", code == 0 and repo.ref("main") == hot, out)
    where, code, out = repo.run_batch(milestone)
    check("s2-J1 the milestone run whose Gate passed after main moved does not move main",
          where == "move" and code != 0 and repo.ref("main") == hot, out)
    check("s2-J1 its move says main moved while the batch ran and nothing in the batch is to blame",
          "while this batch ran" in out and "Nothing in this batch is to blame" in out, out)
    check("s2-J1 its move says to give the same go again, which brings main in",
          "give the same go again" in out and "brings main in" in out, out)
    code, out = repo.go("--milestone", "Batch on go", "INFRA-285")
    where, code, out = repo.run_batch(dispatches(repo.calls())[-1])
    check("s2-J1 the same go given again moves main to the pile and the hotfix together",
          code == 0 and on(repo, hot, repo.ref("main")) and on(repo, pile_tip, repo.ref("main")), out)

# s3-1: --check promises a merge only when the go could make it. Same lines changed on both sides, or a
# CI file left unlike both sides, stop --check the way they stop the go.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    b = repo.land("Change the greeting (INFRA-285)", name="greeting.txt", text="hello from the milestone")
    repo.land_hotfix("Fix the greeting (INFRA-290)", name="greeting.txt", text="hello from the hotfix")
    repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[0])
    code, out = repo.go("--check", "INFRA-285")
    check("s3-1 --check on a pile main cannot be merged into does not promise a merge",
          code != 0 and "a go first brings main into landing" not in out and "greeting.txt" in out, out)
    check("s3-1 that --check pushes and starts nothing", repo.ref("landing") == b and len(dispatches(repo.calls())) == 1,
          out)
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    lint = "\n".join("line {}".format(n) for n in range(1, 21))
    repo.write(".github/workflows/lint.yml", lint + "\n")
    git(repo.work, "add", "-A")
    git(repo.work, "commit", "-q", "-m", "Add lint")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/landing")
    repo.land("Tune lint (INFRA-285)\n\nCI-change-OK: https://linear.app/x/issue/INFRA-285/x#comment-2",
              name=".github/workflows/lint.yml", text=lint.replace("line 20", "line twenty"))
    repo.land_hotfix("Fix lint (INFRA-290)\n\nCI-change-OK: https://linear.app/x/issue/INFRA-290/x#comment-1",
                     name=".github/workflows/lint.yml", text=lint.replace("line 1\n", "line one\n", 1))
    repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[-1])
    code, out = repo.go("--check", "INFRA-285")
    check("s3-1 --check on a merge the push check would refuse says so, and promises nothing",
          code != 0 and "push check refuses" in out and "a go first brings main into landing" not in out, out)

# s3-2: a hotfix that deletes a file the pile changes stops the go, and the stop says what really happened.
with tempfile.TemporaryDirectory() as top:
    repo = Repo(top)
    repo.write("notes.txt", "one\ntwo\nthree\n")
    git(repo.work, "add", "-A")
    git(repo.work, "commit", "-q", "-m", "Add notes")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/landing")
    repo.land("Change the notes (INFRA-285)", name="notes.txt", text="one\nTWO\nthree")
    code, base_out = repo.go("--hotfix", "--base")
    git(repo.work, "fetch", "-q", "origin")
    git(repo.work, "switch", "-q", "--detach", base_out.splitlines()[0])
    git(repo.work, "rm", "-q", "notes.txt")
    git(repo.work, "commit", "-q", "-m", "Remove the notes (INFRA-290)")
    git(repo.work, "push", "-q", "origin", "HEAD:refs/heads/hotfix")
    repo.go("--hotfix", "INFRA-290")
    repo.run_batch(dispatches(repo.calls())[-1])
    code, out = repo.go("INFRA-285")
    check("s3-2 a file deleted on one side and changed on the other stops the go and names the file",
          code != 0 and "notes.txt" in out, out)
    check("s3-2 the stop names deleting a file as a cause, not only the same lines changed",
          "deletes or renames a file the other changes" in out, out)

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
