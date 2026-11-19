#!/usr/bin/env python3
"""Linear issues INFRA-263 and INFRA-288: the foreman queues nothing, and a red batch's bad change stays on landing.

Each case builds a throwaway repository (a bare "GitHub" remote and a checkout),
lands commits on `landing`, turns a batch red, and runs the real
skills/work-on/bad-commit.py to name the bad change. Then it runs the real
skills/work-on/batch-issues.py as the foreman would. gh is the stand-in
hooks/tests/fake-gh.py, which logs every call.

INFRA-263 scenario 1: reading a landing and a batch run queues nothing and
opens nothing: the script makes no gh call but reading runs.
INFRA-288 scenario 3: a red run counts nothing as merged and main stays where it
was, until a later run is green with the fix on top.
INFRA-263 scenario 3: a commit that reached main in a green batch counts as
merged when the foreman reads that run: the named change and its fix included,
since nothing was taken off landing (INFRA-288 scenario 1).
INFRA-263 scenario 4: a repository whose issues live on GitHub works the same way.

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

    def batch_run(self, green, branch="landing"):
        """Record a batch run on the pile's tip (landing, or hotfix for a hotfix's own pile), as the
        starter's run shows it. Green moves main there."""
        sha = git(self.remote, "rev-parse", "refs/heads/" + branch)
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
                                 "headBranch": branch, "attempt": 1, "workflow": "Masthead batch",
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
        return run([sys.executable, SEARCH, run_id], self.work, self.env())

    def foreman(self, *args):
        before = len(self.load()["calls"])
        out = run([sys.executable, SCRIPT, *args], self.work, self.env())
        calls = self.load()["calls"][before:]
        return out, calls

    def main(self):
        return git(self.remote, "rev-parse", "refs/heads/main")

    def done(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def merged_line(text):
    m = re.search(r"^Merged, close and set Done: (.*)$", text, re.M)
    return m.group(1).split(", ") if m else None


def only_reads(calls):
    """True when every gh call reads a run: nothing queued, merged, opened or started."""
    return all(c[:2] in (["run", "view"], ["run", "list"]) for c in calls)


# ---- A red batch, its change named, then fixed on top ---------------------------

r = Repo()
a = r.land({"a": "1\n"}, "Add a (INFRA-11)")
b = r.land({"breaks": "x\n"}, "Add the part that breaks the tests\n\nFixes INFRA-12")
c = r.land({"c": "3\n"}, "Add c (INFRA-13)")
red_tip = r.landing()
red = r.batch_run(green=False)
out = r.search(red)
check("setup: the search names the bad change", out.returncode == 0 and "Masthead-Bad-Change: " + b in out.stdout,
      out.stdout + out.stderr)
check("288 s1 the named change is still on landing, at the same tip", r.landing() == red_tip)

out, calls = r.foreman("merged", red)
check("288 s3 a red run counts nothing as merged", out.returncode == 1 and merged_line(out.stdout) is None, out.stdout)
check("288 s3 a red run says main did not move", "main did not move" in out.stdout, out.stdout)
check("288 s2 a red run says to run the search and hand the named change back to its worker",
      "bad-commit.py " + red in out.stdout and "hand the change it names back to its worker" in out.stdout, out.stdout)
check("288 no word of a returned command any more", "batch-issues.py returned" not in out.stdout, out.stdout)
check("263 s1 reading a red run only reads", only_reads(calls), calls)
check("288 s3 main has not moved", r.main() == r.base)

# The worker fixes it on top of the pile: one more commit on landing, nothing reverted.
git(r.work, "pull", "--quiet", "--rebase", "origin", "landing")
os.remove(os.path.join(r.work, "breaks"))
r.write("b", "fixed\n")
git(r.work, "add", "-A")
git(r.work, "commit", "--quiet", "-m", "Fix the part that broke the tests (INFRA-12)")
git(r.work, "push", "--quiet", "origin", "landing")
green = r.batch_run(green=True)
out, calls = r.foreman("merged", green, "--since", r.base)
check("263 s3 a green run reached by main ends well", out.returncode == 0, out.stdout + out.stderr)
check("288 s3 263 s3 the green run with the fix on top carries every issue to main, the named one included",
      merged_line(out.stdout) == ["INFRA-11", "INFRA-12", "INFRA-13"], out.stdout)
check("288 nothing is listed as sent back", "Sent back" not in out.stdout, out.stdout)
check("263 s1 reading a green run only reads, and queues nothing", only_reads(calls), calls)

# The next green run finds where its batch starts from the earlier green run.
r.land({"d": "4\n"}, "Add d (INFRA-14)")
again = r.batch_run(green=True)
out, calls = r.foreman("merged", again)
check("263 s3 the next green run finds where its batch starts, and counts no issue twice",
      out.returncode == 0 and merged_line(out.stdout) == ["INFRA-14"], out.stdout + out.stderr)

# A green run main has not reached: nothing is merged yet.
r.land({"e": "5\n"}, "Add e (INFRA-15)")
pending = r.batch_run(green=True)
git(r.remote, "update-ref", "refs/heads/main", git(r.remote, "rev-parse", "refs/heads/landing~1"))
out, calls = r.foreman("merged", pending)
check("263 s3 a green run main has not reached counts nothing as merged",
      out.returncode == 1 and merged_line(out.stdout) is None and "main has not reached" in out.stdout, out.stdout)
r.done()

# ---- INFRA-263 scenario 4: a repository whose issues live on GitHub ---------------

r = Repo(linear=False)
r.land({"a": "1\n"}, "Add a (#31)")
bad = r.land({"breaks": "x\n"}, "Add the part that breaks the tests (#32)")
red = r.batch_run(green=False)
out = r.search(red)
check("263 s4 the search names the bad change's GitHub issue",
      "Masthead-Issue: #32" in out.stdout and "--- post on #32 as a comment" in out.stdout, out.stdout)
git(r.work, "pull", "--quiet", "--rebase", "origin", "landing")
os.remove(os.path.join(r.work, "breaks"))
git(r.work, "add", "-A")
git(r.work, "commit", "--quiet", "-m", "Fix the tests (#32)")
git(r.work, "push", "--quiet", "origin", "landing")
green = r.batch_run(green=True)
out, calls = r.foreman("merged", green, "--since", r.base)
check("263 s4 on GitHub, the green batch with the fix carries both issues to main",
      merged_line(out.stdout) == ["#31", "#32"], out.stdout)
check("263 s4 s1 on GitHub too, the foreman's script only reads runs", only_reads(calls), calls)
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

# ---- INFRA-286 arch-1: a hotfix's own run is read like any batch run ----------------
# After a green hotfix run, the foreman reads it to close the hotfix's issue. A later milestone batch that
# brought main in with one merge carries only its own issues: the hotfix was merged by its own run.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-11)")
r.batch_run(green=True)
git(r.work, "fetch", "--quiet", "origin")
git(r.work, "switch", "--quiet", "--detach", "origin/main")
r.write("hot", "fixed\n")
git(r.work, "add", "-A")
git(r.work, "commit", "--quiet", "-m", "Stop the sign-in page crashing (INFRA-290)")
git(r.work, "push", "--quiet", "origin", "HEAD:refs/heads/hotfix")
hot = git(r.work, "rev-parse", "HEAD")
hot_run = r.batch_run(green=True, branch="hotfix")
out, calls = r.foreman("merged", hot_run)
check("286 arch-1 a green hotfix run is read, not refused as off landing", out.returncode == 0, out.stdout + out.stderr)
check("286 arch-1 it lists the hotfix's issue as merged, and only that", merged_line(out.stdout) == ["INFRA-290"],
      out.stdout)
check("286 arch-1 reading a hotfix run only reads", only_reads(calls), calls)
git(r.work, "switch", "--quiet", "landing")
r.land({"c": "3\n"}, "Add c (INFRA-13)")
pile = r.landing()
tree = git(r.work, "merge-tree", "--write-tree", pile, hot).split()[0]
merge = git(r.work, "commit-tree", tree, "-p", pile, "-p", hot, "-m", "Bring main into landing for the go (INFRA-290)")
git(r.work, "push", "--quiet", "origin", merge + ":refs/heads/landing")
later = r.batch_run(green=True)
out, _ = r.foreman("merged", later)
check("286 arch-1 the later milestone batch lists only its own issue, not the hotfix again",
      merged_line(out.stdout) == ["INFRA-13"], out.stdout)
r.done()

# ---- Usage ---------------------------------------------------------------------

r = Repo()
out, _ = r.foreman("merged")
check("a call with no run id prints the usage", out.returncode == 2 and "Usage:" in out.stdout, out.stdout)
out, _ = r.foreman("merged", "notanumber")
check("a run id that is not a number prints the usage", out.returncode == 2, out.stdout)
out, _ = r.foreman("returned")
check("288 returned is gone: nothing is ever dropped, so nothing waits to come back",
      out.returncode == 2 and "returned" not in out.stdout, out.stdout)
r.land({"a": "1\n"}, "Add a (INFRA-41)")
first_green = r.batch_run(green=True)
out, _ = r.foreman("merged", first_green)
check("the first green batch with no --since stops and asks for it",
      out.returncode == 1 and "--since" in out.stdout and merged_line(out.stdout) is None, out.stdout)
r.done()

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
