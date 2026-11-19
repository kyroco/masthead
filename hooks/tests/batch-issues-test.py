#!/usr/bin/env python3
"""Linear issue INFRA-263: the foreman queues nothing, and hands a dropped commit back to its worker.

Each case builds a throwaway repository (a bare "GitHub" remote and a checkout),
lands commits on `landing`, turns a batch red, and runs the real
skills/work-on/bad-commit.py to drop the bad commit, so the records read here
are the ones the search writes. Then it runs the real
skills/work-on/batch-issues.py as the foreman would. gh is the stand-in
hooks/tests/fake-gh.py, which logs every call.

Scenario 1: reading a landing and a batch run queues nothing and opens nothing:
the script makes no gh call but reading runs.
Scenario 2: a dropped commit's worker is told which check failed, and its issue
is listed as sent back, never as merged.
Scenario 3: a commit that reached main in a green batch counts as merged when
the foreman reads that run, including one that came back after a drop.
Scenario 4: a repository whose issues live on GitHub works the same way.
Scenario 5: a commit dropped because it fails with an earlier one: its worker
is told to own the fix end to end, read the earlier issue and every comment on
it first, and comment on both issues once the fix lands.

Run from anywhere: python3 hooks/tests/batch-issues-test.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
SEARCH = os.path.join(PLUGIN, "skills", "work-on", "bad-commit.py")
SCRIPT = os.path.join(PLUGIN, "skills", "work-on", "batch-issues.py")
FAKE_GH = os.path.join(HERE, "fake-gh.py")
GATE = ".github/workflows/gate.yml"
GATE_WORKFLOW = """name: Gate
on: [workflow_call, workflow_dispatch]
jobs:
  tests:
    name: Tests
    runs-on: ubuntu-latest
  static:
    name: Static
    runs-on: ubuntu-latest
  gate:
    name: gate
    needs: [tests, static]
    if: always()
    runs-on: ubuntu-latest
"""

_version = re.search(r"(\d+)\.(\d+)", subprocess.run(["git", "--version"], capture_output=True, text=True).stdout)
if not _version or (int(_version.group(1)), int(_version.group(2))) < (2, 40):
    print("skipped: the search that writes the records needs git 2.40 or newer, and this git is older")
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


def run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def git(cwd, *args):
    r = run(["git", *args], cwd)
    if r.returncode != 0:
        raise SystemExit("git {} failed in {}: {}".format(" ".join(args), cwd, r.stderr))
    return r.stdout.strip()


def job(name, conclusion, steps, start, end):
    return {"name": name, "conclusion": conclusion, "steps": [{"name": n, "conclusion": c} for n, c in steps],
            "startedAt": "2026-11-19T14:{:02d}:00Z".format(start), "completedAt": "2026-11-19T14:{:02d}:00Z".format(end)}


PLAN_OK = job("plan / plan", "success", [("Read the stored Gate", "success")], 0, 1)


class Repo:
    """A bare remote, a checkout of it, and a fake gh whose Gate reads the remote."""

    def __init__(self, linear=True):
        self.tmp = tempfile.mkdtemp(prefix="batch-issues-test-")
        self.remote = os.path.join(self.tmp, "remote.git")
        self.work = os.path.join(self.tmp, "work")
        self.bin = os.path.join(self.tmp, "bin")
        self.state = os.path.join(self.tmp, "gh-state.json")
        git(self.tmp, "init", "--quiet", "--bare", "-b", "main", self.remote)
        git(self.tmp, "clone", "--quiet", self.remote, self.work)
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false")):
            git(self.work, "config", key, value)
        git(self.work, "switch", "--quiet", "-c", "main")
        env = {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "INFRA"} if linear else {}
        self.write(".claude/settings.json", json.dumps({"env": env}))
        self.write(GATE, GATE_WORKFLOW)
        self.write(".claude/gate.json", json.dumps({"workflow": GATE, "starts": ["workflow_call", "workflow_dispatch"]}))
        self.write("README", "base\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "--quiet", "-m", "Base")
        git(self.work, "push", "--quiet", "origin", "main", "main:landing")
        git(self.work, "switch", "--quiet", "-c", "landing", "--track", "origin/landing")
        self.base = git(self.work, "rev-parse", "HEAD")
        os.makedirs(self.bin)
        shim = os.path.join(self.bin, "gh")
        with open(shim, "w") as handle:
            handle.write("#!/bin/sh\nexec python3 '{}' \"$@\"\n".format(FAKE_GH))
        os.chmod(shim, 0o755)
        self.save({"runs": {}, "calls": []})
        self.next_run = 4242

    def write(self, path, text):
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as handle:
            handle.write(text)

    def land(self, files, msg, remove=()):
        git(self.work, "pull", "--quiet", "--rebase", "origin", "landing")
        for name, text in files.items():
            self.write(name, text)
        for name in remove:
            os.remove(os.path.join(self.work, name))
        git(self.work, "add", "-A")
        git(self.work, "commit", "--quiet", "-m", msg)
        git(self.work, "push", "--quiet", "origin", "landing")
        return git(self.work, "rev-parse", "HEAD")

    def load(self):
        with open(self.state) as handle:
            return json.load(handle)

    def save(self, state):
        with open(self.state, "w") as handle:
            json.dump(state, handle)

    def landing(self):
        return git(self.remote, "rev-parse", "refs/heads/landing")

    def batch_run(self, green):
        """Record a batch run on landing's tip, as the starter's run shows it. Green moves main there."""
        sha = self.landing()
        run_id = str(self.next_run)
        self.next_run += 1
        if green:
            jobs = [PLAN_OK, job("gate / Tests", "success", [("Run the tests", "success")], 2, 8),
                    job("gate / gate", "success", [("Decide", "success")], 9, 10),
                    job("move / move", "success", [("Move main", "success")], 10, 11)]
            git(self.remote, "update-ref", "refs/heads/main", sha)
        else:
            jobs = [PLAN_OK, job("gate / Tests", "failure", [("Set up job", "success"), ("Run the tests", "failure")], 2, 8),
                    job("gate / Static", "success", [("Static checks", "success")], 2, 6),
                    job("gate / gate", "failure", [("Decide", "failure")], 9, 10),
                    {"name": "move / move", "conclusion": "skipped", "steps": []}]
        state = self.load()
        state["runs"][run_id] = {"databaseId": int(run_id), "status": "completed",
                                 "conclusion": "success" if green else "failure", "headSha": sha,
                                 "headBranch": "landing", "attempt": 1, "workflow": "Masthead batch",
                                 "workflowName": "Masthead batch", "event": "push",
                                 "url": "https://github.com/example/repo/actions/runs/" + run_id, "jobs": jobs}
        self.save(state)
        return run_id

    def env(self):
        env = dict(os.environ)
        env.update({"PATH": self.bin + os.pathsep + env.get("PATH", ""), "FAKE_GH_STATE": self.state,
                    "FAKE_GH_REMOTE": self.remote, "MASTHEAD_SEARCH_POLL_SECONDS": "0",
                    "MASTHEAD_SEARCH_FIND_TRIES": "2", "CLAUDE_PROJECT_DIR": self.work,
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "Worker", "GIT_AUTHOR_EMAIL": "w@example.com",
                    "GIT_COMMITTER_NAME": "Worker", "GIT_COMMITTER_EMAIL": "w@example.com"})
        return env

    def search(self, run_id):
        out = run([sys.executable, SEARCH, run_id], self.work, self.env())
        git(self.work, "pull", "--quiet", "--rebase", "origin", "landing")
        return out

    def foreman(self, *args):
        before = len(self.load()["calls"])
        out = run([sys.executable, SCRIPT, *args], self.work, self.env())
        calls = self.load()["calls"][before:]
        return out, calls

    def records(self):
        return git(self.remote, "log", "refs/heads/landing", "--format=%H", "--grep=^Masthead-Dropped:").split()

    def done(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def merged_line(text):
    m = re.search(r"^Merged, close and set Done: (.*)$", text, re.M)
    return m.group(1).split(", ") if m else None


def only_reads(calls):
    """True when every gh call reads a run: nothing queued, merged, opened or started."""
    return all(c[:2] in (["run", "view"], ["run", "list"]) for c in calls)


# ---- Scenarios 1, 2 and 3: one bad commit, sent back, then brought back ------

r = Repo()
a = r.land({"a": "1\n"}, "Add a (INFRA-11)")
b = r.land({"breaks": "x\n"}, "Add the part that breaks the tests\n\nFixes INFRA-12")
c = r.land({"c": "3\n"}, "Add c (INFRA-13)")
red = r.batch_run(green=False)
out = r.search(red)
check("setup: the search drops the bad commit", out.returncode == 0 and len(r.records()) == 1, out.stdout + out.stderr)
revert = r.records()[0]

out, calls = r.foreman("merged", red)
check("s2 a red run counts nothing as merged", out.returncode == 1 and merged_line(out.stdout) is None, out.stdout)
check("s2 a red run says to run the search and hand back", "bad-commit.py " + red in out.stdout
      and "batch-issues.py returned" in out.stdout, out.stdout)
check("s1 reading a red run only reads", only_reads(calls), calls)

out, calls = r.foreman("returned")
text = out.stdout
check("s2 returned ends well", out.returncode == 0, text + out.stderr)
check("s2 the dropped commit's issue goes back to its worker", "INFRA-12 goes back to its worker" in text, text)
check("s2 the worker is told which check failed", "Failed check: Tests." in text, text)
check("s2 the foreman is told not to set the issue Done", "Do not set INFRA-12 Done." in text, text)
check("s2 the message names the dropped commit and the revert that dropped it", b in text and revert in text, text)
check("s2 the message says how to bring it back in one push",
      "git revert " + revert in text and "in one push" in text, text)
check("s2 an issue whose commit was not dropped is not handed back",
      "INFRA-11 goes back" not in text and "INFRA-13 goes back" not in text, text)
check("s1 handing back only reads", only_reads(calls) and not calls, calls)
# INFRA-274's push gate refuses a revert and a push on one command line: every command the message
# gives is one git command, and none of them pushes.
commands = re.findall(r"`([^`]*)`", text)
check("the hand-back's commands keep the revert and the push apart, as the push gate needs",
      commands and all("push" not in c and c.count("git ") <= 1 for c in commands), commands)

green = r.batch_run(green=True)
out, calls = r.foreman("merged", green, "--since", r.base)
check("s3 a green run reached by main ends well", out.returncode == 0, out.stdout + out.stderr)
check("s3 the issues the green batch carried to main count as merged",
      merged_line(out.stdout) == ["INFRA-11", "INFRA-13"], out.stdout)
check("s2 the dropped commit's issue is sent back, never merged, though its commit is on main",
      "INFRA-12" not in (merged_line(out.stdout) or []) and "Sent back, not merged, leave open: INFRA-12" in out.stdout,
      out.stdout)
check("s1 reading a green run only reads, and queues nothing", only_reads(calls), calls)

# The worker brings it back: reverts the revert, fixes on top, one push.
git(r.work, "pull", "--quiet", "--rebase", "origin", "landing")
git(r.work, "revert", "--no-edit", revert)
os.remove(os.path.join(r.work, "breaks"))
r.write("b", "fixed\n")
git(r.work, "add", "-A")
git(r.work, "commit", "--quiet", "-m", "Fix the part that broke the tests (INFRA-12)")
git(r.work, "push", "--quiet", "origin", "landing")
again = r.batch_run(green=True)
out, calls = r.foreman("merged", again)
check("s3 the next green run finds where its batch starts from the earlier green run", out.returncode == 0,
      out.stdout + out.stderr)
check("s3 the issue whose commit came back counts as merged once its batch reaches main",
      merged_line(out.stdout) == ["INFRA-12"], out.stdout)
check("s3 an issue already counted in an earlier batch is not counted again",
      "INFRA-11" not in (merged_line(out.stdout) or []), out.stdout)
out, _ = r.foreman("returned")
check("s2 a commit that came back is no longer handed back", "No dropped commit is waiting" in out.stdout, out.stdout)

# A green run main has not reached: nothing is merged yet.
r.land({"d": "4\n"}, "Add d (INFRA-14)")
pending = r.batch_run(green=True)
git(r.remote, "update-ref", "refs/heads/main", git(r.remote, "rev-parse", "refs/heads/landing~1"))
out, calls = r.foreman("merged", pending)
check("s3 a green run main has not reached counts nothing as merged",
      out.returncode == 1 and merged_line(out.stdout) is None and "main has not reached" in out.stdout, out.stdout)
r.done()

# ---- Scenario 5: commits that fail only together ------------------------------

r = Repo()
first = r.land({"half-a": "a\n"}, "Add the first half (INFRA-21)")
r.land({"e": "e\n"}, "Add e (INFRA-23)")
second = r.land({"half-b": "b\n"}, "Add the second half (INFRA-22)")
red = r.batch_run(green=False)
out = r.search(red)
check("s5 setup: the search drops the latest-landed of the two", out.returncode == 0 and len(r.records()) == 1,
      out.stdout + out.stderr)
out, calls = r.foreman("returned")
text = out.stdout
check("s5 the later commit's issue goes back, not the earlier one",
      "INFRA-22 goes back to its worker" in text and "INFRA-21 goes back" not in text, text)
check("s5 the worker is told which check failed", "Failed check: Tests." in text, text)
check("s5 the worker is told it fails only with the earlier commit and its issue",
      "fails only together with {} (INFRA-21)".format(first[:9]) in text, text)
check("s5 the worker owns the fix end to end, whichever commit the fault sits in",
      "It is your job to figure out what needs to be fixed and fix it, end to end" in text
      and "not someone else's commit to hand on" in text, text)
check("s5 the worker reads the earlier issue and every comment on it first",
      "Before you change anything, read INFRA-21 and every comment on it" in text, text)
check("s5 once the fix lands, the worker comments on both issues saying what changed and why",
      "Once your fix lands, add a comment to INFRA-22 and to INFRA-21 saying what you changed and why" in text, text)
check("s1 handing back only reads", not calls, calls)
r.done()

# ---- Scenario 4: a repository whose issues live on GitHub ---------------------

r = Repo(linear=False)
r.land({"a": "1\n"}, "Add a (#31)")
r.land({"breaks": "x\n"}, "Add the part that breaks the tests (#32)")
red = r.batch_run(green=False)
out = r.search(red)
check("s4 setup: the search drops the bad commit on a GitHub repository", len(r.records()) == 1,
      out.stdout + out.stderr)
out, calls = r.foreman("returned")
check("s4 the dropped commit's GitHub issue goes back to its worker, told the failed check",
      "#32 goes back to its worker" in out.stdout and "Failed check: Tests." in out.stdout
      and "Do not set #32 Done." in out.stdout, out.stdout)
green = r.batch_run(green=True)
out, calls = r.foreman("merged", green, "--since", r.base)
check("s4 the GitHub issue the green batch carried counts as merged, the dropped one is sent back",
      merged_line(out.stdout) == ["#31"] and "Sent back, not merged, leave open: #32" in out.stdout, out.stdout)
check("s4 s1 on GitHub too, the foreman's script only reads runs", only_reads(calls), calls)
r.done()

# ---- Round 1 fixes ---------------------------------------------------------------

# s2-1 (arch-1): the worker brings its commit back after the green run and before the foreman
# reads it. The run carried the commit and its revert, not the fix: the issue is still sent back.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-11)")
r.land({"breaks": "x\n"}, "Add the part that breaks the tests (INFRA-12)")
red = r.batch_run(green=False)
r.search(red)
revert = r.records()[0]
green = r.batch_run(green=True)
git(r.work, "revert", "--no-edit", revert)
os.remove(os.path.join(r.work, "breaks"))
r.write("b", "fixed\n")
git(r.work, "add", "-A")
git(r.work, "commit", "--quiet", "-m", "Fix the part that broke the tests (INFRA-12)")
git(r.work, "push", "--quiet", "origin", "landing")
out, _ = r.foreman("merged", green, "--since", r.base)
check("s2-1 an issue brought back after the run it is read from is still sent back in that run",
      merged_line(out.stdout) == ["INFRA-11"] and "Sent back, not merged, leave open: INFRA-12" in out.stdout,
      out.stdout)
r.done()

# s3-1: a commit dropped only because it builds on the bad one comes back as a lone revert of its
# record. That revert is its issue's work, so the green run carrying it lists the issue as merged.
r = Repo()
r.land({"lib": "one\ntwo\nthree\n"}, "Add lib (INFRA-10)")
base = r.landing()
git(r.remote, "update-ref", "refs/heads/main", base)
r.land({"breaks": "x\n", "lib": "one\ntwo by 12\nthree\n"}, "Change lib and break the tests (INFRA-12)")
r.land({"lib": "one\ntwo by 13\nthree\n"}, "Change lib again (INFRA-13)")
red = r.batch_run(green=False)
out = r.search(red)
recs = r.records()
check("s3-1 setup: the search drops the bad commit and the one that builds on it", len(recs) == 2,
      out.stdout + out.stderr)
r.batch_run(green=True)
by_issue = {}
for sha in recs:
    body = git(r.work, "log", "-1", "--format=%B", sha)
    by_issue[re.search(r"^Masthead-Issue: (.*)$", body, re.M).group(1)] = sha
git(r.work, "revert", "--no-edit", by_issue["INFRA-12"])
os.remove(os.path.join(r.work, "breaks"))
git(r.work, "add", "-A")
git(r.work, "commit", "--quiet", "-m", "Fix the tests (INFRA-12)")
git(r.work, "push", "--quiet", "origin", "landing")
r.batch_run(green=True)
git(r.work, "revert", "--no-edit", by_issue["INFRA-13"])
git(r.work, "push", "--quiet", "origin", "landing")
back = r.batch_run(green=True)
out, _ = r.foreman("merged", back)
check("s3-1 an issue whose only commit in the batch is the revert of its record counts as merged",
      merged_line(out.stdout) == ["INFRA-13"], out.stdout)
r.done()

# arch-2: an issue whose own work is a revert of an ordinary commit counts as merged.
r = Repo()
old = r.land({"a": "1\n"}, "Add a (INFRA-50)")
r.batch_run(green=True)
mark = r.landing()
git(r.work, "revert", "--no-edit", old)
git(r.work, "commit", "--quiet", "--amend", "-m", "Take a out again (INFRA-51)\n\nThis reverts commit {}.".format(old))
git(r.work, "push", "--quiet", "origin", "landing")
green = r.batch_run(green=True)
out, _ = r.foreman("merged", green, "--since", mark)
check("arch-2 an issue whose own work is a revert of an ordinary commit counts as merged",
      merged_line(out.stdout) == ["INFRA-51"], out.stdout)
r.done()


def record_commit(repo, dropped, issue):
    """A drop record as bad-commit.py writes it, for a dropped commit whose message names no issue."""
    repo.write("rec-" + dropped[:7], "x\n")
    git(repo.work, "add", "-A")
    git(repo.work, "commit", "--quiet", "-m", "Drop {} from landing\n\nMasthead-Dropped: {}\nMasthead-Issue: {}\n"
        "Masthead-Failed-Check: Tests\nMasthead-Red-Run: https://example/runs/1\nMasthead-Batch: {}\n"
        "Masthead-Bring-Back: revert-this-commit-and-fix-in-one-push\n".format(dropped[:9], dropped, issue, dropped))
    git(repo.work, "push", "--quiet", "origin", "landing")
    return git(repo.work, "rev-parse", "HEAD")


# arch-3: a dropped commit whose message names no issue. When it brings an earlier drop back, it
# is that issue's; otherwise it goes to the person, never to a worker of an issue called "none found".
r = Repo()
r.land({"breaks": "x\n"}, "Break the tests (INFRA-60)")
red = r.batch_run(green=False)
r.search(red)
first = r.records()[0]
git(r.work, "revert", "--no-edit", first)
git(r.work, "push", "--quiet", "origin", "landing")
bring_back = git(r.work, "rev-parse", "HEAD")
record_commit(r, bring_back, "none found")
loose = r.land({"z": "z\n"}, "Tidy something")
record_commit(r, loose, "none found")
out, _ = r.foreman("returned")
check("arch-3 a dropped bring-back that names no issue goes back to the issue it brought back",
      "INFRA-60 goes back to its worker: {}".format(bring_back[:9]) in out.stdout, out.stdout)
check("arch-3 no message goes to an issue called none found", "none found goes back" not in out.stdout
      and "Do not set none found Done" not in out.stdout, out.stdout)
check("arch-3 a dropped commit with no issue goes to the person, named",
      "{} names no issue: tell the person".format(loose[:9]) in out.stdout, out.stdout)
r.done()

# s4-judge-1: a dropped commit's closing words ("Fixes #32", "Fixes INFRA-12") can close its issue
# when it reaches main with its revert. The sent-back line tells the foreman to reopen it.
for linear, key, msg in ((False, "#72", "Break the tests\n\nFixes #72"),
                         (True, "INFRA-72", "Break the tests\n\nFixes INFRA-72")):
    r = Repo(linear=linear)
    r.land({"breaks": "x\n"}, msg)
    red = r.batch_run(green=False)
    r.search(red)
    green = r.batch_run(green=True)
    out, _ = r.foreman("merged", green, "--since", r.base)
    check("s4-judge-1 a sent-back issue closed by its commit's closing words is to be reopened ({})".format(key),
          "If its commit's closing words closed {} or set it Done, reopen it".format(key) in out.stdout, out.stdout)
    r.done()

# ---- Usage ---------------------------------------------------------------------

r = Repo()
out, _ = r.foreman("merged")
check("a call with no run id prints the usage", out.returncode == 2 and "Usage:" in out.stdout, out.stdout)
out, _ = r.foreman("merged", "notanumber")
check("a run id that is not a number prints the usage", out.returncode == 2, out.stdout)
r.land({"a": "1\n"}, "Add a (INFRA-41)")
first_green = r.batch_run(green=True)
out, _ = r.foreman("merged", first_green)
check("the first green batch with no --since stops and asks for it",
      out.returncode == 1 and "--since" in out.stdout and merged_line(out.stdout) is None, out.stdout)
r.done()

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
