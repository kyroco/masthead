#!/usr/bin/env python3
"""A stand-in for the gh command, for bad-commit-test.py (INFRA-269).

It answers only the calls skills/work-on/bad-commit.py makes, keeps its runs in
the JSON file FAKE_GH_STATE, and logs every call there. A "Gate run" it starts
is red or green from the files in the commit's tree in the bare repository
FAKE_GH_REMOTE, the way a real Gate is red or green from the code:

- a file named `breaks`: the Tests job fails;
- files `half-a` and `half-b` together, or `trio-1`, `trio-2` and `trio-3`
  together: the Tests job fails (commits that fail only together).

A red run also fails a verdict job, `gate`, that starts after every other job
ended, as Kyroco's Gate does. A commit listed in the state's `start_failures`
has its Tests job fail at "Set up job" that many times first, as when a runner
could not start. `chain`: the Gate is Tests then Lint, one after the other on
one runner, with no verdict job, and a start failure hits Lint. `land_during`:
each started run first lands one more commit on landing, as a worker would
while the search runs.
"""
import json
import os
import subprocess
import sys

STATE = os.environ["FAKE_GH_STATE"]
REMOTE = os.environ["FAKE_GH_REMOTE"]


def load():
    with open(STATE) as handle:
        return json.load(handle)


def save(state):
    with open(STATE, "w") as handle:
        json.dump(state, handle, indent=1)


def git(*args):
    return subprocess.run(["git", "-C", REMOTE, *args], capture_output=True, text=True, check=True).stdout


def git_in(text, *args):
    return subprocess.run(["git", "-C", REMOTE, *args], input=text, capture_output=True, text=True,
                          check=True).stdout


def red(sha):
    files = set(git("ls-tree", "-r", "--name-only", sha).split())
    return "breaks" in files or {"half-a", "half-b"} <= files or {"trio-1", "trio-2", "trio-3"} <= files


def step(name, conclusion):
    return {"name": name, "conclusion": conclusion}


def job(name, conclusion, steps, start, end):
    return {"name": name, "conclusion": conclusion, "steps": steps,
            "startedAt": "2026-11-19T15:{:02d}:00Z".format(start),
            "completedAt": "2026-11-19T15:{:02d}:00Z".format(end)}


def jobs_for(sha, state, prefix=""):
    starts = state.setdefault("start_failures", {})
    if state.get("chain"):
        # Tests, then Lint on the same runner, and no verdict job; a runner failure hits Lint, the last job.
        bad = red(sha)
        tests = job(prefix + "Tests", "failure" if bad else "success",
                    [step("Set up job", "success"), step("Run the tests", "failure" if bad else "success")], 0, 5)
        if starts.get(sha, 0) > 0:
            starts[sha] -= 1
            lint = job(prefix + "Lint", "failure", [step("Set up job", "failure")], 6, 7)
        else:
            lint = job(prefix + "Lint", "success", [step("Set up job", "success"), step("Lint", "success")], 6, 8)
        return [tests, lint]
    if starts.get(sha, 0) > 0:
        starts[sha] -= 1
        tests = job(prefix + "Tests", "failure", [step("Set up job", "failure")], 0, 1)
        verdict = "failure"
    elif red(sha):
        tests = job(prefix + "Tests", "failure", [step("Set up job", "success"), step("Run the tests", "failure")], 0, 5)
        verdict = "failure"
    else:
        tests = job(prefix + "Tests", "success", [step("Set up job", "success"), step("Run the tests", "success")], 0, 5)
        verdict = "success"
    static = job(prefix + "Static", "success", [step("Set up job", "success"), step("Static checks", "success")], 0, 4)
    gate = job(prefix + "gate", verdict, [step("Decide", verdict)], 6, 7)
    return [tests, static, gate]


def main(argv):
    state = load()
    state.setdefault("calls", []).append(argv)
    runs = state.setdefault("runs", {})
    out = None
    if argv[:2] == ["run", "view"]:
        out = runs.get(argv[2])
        if out is None:
            save(state)
            print("no run " + argv[2], file=sys.stderr)
            return 1
    elif argv[:2] == ["workflow", "run"]:
        workflow, branch = argv[2], argv[argv.index("--ref") + 1]
        if state.get("land_during"):
            n = state["landed_during"] = state.get("landed_during", 0) + 1
            land_one_more("during-{}".format(n))
        sha = git("rev-parse", "refs/heads/" + branch).strip()
        run_id = str(state.get("next", 5000))
        state["next"] = int(run_id) + 1
        jobs = jobs_for(sha, state)
        runs[run_id] = {"databaseId": int(run_id), "status": "completed", "headSha": sha, "headBranch": branch,
                        "url": "https://github.com/example/repo/actions/runs/" + run_id, "attempt": 1,
                        "workflow": workflow, "event": "workflow_dispatch", "jobs": jobs,
                        "conclusion": conclusion(jobs)}
    elif argv[:2] == ["run", "list"]:
        workflow, branch = argv[argv.index("--workflow") + 1], argv[argv.index("--branch") + 1]
        out = [r for r in runs.values() if r.get("workflow") == workflow and r.get("headBranch") == branch]
    elif argv[:2] == ["run", "rerun"]:
        run = runs[argv[2]]
        run["attempt"] = run.get("attempt", 1) + 1
        prefix = "gate / " if run.get("headBranch") == "landing" else ""
        run["jobs"] = jobs_for(run["headSha"], state, prefix)
        run["conclusion"] = conclusion(run["jobs"])
    else:
        save(state)
        print("fake gh: unknown call " + " ".join(argv), file=sys.stderr)
        return 1
    save(state)
    if out is not None:
        print(json.dumps(out))
    return 0


def conclusion(jobs):
    return "failure" if any(j["conclusion"] == "failure" for j in jobs) else "success"


def land_one_more(name):
    """Put one more commit, adding the file `name`, on the remote's landing."""
    tip = git("rev-parse", "refs/heads/landing").strip()
    blob = git_in(name + "\n", "hash-object", "-w", "--stdin").strip()
    tree = git_in(git("ls-tree", tip) + "100644 blob {}\t{}\n".format(blob, name), "mktree").strip()
    commit = git("commit-tree", tree, "-p", tip, "-m", "Land more work meanwhile (INFRA-399)").strip()
    git("update-ref", "refs/heads/landing", commit, tip)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
