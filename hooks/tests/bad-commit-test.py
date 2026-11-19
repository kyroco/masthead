#!/usr/bin/env python3
"""Linear issue INFRA-269: find the commit that turned a batch red, drop it from landing, and say whose it is.

Each case builds a throwaway repository (a bare "GitHub" remote and a checkout),
lands commits on `landing`, records a red batch run, and runs the real
skills/work-on/bad-commit.py against it. gh is the stand-in hooks/tests/fake-gh.py,
whose Gate is red or green from the files in each commit, so the search runs
real git and starts and reads Gate runs as it would on GitHub.

Scenario 1: one commit fails, the others pass: it is off landing's code, the
others stay, and the new landing tip is a plain push the batch run tests again.
Scenario 2: the dropped commit goes back to its worker: the record names its issue.
Scenario 3: red only because a runner could not start or fetch the code: the
failed jobs run again and nothing is dropped.
Scenario 4: the record names the commit, its issue and the failed check, in the
revert's message on landing, where the foreman reads it.
Scenario 5: the search runs the stored Gate and never works it out; with none
stored it stops and says so.
Scenario 6: no commit fails alone but some fail together: the latest-landed is
dropped and the record names each commit it fails with, and their issues.

Run from anywhere: python3 hooks/tests/bad-commit-test.py
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
FAKE_GH = os.path.join(HERE, "fake-gh.py")
STARTER = os.path.join(PLUGIN, "skills", "setup", "batch-starter.yml")
GATE = ".github/workflows/gate.yml"
RED_RUN = "4242"
REAL_GIT = shutil.which("git")
# The stored Gate's own file: its `gate` job runs always(), after the others, so it is the Gate's verdict job.
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
# A Gate whose two jobs run one after another and that has no verdict job (arch-2).
CHAIN_WORKFLOW = """name: Gate
on: [workflow_call, workflow_dispatch]
jobs:
  tests:
    name: Tests
    runs-on: [self-hosted, macbook-air]
  lint:
    name: Lint
    needs: tests
    runs-on: [self-hosted, macbook-air]
"""

_version = re.search(r"(\d+)\.(\d+)", subprocess.run(["git", "--version"], capture_output=True, text=True).stdout)
if not _version or (int(_version.group(1)), int(_version.group(2))) < (2, 38):
    print("skipped: the search needs git 2.38 or newer (merge-tree --write-tree), and this git is older")
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


def run(cmd, cwd, env=None, inp=None):
    return subprocess.run(cmd, cwd=cwd, env=env, input=inp, capture_output=True, text=True)


def job(name, conclusion, steps, start, end):
    """A job as gh run view --json jobs shows it; steps are (name, conclusion) pairs."""
    return {"name": name, "conclusion": conclusion, "steps": [{"name": n, "conclusion": c} for n, c in steps],
            "startedAt": "2026-11-19T14:{:02d}:00Z".format(start), "completedAt": "2026-11-19T14:{:02d}:00Z".format(end)}


PLAN_OK = job("plan / plan", "success", [("Read the stored Gate", "success")], 0, 1)
MOVE_SKIPPED = {"name": "move / move", "conclusion": "skipped", "steps": []}


def git(cwd, *args):
    r = run(["git", *args], cwd)
    if r.returncode != 0:
        raise SystemExit("git {} failed in {}: {}".format(" ".join(args), cwd, r.stderr))
    return r.stdout.strip()


class Repo:
    """A bare remote, a checkout of it, and a fake gh whose Gate reads the remote."""

    def __init__(self, gate=True, decoy=False, starts=("workflow_call", "workflow_dispatch"), workflow=GATE_WORKFLOW,
                 old_git=False):
        self.tmp = tempfile.mkdtemp(prefix="bad-commit-test-")
        self.remote = os.path.join(self.tmp, "remote.git")
        self.work = os.path.join(self.tmp, "work")
        self.bin = os.path.join(self.tmp, "bin")
        self.state = os.path.join(self.tmp, "gh-state.json")
        git(self.tmp, "init", "--quiet", "--bare", "-b", "main", self.remote)
        git(self.tmp, "clone", "--quiet", self.remote, self.work)
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false")):
            git(self.work, "config", key, value)
        git(self.work, "switch", "--quiet", "-c", "main")
        self.write(".claude/settings.json", json.dumps({"env": {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "INFRA"}}))
        self.workflow = ".github/workflows/real-gate.yml" if decoy else GATE
        self.write(self.workflow, workflow)
        if decoy:
            self.write(GATE, "name: Not the Gate\non: [workflow_call, workflow_dispatch]\n")
        if gate:
            self.write(".claude/gate.json", json.dumps({"workflow": self.workflow, "starts": list(starts)}))
        self.write("README", "base\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "--quiet", "-m", "Base")
        git(self.work, "push", "--quiet", "origin", "main", "main:landing")
        git(self.work, "switch", "--quiet", "-c", "landing", "--track", "origin/landing")
        os.makedirs(self.bin)
        shim = os.path.join(self.bin, "gh")
        with open(shim, "w") as handle:
            handle.write("#!/bin/sh\nexec python3 '{}' \"$@\"\n".format(FAKE_GH))
        os.chmod(shim, 0o755)
        if old_git:
            # A git that says it is 2.39: merge-tree has --write-tree there, but not --merge-base (V-S6-J1).
            fake_git = os.path.join(self.bin, "git")
            with open(fake_git, "w") as handle:
                handle.write('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version 2.39.5"; exit 0; fi\n'
                             'exec \'{}\' "$@"\n'.format(REAL_GIT))
            os.chmod(fake_git, 0o755)
        self.save({"runs": {}, "calls": []})

    def write(self, path, text):
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as handle:
            handle.write(text)

    def land(self, files, msg):
        """One commit on landing adding `files` (name -> text), pushed as a worker would."""
        for name, text in files.items():
            self.write(name, text)
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

    def red_batch(self, tests_step="Run the tests", sha=None, extra_jobs=(), jobs=None):
        """Record the batch run on landing's tip as red, the way the starter's run shows it."""
        sha = sha or git(self.work, "rev-parse", "origin/landing")
        if jobs is None:
            if tests_step == "Set up job":
                tests = job("gate / Tests", "failure", [("Set up job", "failure")], 2, 3)
            else:
                tests = job("gate / Tests", "failure", [("Set up job", "success"), (tests_step, "failure")], 2, 8)
            jobs = [PLAN_OK, tests, job("gate / Static", "success", [("Static checks", "success")], 2, 6)]
            jobs += list(extra_jobs)
            jobs += [job("gate / gate", "failure", [("Decide", "failure")], 9, 10), MOVE_SKIPPED]
        state = self.load()
        state["runs"][RED_RUN] = {"databaseId": int(RED_RUN), "status": "completed", "conclusion": "failure",
                                  "headSha": sha, "headBranch": "landing", "attempt": 1, "workflow": "batch.yml",
                                  "url": "https://github.com/example/repo/actions/runs/" + RED_RUN, "jobs": jobs}
        self.save(state)
        return sha

    def search(self, run_id=RED_RUN):
        env = dict(os.environ)
        env.update({"PATH": self.bin + os.pathsep + env.get("PATH", ""), "FAKE_GH_STATE": self.state,
                    "FAKE_GH_REMOTE": self.remote, "MASTHEAD_SEARCH_POLL_SECONDS": "0",
                    "MASTHEAD_SEARCH_FIND_TRIES": "2", "CLAUDE_PROJECT_DIR": self.work,
                    # As on CI's ubuntu-latest: no global git config, so no identity outside the work clone (arch-4).
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        return run([sys.executable, SEARCH, run_id], self.work, env)

    def landing(self):
        return git(self.remote, "rev-parse", "refs/heads/landing")

    def files_on_landing(self):
        return set(git(self.remote, "ls-tree", "-r", "--name-only", "refs/heads/landing").split())

    def dispatches(self):
        return [c for c in self.load()["calls"] if c[:2] == ["workflow", "run"]]

    def reruns(self):
        return [c for c in self.load()["calls"] if c[:2] == ["run", "rerun"]]

    def trailers(self, sha):
        text = git(self.remote, "log", "-1", "--format=%B", sha)
        parsed = run(["git", "interpret-trailers", "--parse"], self.remote, inp=text).stdout
        out = {}
        for line in parsed.splitlines():
            key, _, value = line.partition(": ")
            out.setdefault(key, []).append(value)
        return out

    def records(self):
        """The record commits a foreman finds on landing, newest first."""
        return git(self.remote, "log", "refs/heads/landing", "--format=%H", "--grep=^Masthead-Dropped:").split()

    def is_ancestor(self, a, b):
        return run(["git", "merge-base", "--is-ancestor", a, b], self.remote).returncode == 0

    def done(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---- Scenarios 1, 2 and 4: one commit fails alone -----------------------------

r = Repo()
c1 = r.land({"a": "1\n"}, "Add a (INFRA-301)")
c2 = r.land({"breaks": "x\n"}, "Add the part that breaks the tests\n\nFixes INFRA-302")
c3 = r.land({"c": "3\n"}, "Add c (INFRA-303)")
c4 = r.land({"d": "4\n"}, "Add d (INFRA-304)")
before = r.red_batch()
out = r.search()
check("s1 the search ends well", out.returncode == 0, out.stdout + out.stderr)
tip = r.landing()
files = r.files_on_landing()
check("s1 the failing commit's change is no longer on landing", "breaks" not in files, files)
check("s1 the other commits' changes are still on landing", {"a", "c", "d"} <= files, files)
check("s1 every other commit is still on landing", all(r.is_ancestor(c, tip) for c in (c1, c3, c4)))
check("s1 landing moved forward with a plain push, nothing rewritten", r.is_ancestor(before, tip) and tip != before)
starter = open(STARTER).read()
check("s1 the new landing tip is a push the batch run tests again (starter runs on each push to landing)",
      "on:\n  push:\n    branches: [landing]" in starter and git(r.remote, "rev-parse", tip + "^") == before)
check("s1 one bad of four commits costs log2(4) + 1 = 3 Gate runs", len(r.dispatches()) == 3, r.dispatches())
check("s1 no throwaway search branch is left on GitHub",
      git(r.remote, "for-each-ref", "--format=%(refname)", "refs/heads/masthead-search") == "")
rec = r.trailers(tip)
check("s4 the record names the dropped commit", rec.get("Masthead-Dropped") == [c2], rec)
check("s2 s4 the record names the issue it belongs to, the way back to its worker",
      rec.get("Masthead-Issue") == ["INFRA-302"], rec)
check("s4 the record names the check that failed, not the Gate's verdict job",
      rec.get("Masthead-Failed-Check") == ["Tests"], rec)
check("s4 the record says how the worker brings it back",
      rec.get("Masthead-Bring-Back") == ["revert-this-commit-and-fix-in-one-push"], rec)
check("s4 the record names the batch and the red run",
      rec.get("Masthead-Batch") == [before] and rec.get("Masthead-Red-Run", [""])[0].startswith("https://"), rec)
check("s1 a commit that fails alone names no commit it fails with", "Masthead-Fails-With" not in rec, rec)
check("s4 the foreman finds the record on landing with git log --grep", r.records() == [tip], r.records())
check("s2 the search says which commit and issue went back", c2[:9] in out.stdout and "INFRA-302" in out.stdout,
      out.stdout)
r.done()

# A batch of one commit: the batch run itself showed it red, so no Gate run is needed.
r = Repo()
only = r.land({"breaks": "x\n"}, "Break it (INFRA-310)")
r.red_batch()
out = r.search()
check("s1 one commit in the batch is dropped with no extra Gate run",
      out.returncode == 0 and r.dispatches() == [] and r.trailers(r.landing()).get("Masthead-Dropped") == [only],
      out.stdout + out.stderr)
r.done()

# ---- Scenario 6: commits that fail only together ------------------------------

r = Repo()
p1 = r.land({"half-a": "a\n"}, "Add half a (INFRA-321)")
r.land({"e": "e\n"}, "Add e (INFRA-322)")
p3 = r.land({"half-b": "b\n"}, "Add half b (INFRA-323)")
r.land({"f": "f\n"}, "Add f (INFRA-324)")
r.red_batch()
out = r.search()
check("s6 the search ends well", out.returncode == 0, out.stdout + out.stderr)
rec = r.trailers(r.landing())
check("s6 the latest-landed of the commits that fail together is dropped", rec.get("Masthead-Dropped") == [p3], rec)
check("s6 the record names its issue", rec.get("Masthead-Issue") == ["INFRA-323"], rec)
check("s6 the record names each commit it fails with, and their issues",
      rec.get("Masthead-Fails-With") == ["{} INFRA-321".format(p1)], rec)
files = r.files_on_landing()
check("s6 the rest stay on landing, the dropped change does not", {"half-a", "e", "f"} <= files and "half-b" not in files,
      files)
check("s6 the record names the failed check", rec.get("Masthead-Failed-Check") == ["Tests"], rec)
r.done()

r = Repo()
q1 = r.land({"trio-1": "1\n"}, "Add trio 1 (INFRA-331)")
q2 = r.land({"trio-2": "2\n"}, "Add trio 2 (INFRA-332)")
r.land({"g": "g\n"}, "Add g (INFRA-333)")
q4 = r.land({"trio-3": "3\n"}, "Add trio 3 (INFRA-334)")
r.red_batch()
out = r.search()
rec = r.trailers(r.landing())
check("s6 three commits that fail only together: the last is dropped, both others named",
      out.returncode == 0 and rec.get("Masthead-Dropped") == [q4] and
      rec.get("Masthead-Fails-With") == ["{} INFRA-331".format(q1), "{} INFRA-332".format(q2)],
      out.stdout + out.stderr + str(rec))
r.done()

# A commit that only applies on top of an earlier one fails with it.
r = Repo()
d1 = r.land({"lib": "one\n"}, "Add lib (INFRA-341)")
r.land({"lib": "one\ntwo\n", "breaks": "x\n"}, "Change lib and break it (INFRA-342)")
r.red_batch()
out = r.search()
rec = r.trailers(r.landing())
check("s6 a commit that cannot apply alone is dropped and names the commit it needs",
      out.returncode == 0 and rec.get("Masthead-Issue") == ["INFRA-342"] and
      rec.get("Masthead-Fails-With") == ["{} INFRA-341".format(d1)],
      out.stdout + out.stderr + str(rec))
check("s6 with no search run red, the batch is run once more to confirm before any blame (2 runs here)",
      len(r.dispatches()) == 2 and rec.get("Masthead-Red-Run", [""])[0].endswith("/5001"), (r.dispatches(), rec))
r.done()

# ---- Scenario 3: red only because a runner could not start ---------------------

for step in ("Set up job", "Run actions/checkout@v5"):
    r = Repo()
    r.land({"breaks": "x\n"}, "Break it (INFRA-351)")
    before = r.red_batch(tests_step=step)
    out = r.search()
    check("s3 '{}' failing: the failed jobs run again".format(step),
          out.returncode == 0 and r.reruns() == [["run", "rerun", RED_RUN, "--failed"]], out.stdout + out.stderr)
    check("s3 '{}' failing: no commit is dropped and no search runs".format(step),
          r.landing() == before and r.dispatches() == [] and r.records() == [])
    r.done()

# A runner failure next to a real failed check is a real red: it is searched, not rerun.
r = Repo()
r.land({"breaks": "x\n"}, "Break it (INFRA-352)")
r.red_batch(extra_jobs=[job("gate / Lint", "failure", [("Set up job", "failure")], 2, 3)])
out = r.search()
check("s3 a runner failure beside a real failure does not hide it: the commit is dropped",
      out.returncode == 0 and r.reruns() == [] and r.records() != [], out.stdout + out.stderr)
r.done()

# A Gate run the search starts that hits a runner failure is run again, not read as green or red.
r = Repo()
first = r.land({"a": "1\n"}, "Add a (INFRA-361)")
bad = r.land({"breaks": "x\n"}, "Break it (INFRA-362)")
r.red_batch()
state = r.load()
state["start_failures"] = {first: 1}
r.save(state)
out = r.search()
check("s3 a search run whose runner could not start is run again before it is read",
      out.returncode == 0 and len(r.reruns()) == 1 and r.trailers(r.landing()).get("Masthead-Dropped") == [bad],
      out.stdout + out.stderr)
r.done()

# ---- Scenario 5: the stored Gate, and none stored ------------------------------

r = Repo(decoy=True)
r.land({"a": "1\n"}, "Add a (INFRA-371)")
r.land({"breaks": "x\n"}, "Break it (INFRA-372)")
r.land({"c": "1\n"}, "Add c (INFRA-373)")
r.red_batch()
out = r.search()
names = {c[2] for c in r.dispatches()}
check("s5 the search runs the stored Gate, not the decoy gate.yml beside it",
      out.returncode == 0 and r.dispatches() and names == {"real-gate.yml"}, (names, out.stdout + out.stderr))
check("s5 each search run is on a throwaway branch, never on landing or main",
      all(c[c.index("--ref") + 1].startswith("masthead-search/") for c in r.dispatches()), r.dispatches())
r.done()

r = Repo(gate=False)
r.land({"breaks": "x\n"}, "Break it (INFRA-374)")
before = r.red_batch()
out = r.search()
check("s5 with no Gate stored the search stops and says so",
      out.returncode != 0 and "No Gate is stored in .claude/gate.json" in out.stdout, out.stdout + out.stderr)
check("s5 with no Gate stored nothing is asked of GitHub and nothing is dropped",
      r.load()["calls"] == [] and r.landing() == before)
r.done()

r = Repo(starts=("workflow_call",))
r.land({"breaks": "x\n"}, "Break it (INFRA-375)")
before = r.red_batch()
out = r.search()
check("s5 a stored Gate that cannot be dispatched stops the search and says why",
      out.returncode != 0 and "workflow_dispatch" in out.stdout and r.landing() == before, out.stdout)
r.done()

# ---- What the search refuses to blame ------------------------------------------

r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-381)")
r.land({"b": "1\n"}, "Add b (INFRA-382)")
before = r.red_batch()
out = r.search()
check("a red that does not happen again in any search run drops nothing and says so",
      out.returncode != 0 and "did not happen again" in out.stdout and r.landing() == before and r.records() == [],
      out.stdout + out.stderr)
r.done()

r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-383)")
r.land({"breaks": "x\n"}, "Break it (INFRA-384)")
before = r.red_batch()
state = r.load()
state["land_during"] = True
r.save(state)
out = r.search()
tip = r.landing()
landed = git(r.remote, "log", "--format=%s", "{}..{}".format(before, tip)).splitlines()
check("a worker landing while the search runs loses nothing: the revert goes on top of their commit",
      out.returncode == 0 and any("meanwhile" in s for s in landed) and r.is_ancestor(before, tip) and
      "breaks" not in r.files_on_landing(), (out.stdout + out.stderr, landed))
r.done()

# V-S1-2: later work changes the same lines as the failing commit, so the failing
# commit cannot come off alone. It still comes off: with the commits that build on it.
r = Repo()
r.land({"lib": "one\n"}, "Add lib (INFRA-391)")
bad = r.land({"lib": "one\nbreaks\n", "breaks": "x\n"}, "Break lib (INFRA-392)")
r.red_batch()
r.land({"other": "o\n"}, "Add other (INFRA-395)")
later = r.land({"lib": "one\nbreaks\nthree\n"}, "Build on lib (INFRA-393)")
after = r.landing()
out = r.search()
tip = r.landing()
files = r.files_on_landing()
lib = git(r.remote, "show", "refs/heads/landing:lib")
check("s1 a failing commit later work builds on still comes off landing, by a plain push",
      out.returncode == 0 and "breaks" not in files and lib == "one" and r.is_ancestor(after, tip),
      (out.stdout + out.stderr, files, lib))
recs = {tuple(r.trailers(sha).get("Masthead-Dropped", [])): r.trailers(sha) for sha in r.records()}
check("s1 the commit that builds on it comes off with it, its record saying what it builds on",
      recs.get((later,), {}).get("Masthead-Builds-On") == ["{} INFRA-392".format(bad)] and
      recs.get((later,), {}).get("Masthead-Issue") == ["INFRA-393"] and
      "Masthead-Failed-Check" not in recs.get((later,), {}), recs)
check("s1 s4 the failing commit's own record still names it, its issue and the failed check",
      recs.get((bad,), {}).get("Masthead-Issue") == ["INFRA-392"] and
      recs.get((bad,), {}).get("Masthead-Failed-Check") == ["Tests"], recs)
check("s1 a commit that does not build on it stays on landing", "other" in files, files)
r.done()

# V-S1-1: a later red batch still holds a commit an earlier search dropped, with its
# revert. The search blames the commit that fails now, not the one already dropped.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-401)")
first_bad = r.land({"breaks": "x\n"}, "Break it (INFRA-402)")
r.red_batch()
out = r.search()
check("v-s1-1 the first search drops the first bad commit", out.returncode == 0 and len(r.records()) == 1,
      out.stdout + out.stderr)
git(r.work, "pull", "--quiet", "--rebase", "origin", "landing")
now_bad = r.land({"half-a": "a\n", "half-b": "b\n"}, "Break it another way (INFRA-404)")
for n in range(4):
    r.land({"later-{}".format(n): "1\n"}, "Add later {} (INFRA-41{})".format(n, n))
# main..batch is a, the first bad commit, its revert, the commit that fails now and four more:
# halving tests the prefix that ends at the first bad commit, which is red without its revert.
r.red_batch()
state = r.load()
state["calls"] = []
r.save(state)
out = r.search()
records = r.records()
latest = r.trailers(records[0]) if records else {}
check("v-s1-1 the next red batch drops the commit that fails now, not the one already dropped",
      out.returncode == 0 and latest.get("Masthead-Dropped") == [now_bad] and len(records) == 2,
      (out.stdout + out.stderr, latest))
check("v-s1-1 that commit's change is off landing, and the first drop still holds",
      not {"half-a", "half-b", "breaks"} & r.files_on_landing(), r.files_on_landing())
r.done()

# V-S1-1: the same red run searched twice, as when the batch run queued behind the red
# one goes red on the same dropped commit. The second search pushes nothing.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-405)")
r.land({"breaks": "x\n"}, "Break it (INFRA-406)")
r.red_batch()
first = r.search()
after_first = r.landing()
second = r.search()
check("v-s1-1 searching a red batch whose bad commit is already off landing pushes nothing and says so",
      first.returncode == 0 and second.returncode == 0 and r.landing() == after_first and len(r.records()) == 1 and
      "already" in second.stdout, second.stdout + second.stderr)
r.done()

# ---- V-S3-1, V-S3-2: the batch run's own plan and move jobs ---------------------

for part, broken in (("move", job("move / move", "failure", [("Run actions/checkout@v5", "failure")], 11, 12)),
                     ("plan", job("plan / plan", "failure", [("Run actions/checkout@v5", "failure")], 0, 1))):
    r = Repo()
    r.land({"a": "1\n"}, "Add a (INFRA-411)")
    r.land({"b": "1\n"}, "Add b (INFRA-412)")
    if part == "move":
        jobs = [PLAN_OK, job("gate / Tests", "success", [("Run the tests", "success")], 2, 8),
                job("gate / gate", "success", [("Decide", "success")], 9, 10), broken]
    else:
        jobs = [broken, {"name": "gate / Tests", "conclusion": "skipped", "steps": []}, MOVE_SKIPPED]
    before = r.red_batch(jobs=jobs)
    out = r.search()
    check("s3 the {} job's runner could not fetch the code: the batch is run again".format(part),
          out.returncode == 0 and r.reruns() == [["run", "rerun", RED_RUN, "--failed"]], out.stdout + out.stderr)
    check("s3 the {} job's runner could not fetch the code: nothing is dropped and no search runs".format(part),
          r.landing() == before and r.dispatches() == [] and r.records() == [])
    r.done()

r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-413)")
before = r.red_batch(jobs=[PLAN_OK, job("gate / Tests", "success", [("Run the tests", "success")], 2, 8),
                           job("gate / gate", "success", [("Decide", "success")], 9, 10),
                           job("move / move", "failure", [("Set up job", "success"), ("Move main to the batch", "failure")],
                               11, 12)])
out = r.search()
check("s3 a batch whose Gate passed and whose move failed is not red: nothing is dropped, nothing rerun",
      out.returncode != 0 and r.landing() == before and r.records() == [] and r.reruns() == [] and
      "Gate passed" in out.stdout, out.stdout + out.stderr)
r.done()

# ---- arch-2: a Gate whose jobs run one after another ---------------------------

r = Repo(workflow=CHAIN_WORKFLOW)
first = r.land({"a": "1\n"}, "Add a (INFRA-421)")
bad = r.land({"breaks": "x\n"}, "Break it (INFRA-422)")
r.red_batch(jobs=[PLAN_OK, job("gate / Tests", "failure", [("Run the tests", "failure")], 2, 8),
                  job("gate / Lint", "success", [("Lint", "success")], 9, 10), MOVE_SKIPPED])
state = r.load()
state["chain"] = True
state["start_failures"] = {first: 1}
r.save(state)
out = r.search()
check("arch-2 the last job of a chained Gate failing at Set up job is a runner failure: run again, not blamed",
      out.returncode == 0 and len(r.reruns()) == 1 and r.trailers(r.landing()).get("Masthead-Dropped") == [bad],
      out.stdout + out.stderr)
r.done()

# ---- V-S4-J2: the issue a commit names last in its subject ---------------------

r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-430)")
r.land({"breaks": "x\n"}, "Undo part of INFRA-421 so the tests fail (INFRA-431)")
r.red_batch()
out = r.search()
check("s4 a subject that names another issue first: the record names the commit's own issue",
      out.returncode == 0 and r.trailers(r.landing()).get("Masthead-Issue") == ["INFRA-431"],
      out.stdout + out.stderr)
r.done()

# ---- V-S6-J1: the git the search needs ------------------------------------------

r = Repo(old_git=True)
r.land({"breaks": "x\n"}, "Break it (INFRA-440)")
before = r.red_batch()
out = r.search()
check("v-s6-j1 git 2.39 (no merge-tree --merge-base) stops the search and says it needs 2.40",
      out.returncode != 0 and "2.40" in out.stdout and r.landing() == before and r.load()["calls"] == [],
      out.stdout + out.stderr)
r.done()

r = Repo()
r.land({"breaks": "x\n"}, "Break it (INFRA-394)")
r.red_batch()
state = r.load()
state["runs"][RED_RUN]["headBranch"] = "main"
r.save(state)
out = r.search()
check("a run that is not on landing is not a batch: nothing is dropped",
      out.returncode != 0 and "not a batch run" in out.stdout and r.records() == [], out.stdout)
r.done()

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
