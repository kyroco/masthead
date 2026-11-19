#!/usr/bin/env python3
"""Linear issue INFRA-268: setup works out how a repository's Gate is run, and stores it after one yes.

Scenario 1: `gate.py look` works out the Gate (a workflow named Gate, else what
runs on a pull request or the merge queue, that can be started on its own) and
writes nothing, so setup can ask for one yes.
Scenario 2: after `gate.py store`, `look` answers "stored" and does not work
the Gate out again, even when the workflows would now point elsewhere.
Scenarios 3 and 4: `project_fact.py --gate`, the reader the search for a bad
commit and the batch run call, prints the stored answer, from any folder of the
checkout, and never works it out; the stored file is plain JSON a workflow can read.
Scenario 5: with no Gate that can be started, or no yes, nothing is written and
setup has its one line saying the repository keeps shipping the old way.

Run from anywhere: python3 hooks/tests/gate-fact-test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
FACT = os.path.join(PLUGIN, "hooks", "project_fact.py")
GATE = os.path.join(PLUGIN, "skills", "setup", "gate.py")
sys.path.insert(0, os.path.join(PLUGIN, "skills", "setup"))
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))
import gate as gate_py  # noqa: E402

passed = 0
failed = 0

OLD_WAY = "Masthead could not work out how this repository's Gate is run, so it keeps shipping the way it does today."

GATE_YML = """# The checks.
name: Gate

on:
  pull_request:
  merge_group:
    types: [checks_requested]
  workflow_dispatch:
  workflow_call:
    secrets:
      TOKEN:
        required: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo on
"""

PR_ONLY = """name: tests
on:
  push:
  pull_request:
jobs: {}
"""


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


def repo():
    root = os.path.realpath(tempfile.mkdtemp(prefix="gate-fact-"))
    os.mkdir(os.path.join(root, ".git"))
    return root


def write(root, rel, text=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    return path


def snapshot(root):
    """Every file under root with its contents, to show nothing changed."""
    files = {}
    for folder, _, leaves in os.walk(root):
        for leaf in leaves:
            path = os.path.join(folder, leaf)
            with open(path, "rb") as handle:
                files[os.path.relpath(path, root)] = handle.read()
    return files


def env_for(project=None):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project:
        env["CLAUDE_PROJECT_DIR"] = project
    return env


def run_gate(root, *args):
    r = subprocess.run([sys.executable, GATE] + list(args) + ["--root", root],
                       capture_output=True, text=True, env=env_for())
    return r.returncode, r.stdout, r.stderr


def look(root):
    code, out, err = run_gate(root, "look")
    return json.loads(out) if code == 0 else {"error": err}


def read_fact(cwd, project=None):
    r = subprocess.run([sys.executable, FACT, "--gate"], capture_output=True, text=True,
                       cwd=cwd, env=env_for(project))
    return r.returncode, r.stdout.strip()


# Scenario 1: a workflow named Gate that can be started is found, and nothing is written.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
write(root, ".github/workflows/tests.yml", PR_ONLY)
before = snapshot(root)
got = look(root)
expect("s1 status", got.get("status"), "found")
expect("s1 workflow", got.get("workflow"), ".github/workflows/gate.yml")
expect("s1 starts", got.get("starts"), ["workflow_call", "workflow_dispatch"])
expect("s1 look writes nothing", snapshot(root), before)

# Scenario 1: with no workflow named Gate, the one on pull requests that can be started is the Gate.
root = repo()
write(root, ".github/workflows/ci.yaml", "name: CI\non: [pull_request, workflow_dispatch]\njobs: {}\n")
write(root, ".github/workflows/nightly.yml", "name: Nightly\non:\n  schedule:\n    - cron: '0 5 * * *'\n  workflow_dispatch:\njobs: {}\n")
got = look(root)
expect("s1 by pull request", (got.get("status"), got.get("workflow")), ("found", ".github/workflows/ci.yaml"))

# Scenario 1: two candidates, so setup asks which; the choice is the one yes.
root = repo()
write(root, ".github/workflows/a.yml", "name: A\non:\n  pull_request:\n  workflow_call:\njobs: {}\n")
write(root, ".github/workflows/b.yml", "name: B\n'on':\n  - merge_group\n  - workflow_dispatch\njobs: {}\n")
got = look(root)
expect("s1 choose status", got.get("status"), "choose")
expect("s1 choose list", [c["workflow"] for c in got.get("choices", [])],
       [".github/workflows/a.yml", ".github/workflows/b.yml"])

# Scenario 2: the yes stores it; the next look reads it and does not work it out again.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
code, out, err = run_gate(root, "store", ".github/workflows/gate.yml")
expect("s2 store exit", code, 0)
with open(os.path.join(root, ".claude", "gate.json")) as handle:
    stored = json.load(handle)
expect("s2 stored shape", stored, {"workflow": ".github/workflows/gate.yml", "starts": ["workflow_call", "workflow_dispatch"]})
# A new workflow that working it out would now pick instead: a stored answer still wins.
write(root, ".github/workflows/Gate.yaml", "name: Gate\non: [workflow_dispatch]\njobs: {}\n")
got = look(root)
expect("s2 stored wins", (got.get("status"), got.get("workflow")), ("stored", ".github/workflows/gate.yml"))

# Scenarios 3 and 4: the reader the search and the batch run call prints the stored answer.
sub = os.path.join(root, "lib", "deep")
os.makedirs(sub)
code, out = read_fact(sub)
expect("s3 reader exit", code, 0)
expect("s3 reader answer", json.loads(out) if out else None,
       {"workflow": ".github/workflows/gate.yml", "starts": ["workflow_call", "workflow_dispatch"]})
code, out = read_fact(root, project=root)
expect("s4 reader under a hook", (code, json.loads(out)["workflow"] if out else None), (0, ".github/workflows/gate.yml"))
# The reader never works it out: a repository with a Gate workflow but nothing stored gets nothing.
fresh = repo()
write(fresh, ".github/workflows/gate.yml", GATE_YML)
expect("s4 reader does not work it out", read_fact(fresh), (1, ""))
# Another repository's checkout is not read for a session in this one.
expect("s3 reader refuses another repo", subprocess.run(
    [sys.executable, FACT, "--root", root, "--gate"], capture_output=True, text=True,
    env=env_for(fresh)).returncode, 1)

# The reader refuses a stored answer that does not name a startable workflow file.
for label, body in (
        ("outside workflows", {"workflow": "../evil.yml", "starts": ["workflow_dispatch"]}),
        ("missing file", {"workflow": ".github/workflows/gone.yml", "starts": ["workflow_dispatch"]}),
        ("no way to start", {"workflow": ".github/workflows/gate.yml", "starts": ["push"]}),
        ("not an object", ["x"])):
    bad = repo()
    write(bad, ".github/workflows/gate.yml", GATE_YML)
    write(bad, ".claude/gate.json", json.dumps(body))
    expect("reader refuses " + label, read_fact(bad), (1, ""))

# Scenario 5: no Gate that can be started: nothing written, and the one line to say.
root = repo()
write(root, ".github/workflows/tests.yml", PR_ONLY)
before = snapshot(root)
got = look(root)
expect("s5 none status", got.get("status"), "none")
expect("s5 none line", got.get("say"), OLD_WAY)
expect("s5 none writes nothing", snapshot(root), before)
code, out, err = run_gate(root, "store", ".github/workflows/tests.yml")
expect("s5 store refuses unstartable", code, 1)
expect("s5 store says old way", OLD_WAY in err, True)
expect("s5 refused store writes nothing", snapshot(root), before)
expect("s5 reader has nothing", read_fact(root), (1, ""))

# Scenario 5: no workflows at all.
root = repo()
got = look(root)
expect("s5 no workflows", (got.get("status"), got.get("say")), ("none", OLD_WAY))

# Scenario 5: the person says no, so store never runs: the reader still has nothing.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
look(root)
expect("s5 no yes, nothing stored", os.path.exists(os.path.join(root, ".claude", "gate.json")), False)

# V-S1-J1: the pull-request workflow cannot be started alone but calls a reusable one
# that can: the reusable one is the Gate.
root = repo()
write(root, ".github/workflows/ci.yml",
      "name: CI\non:\n  pull_request:\njobs:\n  checks:\n    uses: ./.github/workflows/checks.yml\n    secrets: inherit\n")
write(root, ".github/workflows/checks.yml", "name: Checks\non:\n  workflow_call:\njobs: {}\n")
got = look(root)
expect("s1 reusable workflow", (got.get("status"), got.get("workflow"), got.get("starts")),
       ("found", ".github/workflows/checks.yml", ["workflow_call"]))

# V-S1-2: a byte order mark before `on:` on the first line still reads.
root = repo()
write(root, ".github/workflows/gate.yml", "\ufeffon: [pull_request, workflow_dispatch]\njobs: {}\n")
got = look(root)
expect("s1 byte order mark", (got.get("status"), got.get("workflow")), ("found", ".github/workflows/gate.yml"))

# SEC-1: a committed .claude/gate.json that is a symlink is never written through.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
outside = os.path.realpath(tempfile.mkdtemp(prefix="gate-outside-"))
target = write(outside, "rcfile", "export KEEP=1\n")
os.makedirs(os.path.join(root, ".claude"))
os.symlink(target, os.path.join(root, ".claude", "gate.json"))
code, out, err = run_gate(root, "store", ".github/workflows/gate.yml")
expect("sec1 store refuses a symlinked gate.json", code, 1)
with open(target) as handle:
    expect("sec1 outside file untouched", handle.read(), "export KEEP=1\n")
# Nor through a symlinked .claude folder.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
os.symlink(outside, os.path.join(root, ".claude"))
code, out, err = run_gate(root, "store", ".github/workflows/gate.yml")
expect("sec1 store refuses a symlinked .claude", (code, os.path.exists(os.path.join(outside, "gate.json"))), (1, False))

# SEC-3: reading never hangs on a file that does not end, and refuses a huge one.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
os.makedirs(os.path.join(root, ".claude"))
os.symlink("/dev/zero", os.path.join(root, ".claude", "gate.json"))
try:
    r = subprocess.run([sys.executable, FACT, "--gate"], capture_output=True, text=True,
                       cwd=root, env=env_for(), timeout=10)
    expect("sec3 reader does not hang", (r.returncode, r.stdout.strip()), (1, ""))
except subprocess.TimeoutExpired:
    expect("sec3 reader does not hang", "timed out", (1, ""))
try:
    r = subprocess.run([sys.executable, GATE, "look", "--root", root], capture_output=True,
                       text=True, env=env_for(), timeout=10)
    expect("sec3 look does not hang", r.returncode, 0)
except subprocess.TimeoutExpired:
    expect("sec3 look does not hang", "timed out", 0)
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
write(root, ".claude/gate.json", json.dumps({"workflow": ".github/workflows/gate.yml",
                                             "starts": ["workflow_dispatch"], "pad": "x" * 200000}))
expect("sec3 reader refuses a huge file", read_fact(root), (1, ""))

# SEC-2: a workflow that is a symlink, or under a symlinked folder, is never offered or read.
root = repo()
decoy = write(outside, "elsewhere.yml", "name: TOKEN=secret\non: [pull_request, workflow_dispatch]\n")
os.makedirs(os.path.join(root, ".github", "workflows"))
os.symlink(decoy, os.path.join(root, ".github", "workflows", "gate.yml"))
got = look(root)
expect("sec2 symlinked workflow not offered", (got.get("status"), "secret" in json.dumps(got)), ("none", False))
write(root, ".claude/gate.json", json.dumps({"workflow": ".github/workflows/gate.yml", "starts": ["workflow_dispatch"]}))
expect("sec2 reader refuses a symlinked workflow", read_fact(root), (1, ""))
root = repo()
write(outside, "wf/gate.yml", GATE_YML)
os.makedirs(os.path.join(root, ".github"))
os.symlink(os.path.join(outside, "wf"), os.path.join(root, ".github", "workflows"))
expect("sec2 symlinked workflows folder not read", look(root).get("status"), "none")

# V2-S1-1: a byte order mark before `name: Gate` still names the Gate.
root = repo()
write(root, ".github/workflows/ci.yml", "\ufeffname: Gate\non: [workflow_dispatch]\njobs: {}\n")
got = look(root)
expect("s1 byte order mark before name", (got.get("status"), got.get("workflow")), ("found", ".github/workflows/ci.yml"))

# SEC-R1-1: a workflow file of blank lines does not stall working the Gate out.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
write(root, ".github/workflows/blank.yml", "\n" * 100000 + " \n" * 100000)
try:
    r = subprocess.run([sys.executable, GATE, "look", "--root", root], capture_output=True,
                       text=True, env=env_for(), timeout=10)
    expect("secr1 blank lines do not stall look", (r.returncode, json.loads(r.stdout).get("status")), (0, "found"))
except subprocess.TimeoutExpired:
    expect("secr1 blank lines do not stall look", "timed out", (0, "found"))

# SEC-R1-C2-obs: a deeply nested gate.json is nothing stored, not a crash.
root = repo()
write(root, ".github/workflows/gate.yml", GATE_YML)
write(root, ".claude/gate.json", "[" * 60000)
r = subprocess.run([sys.executable, FACT, "--gate"], capture_output=True, text=True, cwd=root, env=env_for())
expect("secr1 nested gate.json reader", (r.returncode, r.stdout.strip(), "Traceback" in r.stderr), (1, "", False))
r = subprocess.run([sys.executable, GATE, "look", "--root", root], capture_output=True, text=True, env=env_for())
expect("secr1 nested gate.json look", (r.returncode, "Traceback" in r.stderr,
                                       json.loads(r.stdout).get("status") if r.returncode == 0 else None), (0, False, "found"))

# The trigger reader handles each form GitHub documents.
for label, text, want in (
        ("string", "on: workflow_dispatch\n", {"workflow_dispatch"}),
        ("list", "on: [push, 'workflow_call']\n", {"push", "workflow_call"}),
        ("flow map", "on: {push: {branches: [main]}, workflow_dispatch: {}}\n", {"push", "workflow_dispatch"}),
        ("quoted key", '"on":\n  workflow_dispatch:\n', {"workflow_dispatch"}),
        ("yaml 1.1 true", "true:\n  pull_request:\n", {"pull_request"}),
        ("list flush with on", "on:\n- pull_request\n- workflow_dispatch\njobs: {}\n", {"pull_request", "workflow_dispatch"}),
        ("comment", "on:  # when\n  # workflow_dispatch:\n  push:\n", {"push"}),
        ("nested keys not triggers", "on:\n  workflow_call:\n    inputs:\n      workflow_dispatch:\n        type: string\n", {"workflow_call"}),
        ("jobs key named on", "name: x\njobs:\n  on:\n    runs-on: x\n", set())):
    expect("triggers " + label, gate_py.triggers(text), want)

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
