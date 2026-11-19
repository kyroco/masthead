#!/usr/bin/env python3
"""Linear issues INFRA-269 and INFRA-288: find the change that turned a batch red and say whose it is.

Each case builds a throwaway repository (a bare "GitHub" remote and a checkout),
lands commits on `landing`, records a red batch run, and runs the real
skills/work-on/bad-commit.py against it. gh is the stand-in hooks/tests/fake-gh.py,
whose Gate is red or green from the files in each commit, so the search runs
real git and starts and reads Gate runs as it would on GitHub.

INFRA-288 scenario 1: the search names the bad change, its issue and the failed
check, and pushes nothing to landing (no revert, nothing taken off).
INFRA-288 scenario 2: the change's worker is handed it back to fix on top of the
pile, with INFRA-263's rule when it fails together with earlier commits.
INFRA-288 scenario 3: the search never moves main, and its worker is told main
waits for a later go to run green (batch-run-test.py scenario 3 proves the move
refuses a red Gate).
INFRA-269 scenario 3: red only because a runner could not start or fetch the
code: the failed jobs run again and nothing is named.
INFRA-269 scenario 5: the search runs the stored Gate and never works it out;
with none stored it stops and says so.
INFRA-269 scenario 6: no commit fails alone but some fail together: the
latest-landed is named, with each commit it fails with and their issues.

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
if not _version or (int(_version.group(1)), int(_version.group(2))) < (2, 40):
    print("skipped: the search needs git 2.40 or newer (merge-tree --merge-base), and this git is older")
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
        # As setup leaves a real checkout: the state folder, where the search remembers what it
        # named, is kept out of git.
        with open(os.path.join(self.work, ".git", "info", "exclude"), "a") as handle:
            handle.write(".claude/state/\n")
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
                    # As on CI's ubuntu-latest: no global git config. Commits the fake gh makes in the bare
                    # remote take their identity from here, as batch-run-test.py's do (arch-4).
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "Worker", "GIT_AUTHOR_EMAIL": "w@example.com",
                    "GIT_COMMITTER_NAME": "Worker", "GIT_COMMITTER_EMAIL": "w@example.com"})
        return run([sys.executable, SEARCH, run_id], self.work, env)

    def landing(self):
        return git(self.remote, "rev-parse", "refs/heads/landing")

    def main(self):
        return git(self.remote, "rev-parse", "refs/heads/main")

    def refs(self):
        """Every branch on the "GitHub" remote and the commit it is on."""
        return git(self.remote, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")

    def files_on_landing(self):
        return set(git(self.remote, "ls-tree", "-r", "--name-only", "refs/heads/landing").split())

    def dispatches(self):
        return [c for c in self.load()["calls"] if c[:2] == ["workflow", "run"]]

    def reruns(self):
        return [c for c in self.load()["calls"] if c[:2] == ["run", "rerun"]]

    def done(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def record(text):
    """{field: [values]} from the record lines of the search's output."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(Masthead-[A-Za-z-]+): (.*)$", line)
        if m:
            out.setdefault(m.group(1), []).append(m.group(2))
    return out


def block(text):
    """The block the foreman posts on the issue and sends to the worker: its opening line and its text."""
    m = re.search(r"^(--- post on .* ---)\n(.*?)^--- end ---$", text, re.M | re.S)
    return (m.group(1), m.group(2)) if m else ("", "")


# ---- INFRA-288 scenarios 1, 2 and 3: one commit fails alone --------------------

r = Repo()
c1 = r.land({"a": "1\n"}, "Add a (INFRA-301)")
c2 = r.land({"breaks": "x\n"}, "Add the part that breaks the tests\n\nFixes INFRA-302")
c3 = r.land({"c": "3\n"}, "Add c (INFRA-303)")
c4 = r.land({"d": "4\n"}, "Add d (INFRA-304)")
before = r.red_batch()
refs = r.refs()
main_before = r.main()
out = r.search()
check("s1 the search ends well", out.returncode == 0, out.stdout + out.stderr)
check("s1 nothing is pushed: landing and every other branch are where they were", r.refs() == refs,
      (refs, r.refs()))
check("s1 landing still ends at the red batch, the bad change on it",
      r.landing() == before and "breaks" in r.files_on_landing())
check("s3 the search does not move main", r.main() == main_before)
check("s1 one bad of four commits costs log2(4) + 1 = 3 Gate runs", len(r.dispatches()) == 3, r.dispatches())
rec = record(out.stdout)
check("s1 the record names the bad change", rec.get("Masthead-Bad-Change") == [c2], rec)
check("s1 the record names its issue", rec.get("Masthead-Issue") == ["INFRA-302"], rec)
check("s1 the record names the check that failed, not the Gate's verdict job",
      rec.get("Masthead-Failed-Check") == ["Tests"], rec)
check("s1 the record names the batch and the red run",
      rec.get("Masthead-Batch") == [before] and rec.get("Masthead-Red-Run", [""])[0].startswith("https://"), rec)
check("s1 a commit that fails alone names no commit it fails with", "Masthead-Fails-With" not in rec, rec)
check("s1 the search says it pushed nothing", "Nothing was pushed to landing or main" in out.stdout, out.stdout)
check("s1 no word of a drop or a revert", not re.search(r"\b(drop|dropped|revert)", out.stdout, re.I), out.stdout)
opening, text = block(out.stdout)
check("s2 the block is for the bad change's issue, to post and to send to its worker",
      opening == "--- post on INFRA-302 as a comment, word for word, and send it whole to its worker ---", opening)
check("s2 the worker's message names the commit, its issue and the failed check",
      c2 in text and "for INFRA-302" in text and "Failed check: Tests." in text, text)
check("s2 the worker fixes it on top of the pile, from the newest landing",
      "Fix it on top" in text and "your commit stays on the pile" in text and "origin/landing" in text, text)
check("s3 the worker is told main does not move until a later go runs green",
      "main does not move until a later go runs green" in text, text)
check("s2 the record goes with the message, so the issue's comment holds it", "Masthead-Bad-Change: " + c2 in text, text)
commands = re.findall(r"`([^`]*)`", text)
check("s2 the message gives no push command", all("push" not in c for c in commands), commands)
r.done()

# A batch of one commit: the batch run itself showed it red, so no Gate run is needed.
r = Repo()
only = r.land({"breaks": "x\n"}, "Break it (INFRA-310)")
before = r.red_batch()
out = r.search()
check("s1 one commit in the batch is named with no extra Gate run, and landing is left alone",
      out.returncode == 0 and r.dispatches() == [] and record(out.stdout).get("Masthead-Bad-Change") == [only] and
      r.landing() == before, out.stdout + out.stderr)
r.done()

# ---- INFRA-269 scenario 6, INFRA-288 scenario 2: commits that fail only together --

r = Repo()
p1 = r.land({"half-a": "a\n"}, "Add half a (INFRA-321)")
r.land({"e": "e\n"}, "Add e (INFRA-322)")
p3 = r.land({"half-b": "b\n"}, "Add half b (INFRA-323)")
r.land({"f": "f\n"}, "Add f (INFRA-324)")
r.red_batch()
refs = r.refs()
out = r.search()
check("s6 the search ends well", out.returncode == 0, out.stdout + out.stderr)
rec = record(out.stdout)
check("s6 the latest-landed of the commits that fail together is named", rec.get("Masthead-Bad-Change") == [p3], rec)
check("s6 the record names its issue", rec.get("Masthead-Issue") == ["INFRA-323"], rec)
check("s6 the record names each commit it fails with, and their issues",
      rec.get("Masthead-Fails-With") == ["{} INFRA-321".format(p1)], rec)
check("s6 the record names the failed check", rec.get("Masthead-Failed-Check") == ["Tests"], rec)
check("s1 nothing is pushed: both halves stay on landing",
      r.refs() == refs and {"half-a", "half-b", "e", "f"} <= r.files_on_landing())
opening, text = block(out.stdout)
check("s2 the later commit's issue gets the block, not the earlier one's", "post on INFRA-323 " in opening, opening)
check("s2 the worker is told it fails only with the earlier commit and its issue",
      "fails only together with {} (INFRA-321)".format(p1[:9]) in text, text)
check("s2 INFRA-263's rule: the worker owns the fix end to end, whichever commit the fault sits in",
      "It is your job to figure out what needs to be fixed and fix it, end to end" in text
      and "not someone else's commit to hand on" in text, text)
check("s2 INFRA-263's rule: the worker reads the earlier issue and every comment on it first",
      "Before you change anything, read INFRA-321 and every comment on it" in text, text)
check("s2 INFRA-263's rule: once the fix lands, the worker comments on both issues",
      "Once your fix lands, add a comment to INFRA-323 and to INFRA-321 saying what you changed and why" in text, text)
check("s2 and it fixes on top of the pile", "Fix it on top" in text, text)
r.done()

r = Repo()
q1 = r.land({"trio-1": "1\n"}, "Add trio 1 (INFRA-331)")
q2 = r.land({"trio-2": "2\n"}, "Add trio 2 (INFRA-332)")
r.land({"g": "g\n"}, "Add g (INFRA-333)")
q4 = r.land({"trio-3": "3\n"}, "Add trio 3 (INFRA-334)")
r.red_batch()
out = r.search()
rec = record(out.stdout)
check("s6 three commits that fail only together: the last is named, both others named with it",
      out.returncode == 0 and rec.get("Masthead-Bad-Change") == [q4] and
      rec.get("Masthead-Fails-With") == ["{} INFRA-331".format(q1), "{} INFRA-332".format(q2)],
      out.stdout + out.stderr + str(rec))
check("s2 with two earlier issues, the worker reads both and comments on all three",
      "read INFRA-331 and INFRA-332 and every comment on them" in out.stdout and
      "add a comment to INFRA-334 and to INFRA-331 and to INFRA-332" in out.stdout, out.stdout)
r.done()

# A commit that only applies on top of an earlier one fails with it.
r = Repo()
d1 = r.land({"lib": "one\n"}, "Add lib (INFRA-341)")
r.land({"lib": "one\ntwo\n", "breaks": "x\n"}, "Change lib and break it (INFRA-342)")
r.red_batch()
out = r.search()
rec = record(out.stdout)
check("s6 a commit that cannot apply alone is named with the commit it needs",
      out.returncode == 0 and rec.get("Masthead-Issue") == ["INFRA-342"] and
      rec.get("Masthead-Fails-With") == ["{} INFRA-341".format(d1)],
      out.stdout + out.stderr + str(rec))
check("s6 with no search run red, the batch is run once more to confirm before any blame (2 runs here)",
      len(r.dispatches()) == 2 and rec.get("Masthead-Red-Run", [""])[0].endswith("/5001"), (r.dispatches(), rec))
r.done()

# ---- INFRA-269 scenario 3: red only because a runner could not start --------------

for step in ("Set up job", "Run actions/checkout@v5"):
    r = Repo()
    r.land({"breaks": "x\n"}, "Break it (INFRA-351)")
    before = r.red_batch(tests_step=step)
    out = r.search()
    check("s3 '{}' failing: the failed jobs run again".format(step),
          out.returncode == 0 and r.reruns() == [["run", "rerun", RED_RUN, "--failed"]], out.stdout + out.stderr)
    check("s3 '{}' failing: no change is named and no search runs".format(step),
          r.landing() == before and r.dispatches() == [] and record(out.stdout) == {})
    r.done()

# A runner failure next to a real failed check is a real red: it is searched, not rerun.
r = Repo()
r.land({"breaks": "x\n"}, "Break it (INFRA-352)")
r.red_batch(extra_jobs=[job("gate / Lint", "failure", [("Set up job", "failure")], 2, 3)])
out = r.search()
check("s3 a runner failure beside a real failure does not hide it: the change is named",
      out.returncode == 0 and r.reruns() == [] and record(out.stdout).get("Masthead-Issue") == ["INFRA-352"],
      out.stdout + out.stderr)
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
      out.returncode == 0 and len(r.reruns()) == 1 and record(out.stdout).get("Masthead-Bad-Change") == [bad],
      out.stdout + out.stderr)
r.done()

# ---- INFRA-269 scenario 5: the stored Gate, and none stored ----------------------

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
check("s5 no throwaway search branch is left on GitHub",
      git(r.remote, "for-each-ref", "--format=%(refname)", "refs/heads/masthead-search") == "")
r.done()

r = Repo(gate=False)
r.land({"breaks": "x\n"}, "Break it (INFRA-374)")
before = r.red_batch()
out = r.search()
check("s5 with no Gate stored the search stops and says so",
      out.returncode != 0 and "No Gate is stored in .claude/gate.json" in out.stdout, out.stdout + out.stderr)
check("s5 with no Gate stored nothing is asked of GitHub and nothing is named",
      r.load()["calls"] == [] and r.landing() == before and record(out.stdout) == {})
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
check("a red that does not happen again in any search run names nothing and says so",
      out.returncode != 0 and "did not happen again" in out.stdout and r.landing() == before and
      record(out.stdout) == {}, out.stdout + out.stderr)
r.done()

# A worker landing while the search runs: the search adds nothing on top of it.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-383)")
bad = r.land({"breaks": "x\n"}, "Break it (INFRA-384)")
before = r.red_batch()
state = r.load()
state["land_during"] = True
r.save(state)
out = r.search()
landed = git(r.remote, "log", "--format=%s", "{}..{}".format(before, r.landing())).splitlines()
check("s1 a worker landing while the search runs: only their commits are new on landing, the search added none",
      out.returncode == 0 and landed and all("meanwhile" in s for s in landed) and
      record(out.stdout).get("Masthead-Bad-Change") == [bad], (out.stdout + out.stderr, landed))
r.done()

# The same red run searched twice, as when the foreman runs it again.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-405)")
bad = r.land({"breaks": "x\n"}, "Break it (INFRA-406)")
before = r.red_batch()
first = r.search()
second = r.search()
check("s1 searching the same red batch twice names it once, says so the second time, and pushes nothing",
      first.returncode == 0 and second.returncode == 0 and r.landing() == before and
      record(first.stdout).get("Masthead-Bad-Change") == [bad] and "already named" in second.stdout and
      block(second.stdout) == ("", ""), second.stdout + second.stderr)
r.done()

# A commit whose message names no issue: the record goes to the person, not to a worker.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-407)")
bad = r.land({"breaks": "x\n"}, "Break it with no issue named")
r.red_batch()
out = r.search()
check("a bad change that names no issue goes to the person with its record, and no worker block is printed",
      out.returncode == 0 and "names no issue: tell the person" in out.stdout and block(out.stdout) == ("", "") and
      record(out.stdout).get("Masthead-Bad-Change") == [bad], out.stdout + out.stderr)
r.done()

# ---- V-S2-1: a named change fixed on top, then a new break -----------------------
# Main has not moved, so the next red batch still holds the first bad change with its
# fix on top. The search names the new break, not the change already fixed.

# The commits are bad, a, fix, new: halving tests bad + a first, which is red, so a
# search that trusts red prefixes to only grow names the change already fixed.
r = Repo()
first_bad = r.land({"breaks": "x\n"}, "Break it (INFRA-501)")
r.land({"a": "1\n"}, "Add a (INFRA-500)")
r.red_batch()
out = r.search()
check("v-s2-1 setup: the first search names the first bad change",
      record(out.stdout).get("Masthead-Bad-Change") == [first_bad], out.stdout + out.stderr)
os.remove(os.path.join(r.work, "breaks"))
fix = r.land({"b": "fixed\n"}, "Fix the break on top (INFRA-501)")
new_bad = r.land({"half-a": "a\n", "half-b": "b\n"}, "Break it another way (INFRA-503)")
before = r.red_batch()
state = r.load()
state["calls"] = []
r.save(state)
out = r.search()
rec = record(out.stdout)
check("v-s2-1 the next red batch names the new break, not the change already fixed on top",
      out.returncode == 0 and rec.get("Masthead-Bad-Change") == [new_bad] and rec.get("Masthead-Issue") == ["INFRA-503"],
      out.stdout + out.stderr)
check("v-s2-1 the block goes to the new break's issue only",
      "post on INFRA-503 " in block(out.stdout)[0] and "INFRA-501 as a comment" not in out.stdout, out.stdout)
check("v-s2-1 the new break fails alone after the fix, so it names no commit it fails with",
      "Masthead-Fails-With" not in rec, rec)
check("v-s2-1 still nothing is pushed", r.landing() == before)
r.done()

# A fix on top that does not fix it: the change is named again, and its worker is told so.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-510)")
first_bad = r.land({"breaks": "x\n"}, "Break it (INFRA-511)")
r.red_batch()
r.search()
tried = r.land({"b": "not fixed\n"}, "Try to fix the break (INFRA-511)")
r.land({"c": "3\n"}, "Add c (INFRA-512)")
r.red_batch()
out = r.search()
rec = record(out.stdout)
check("v-s2-1 a fix on top that is still red: the same change is named again",
      out.returncode == 0 and rec.get("Masthead-Bad-Change") == [first_bad], out.stdout + out.stderr)
check("v-s2-1 and its worker is told the fix it landed is still red",
      "Your fix on top, {}".format(tried[:9]) in block(out.stdout)[1] and "still red" in block(out.stdout)[1],
      out.stdout)
r.done()

# ---- V-S2-J1: a named change whose fix has not landed is not searched again ------
# The batch run queued behind the red one holds the same change and goes red too.

r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-520)")
bad = r.land({"breaks": "x\n"}, "Break it (INFRA-521)")
r.red_batch()
first = r.search()
r.land({"d": "4\n"}, "Add d (INFRA-522)")
before = r.red_batch()
state = r.load()
state["calls"] = []
r.save(state)
out = r.search()
check("v-s2-j1 a red batch holding a named change with no fix on top starts no Gate run",
      out.returncode == 0 and r.dispatches() == [], (r.dispatches(), out.stdout + out.stderr))
check("v-s2-j1 it says the change is already named and handed back, and prints no block to send again",
      "already named" in out.stdout and bad[:9] in out.stdout and "INFRA-521" in out.stdout and
      block(out.stdout) == ("", ""), out.stdout)
check("v-s2-j1 still nothing is pushed", r.landing() == before)
r.done()

# ---- Re-verify round 1 ---------------------------------------------------------

# r1-c3-false, state A: one change landed as two commits on one issue. Its second
# commit is part of the change, never a fix on top.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-600)")
x1 = r.land({"breaks": "x\n"}, "Add the part that breaks (INFRA-601)")
r.land({"doc": "d\n"}, "Document the part (INFRA-601)")
r.red_batch()
out = r.search()
check("r1-c3 a change's own second commit is not read as a fix on top: no 'Your fix on top' line",
      record(out.stdout).get("Masthead-Bad-Change") == [x1] and "Your fix on top" not in out.stdout,
      out.stdout + out.stderr)
r.land({"y": "1\n"}, "Add y (INFRA-602)")
r.red_batch()
state = r.load()
state["calls"] = []
r.save(state)
out = r.search()
check("r1-c3 the next red batch, with no fix landed since, starts no Gate run and sends nothing again",
      r.dispatches() == [] and "already named" in out.stdout and block(out.stdout) == ("", ""),
      (r.dispatches(), out.stdout + out.stderr))
r.done()

# r1-c2-false: a new break lands while the named change waits for its fix, then the fix lands.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-610)")
x = r.land({"breaks": "x\n"}, "Break it (INFRA-611)")
r.red_batch()
r.search()
m = r.land({"half-a": "a\n", "half-b": "b\n"}, "Break it another way (INFRA-613)")
r.red_batch()
out = r.search()
check("r1-c2 setup: while the fix has not landed, the batch is held as already named",
      "already named" in out.stdout, out.stdout + out.stderr)
os.remove(os.path.join(r.work, "breaks"))
r.land({"b": "fixed\n"}, "Fix the break on top (INFRA-611)")
r.red_batch()
out = r.search()
rec = record(out.stdout)
check("r1-c2 a fix that works is not blamed for a break landed before it: the new break is named",
      out.returncode == 0 and rec.get("Masthead-Bad-Change") == [m] and rec.get("Masthead-Issue") == ["INFRA-613"],
      out.stdout + out.stderr)
check("r1-c2 no one is told a working fix is still red", "still red" not in out.stdout, out.stdout)
r.done()

# r1-c3-false, state B: a fix already found red is not searched and handed back again.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-620)")
x = r.land({"breaks": "x\n"}, "Break it (INFRA-621)")
r.red_batch()
r.search()
tried = r.land({"b": "not fixed\n"}, "Try to fix the break (INFRA-621)")
r.red_batch()
out = r.search()
check("r1-c3-b setup: the fix that is still red is named as tried",
      "Your fix on top, {}".format(tried[:9]) in out.stdout, out.stdout + out.stderr)
r.land({"z": "1\n"}, "Add z (INFRA-622)")
r.red_batch()
state = r.load()
state["calls"] = []
r.save(state)
out = r.search()
check("r1-c3-b with no newer fix since, the next red batch starts no Gate run and sends nothing again",
      r.dispatches() == [] and "already named" in out.stdout and block(out.stdout) == ("", ""),
      (r.dispatches(), out.stdout + out.stderr))
r.done()

# r1-judge-1: a bad change whose commit names no issue goes to the person and is not held
# forever: once fixed on top, a later break is still found.
r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-630)")
loose = r.land({"breaks": "x\n"}, "Break it with no issue named")
r.red_batch()
out = r.search()
check("r1-judge-1 setup: the change with no issue goes to the person",
      "names no issue: tell the person" in out.stdout, out.stdout + out.stderr)
os.remove(os.path.join(r.work, "breaks"))
r.land({"b": "fixed\n"}, "Fix the break by hand")
later = r.land({"half-a": "a\n", "half-b": "b\n"}, "Break it another way (INFRA-631)")
r.red_batch()
out = r.search()
# With no issue, no later commit can be told apart as its fix, so halving may still land on it;
# it goes to the person again, never held as waiting with nothing named.
check("r1-judge-1 a change with no issue is not held as waiting: the later batch is searched and a change named",
      out.returncode == 0 and "already named" not in out.stdout and r.dispatches() and
      record(out.stdout).get("Masthead-Bad-Change") in ([later], [loose]), out.stdout + out.stderr)
check("r1-judge-1 nothing with no issue is written to the search's memory",
      loose not in open(os.path.join(r.work, ".claude", "state", "named-changes.tsv")).read()
      if os.path.exists(os.path.join(r.work, ".claude", "state", "named-changes.tsv")) else True)
r.done()

# ---- Re-verify round 2, scenario-2-then: a change that failed together, whose fix is still red ----
# It is handed back with the commit it fails with and INFRA-263's rule, never as failing alone.
r = Repo()
p = r.land({"half-a": "a\n"}, "Add the first half (INFRA-700)")
r.land({"e": "e\n"}, "Add e (INFRA-702)")
c = r.land({"half-b": "b\n"}, "Add the second half (INFRA-701)")
r.red_batch()
out = r.search()
check("r2-s2 setup: the first search names the later half with the earlier one it fails with",
      record(out.stdout).get("Masthead-Fails-With") == ["{} INFRA-700".format(p)], out.stdout + out.stderr)
tried = r.land({"b-note": "not fixed\n"}, "Try to fix the halves (INFRA-701)")
r.red_batch()
out = r.search()
rec = record(out.stdout)
text = block(out.stdout)[1]
check("r2-s2 a still-red fix names the same change again, still with the commit it fails with",
      rec.get("Masthead-Bad-Change") == [c] and rec.get("Masthead-Fails-With") == ["{} INFRA-700".format(p)],
      out.stdout + out.stderr)
check("r2-s2 its worker is told the fix is still red, and never that it fails on its own",
      "Your fix on top, {}".format(tried[:9]) in text and "fails that check on its own" not in text, text)
check("r2-s2 INFRA-263's rule is kept: read the earlier issue and comment on both",
      "Before you change anything, read INFRA-700 and every comment on it" in text and
      "add a comment to INFRA-701 and to INFRA-700" in text, text)
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
    check("s3 the {} job's runner could not fetch the code: nothing is named and no search runs".format(part),
          r.landing() == before and r.dispatches() == [] and record(out.stdout) == {})
    r.done()

r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-413)")
before = r.red_batch(jobs=[PLAN_OK, job("gate / Tests", "success", [("Run the tests", "success")], 2, 8),
                           job("gate / gate", "success", [("Decide", "success")], 9, 10),
                           job("move / move", "failure", [("Set up job", "success"), ("Move main to the batch", "failure")],
                               11, 12)])
out = r.search()
check("s3 a batch whose Gate passed and whose move failed is not red: nothing is named, nothing rerun",
      out.returncode != 0 and r.landing() == before and record(out.stdout) == {} and r.reruns() == [] and
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
      out.returncode == 0 and len(r.reruns()) == 1 and record(out.stdout).get("Masthead-Bad-Change") == [bad],
      out.stdout + out.stderr)
r.done()

# ---- V-S4-J2: the issue a commit names last in its subject ---------------------

r = Repo()
r.land({"a": "1\n"}, "Add a (INFRA-430)")
r.land({"breaks": "x\n"}, "Undo part of INFRA-421 so the tests fail (INFRA-431)")
r.red_batch()
out = r.search()
check("s1 a subject that names another issue first: the record names the commit's own issue",
      out.returncode == 0 and record(out.stdout).get("Masthead-Issue") == ["INFRA-431"],
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
check("a run that is not on landing is not a batch: nothing is named",
      out.returncode != 0 and "not a batch run" in out.stdout and record(out.stdout) == {}, out.stdout)
r.done()

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
