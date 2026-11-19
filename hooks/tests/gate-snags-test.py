#!/usr/bin/env python3
"""Linear issue INFRA-283: warn a repository opting in to the batch run about the three things its Gate may key on.

Kyroco's first real batch run (run 44591628232, November 19, 2026) went green,
but its Gate had to change in three ways first (Korium 601448c5):
  1. Under the starter the Gate runs as a called workflow on a push event, and
     github.workflow_ref names masthead-batch.yml, so logic keyed on
     workflow_dispatch misses a batch run.
  2. github.event.before as a diff base sees only the last push, not the batch.
  3. The verdict check is named "gate / gate", not "gate", and a workflow_run
     helper keyed on the workflow name "Gate" does not see "Masthead batch".

Scenario 1: setup names the three things before the first batch.
Scenario 2: `gate.py snags` reads the stored Gate, the workflows it calls and
the workflow_run helpers, points at each line that keys on one of the three,
and says what a batch run would miss. Lines already fixed the way Kyroco did
are not pointed at.
Scenario 3: references/batch-run.md and the README write the three things
down, step by step, with Kyroco's match as the example.

Run from anywhere: python3 hooks/tests/gate-snags-test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
GATE = os.path.join(PLUGIN, "skills", "setup", "gate.py")
SKILL = os.path.join(PLUGIN, "skills", "setup", "SKILL.md")
README = os.path.join(PLUGIN, "README.md")
BATCH_DOC = os.path.join(PLUGIN, "references", "batch-run.md")

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL {}{}".format(name, (": " + str(detail)[:600]) if detail else ""))


def repo(files):
    root = os.path.realpath(tempfile.mkdtemp(prefix="gate-snags-"))
    os.mkdir(os.path.join(root, ".git"))
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return root


def snags(root):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    run = subprocess.run([sys.executable, GATE, "snags", "--root", root],
                         capture_output=True, text=True, env=env)
    try:
        return run.returncode, json.loads(run.stdout), run.stderr
    except ValueError:
        return run.returncode, None, run.stdout + run.stderr


def flat(path):
    with open(path, encoding="utf-8") as handle:
        return " ".join(handle.read().split())


STORED = '{\n  "workflow": ".github/workflows/gate.yml",\n  "starts": ["workflow_call", "workflow_dispatch"]\n}\n'

# A Gate that keys on all three, the way Kyroco's did before its first batch.
BEFORE = """name: Gate
on:
  pull_request:
  workflow_dispatch:   # started by hand
  workflow_call:
jobs:
  changes:
    runs-on: ubuntu-latest
    steps:
      - name: Diff base
        env:
          BASE: ${{ github.event.pull_request.base.sha || github.event.before }}
        run: git diff --name-only "$BASE...HEAD"
  plan-checks:
    if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'
    uses: ./.github/workflows/gate-plan.yml
  gate:
    needs: [changes]
    runs-on: ubuntu-latest
    steps:
      - run: echo verdict
"""

PLAN = """name: Plan
on:
  workflow_call:
jobs:
  plan:
    runs-on: ${{ github.event_name == 'workflow_dispatch' && 'self-hosted' || 'ubuntu-latest' }}
    steps:
      - run: gh api "repos/x/y/commits/$SHA/check-runs?check_name=gate"
"""

RETRY = """name: Retry
on:
  workflow_run:
    workflows: [Gate]
    types: [completed]
jobs:
  retry:
    if: github.event.workflow_run.name == 'Gate'
    runs-on: ubuntu-latest
    steps:
      - run: echo retry
"""

# The same Gate after Kyroco's fixes: a batch arm beside each dispatch test,
# the diff against main, the helper listening to both names.
AFTER = """name: Gate
on:
  pull_request:
  workflow_dispatch:
  workflow_call:
jobs:
  changes:
    runs-on: ubuntu-latest
    steps:
      - name: Diff base
        env:
          BASE: ${{ github.event.pull_request.base.sha || 'origin/main' }}
        run: git diff --name-only "$BASE...HEAD"
  plan-checks:
    if: >-
      github.event_name == 'pull_request'
      || (github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main')
      || (github.event_name == 'push' && github.ref == 'refs/heads/landing'
      && endsWith(github.workflow_ref, '/.github/workflows/masthead-batch.yml@refs/heads/landing'))
    runs-on: ubuntu-latest
    steps:
      - run: echo plan
"""

RETRY_AFTER = RETRY.replace("workflows: [Gate]", "workflows: [Gate, Masthead batch]").replace(
    "    if: github.event.workflow_run.name == 'Gate'\n", "")

# ---- Scenario 2: setup points at the lines -----------------------------------

root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": BEFORE,
             ".github/workflows/gate-plan.yml": PLAN, ".github/workflows/retry.yml": RETRY,
             ".github/workflows/other.yml": "name: Other\non:\n  workflow_dispatch:\njobs: {}\n"})
code, out, err = snags(root)
check("S2 snags answers JSON and exits 0", code == 0 and out is not None, err)
out = out or {}
found = {(s["workflow"], s["line"], s["kind"]) for s in out.get("snags", [])}
check("S2 status says there are snags", out.get("status") == "snags", out)
check("S2 points at the dispatch test in the Gate",
      (".github/workflows/gate.yml", 15, "event") in found, found)
check("S2 points at the dispatch test in a workflow the Gate calls",
      (".github/workflows/gate-plan.yml", 6, "event") in found, found)
check("S2 points at github.event.before", (".github/workflows/gate.yml", 12, "base") in found, found)
check("S2 points at a check named gate", (".github/workflows/gate-plan.yml", 8, "check") in found, found)
check("S2 points at a workflow_run helper listening only to Gate",
      (".github/workflows/retry.yml", 4, "helper") in found, found)
check("S2 points at a helper comparing the run's name to Gate",
      (".github/workflows/retry.yml", 8, "check") in found, found)
check("S2 does not point at the workflow_dispatch trigger key",
      not any(f[0] == ".github/workflows/gate.yml" and f[1] == 4 for f in found), found)
check("S2 does not read a workflow neither the Gate nor a helper is",
      not any(f[0] == ".github/workflows/other.yml" for f in found), found)
each = out.get("snags", [])
check("S2 each snag quotes its line and says what a batch run misses",
      each and all(s.get("text") and s.get("misses") for s in each), each)
event = [s for s in each if s["kind"] == "event"]
check("S2 the event snag says how to match a batch run",
      event and "masthead-batch.yml@refs/heads/landing" in event[0]["misses"], event)
base = [s for s in each if s["kind"] == "base"]
check("S2 the base snag says to diff against main", base and "main" in base[0]["misses"], base)
helper = [s for s in each if s["kind"] == "helper"]
check("S2 the helper snag names Masthead batch", helper and "Masthead batch" in helper[0]["misses"], helper)
check("S2 the read list names the Gate, what it calls and the helper",
      set(out.get("read", [])) == {".github/workflows/gate.yml", ".github/workflows/gate-plan.yml",
                                   ".github/workflows/retry.yml"}, out.get("read"))

# Lines already fixed the way Kyroco did are not pointed at.
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": AFTER,
             ".github/workflows/retry.yml": RETRY_AFTER})
code, out, err = snags(root)
check("S2 a Gate fixed the way Kyroco did has no snags",
      code == 0 and out and out.get("status") == "clear" and out.get("snags") == [], out or err)

# A dispatch test with no batch arm nearby is still pointed at, even when the
# file names masthead-batch.yml somewhere else.
far = AFTER.replace("    runs-on: ubuntu-latest\n    steps:\n      - run: echo plan\n",
                    "    runs-on: ubuntu-latest\n    steps:\n      - run: echo plan\n"
                    "  picker:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo one\n"
                    "      - run: echo two\n      - run: echo three\n      - run: echo four\n"
                    "      - if: github.event_name == 'workflow_dispatch'\n        run: echo pick\n")
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": far})
code, out, err = snags(root)
found = {(s["line"], s["kind"]) for s in (out or {}).get("snags", [])}
check("S2 a far-off dispatch test is still pointed at", (30, "event") in found, out or err)
check("S2 the fixed dispatch test beside the batch arm is not", (17, "event") not in found, found)

# No Gate stored: nothing to read, and it says so.
root = repo({".github/workflows/gate.yml": BEFORE})
code, out, err = snags(root)
check("S2 with no Gate stored, snags says none and reads nothing",
      code == 0 and out and out.get("status") == "none" and out.get("snags") == [] and out.get("say"),
      out or err)

# A symlinked workflow is not the repository's own and is not read.
root = repo({".claude/gate.json": STORED, ".github/workflows/real.yml": BEFORE})
os.symlink(os.path.join(root, ".github/workflows/real.yml"), os.path.join(root, ".github/workflows/gate.yml"))
code, out, err = snags(root)
check("S2 a symlinked Gate is not read",
      code == 0 and out and out.get("snags") == [] and ".github/workflows/gate.yml" not in out.get("read", []),
      out or err)

# ---- Scenario 1: setup names the three things before the first batch ---------

skill = flat(SKILL)
batch_part = skill.split("### Then the batch run, only with a Gate stored", 1)[-1].split("## 10.", 1)[0]
before_push = batch_part.split("Land the starter", 1)[0]
check("S1 setup runs gate.py snags before the starter lands", "gate.py snags" in before_push, before_push[-800:])
for words in ("workflow_dispatch", "masthead-batch.yml@refs/heads/landing", "github.event.before",
              "gate / gate", "Masthead batch"):
    check("S1 setup names " + words + " before the first batch", words in before_push)

# ---- Scenario 3: the batch doc and the README write it down, step by step ----

doc = flat(BATCH_DOC)
readme = flat(README)
readme_part = readme.split("### The optional batch run", 1)[-1].split("### Install options", 1)[0]
for name, text in (("references/batch-run.md", doc), ("README batch section", readme_part)):
    for words in ("workflow_dispatch", "github.workflow_ref", "masthead-batch.yml@refs/heads/landing",
                  "refs/heads/landing", "github.event.before", "gate / gate", "Masthead batch",
                  "gate.py snags", "Kyroco"):
        check("S3 {} says {}".format(name, words), words in text)
check("S3 the README gives the Gate steps as numbered steps",
      "Make your Gate ready for a batch run" in readme_part and " 1. " in readme_part.split(
          "Make your Gate ready for a batch run", 1)[-1][:3000], readme_part[:200])

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
