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


def git(cwd, *args):
    r = run(["git", *args], cwd)
    if r.returncode != 0:
        raise SystemExit("git {} failed in {}: {}".format(" ".join(args), cwd, r.stderr))
    return r.stdout.strip()


class Repo:
    """A bare remote, a checkout of it, and a fake gh whose Gate reads the remote."""

    def __init__(self, gate=True, decoy=False, starts=("workflow_call", "workflow_dispatch")):
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
        self.write(self.workflow, "name: Gate\non: [workflow_call, workflow_dispatch]\n")
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

    def red_batch(self, tests_step="Run the tests", sha=None, extra_jobs=()):
        """Record the batch run on landing's tip as red, the way the starter's run shows it."""
        sha = sha or git(self.work, "rev-parse", "origin/landing")
        def job(name, conclusion, steps, start, end):
            return {"name": name, "conclusion": conclusion, "steps": steps,
                    "startedAt": "2026-11-19T14:{:02d}:00Z".format(start),
                    "completedAt": "2026-11-19T14:{:02d}:00Z".format(end)}
        jobs = [job("plan / plan", "success", [{"name": "Read the stored Gate", "conclusion": "success"}], 0, 1),
                job("gate / Tests", "failure", [{"name": "Set up job", "conclusion": "success" if tests_step != "Set up job" else "failure"},
                                               {"name": tests_step, "conclusion": "failure"}][:1 if tests_step == "Set up job" else 2], 2, 8),
                job("gate / Static", "success", [{"name": "Static checks", "conclusion": "success"}], 2, 6)]
        jobs += list(extra_jobs)
        jobs += [job("gate / gate", "failure", [{"name": "Decide", "conclusion": "failure"}], 9, 10),
                 {"name": "move / move", "conclusion": "skipped", "steps": []}]
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
                    "MASTHEAD_SEARCH_FIND_TRIES": "2", "CLAUDE_PROJECT_DIR": self.work})
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
start_fail = {"name": "gate / Lint", "conclusion": "failure", "steps": [{"name": "Set up job", "conclusion": "failure"}],
              "startedAt": "2026-11-19T14:02:00Z", "completedAt": "2026-11-19T14:03:00Z"}
r.red_batch(extra_jobs=[start_fail])
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

r = Repo()
r.land({"lib": "one\n"}, "Add lib (INFRA-391)")
r.land({"lib": "one\nbreaks\n", "breaks": "x\n"}, "Break lib (INFRA-392)")
before = r.red_batch()
r.land({"lib": "one\nbreaks\nthree\n"}, "Build on lib (INFRA-393)")
after = r.landing()
out = r.search()
check("a commit later work builds on is not dropped by force: nothing changes and it says so",
      out.returncode != 0 and "cannot be taken off landing cleanly" in out.stdout and r.landing() == after,
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
