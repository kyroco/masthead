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

INFRA-285: a batch run now starts on a go, as a workflow_dispatch run on
landing. A test for workflow_dispatch is true for it, a test of
github.workflow_ref is not, and the push arm INFRA-283 advised is never true.

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
    if: github.event_name == 'pull_request' || endsWith(github.workflow_ref, '/gate.yml@refs/heads/main')
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
      || (github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/landing'
      && endsWith(github.workflow_ref, '/.github/workflows/masthead-batch.yml@refs/heads/landing'))
    runs-on: ubuntu-latest
    steps:
      - run: echo plan
  gate:
    needs: [plan-checks]
    uses: ./.github/workflows/gate-plan.yml
"""

# The helper fixed, not deleted: it lists both names and its test matches both (arch-1).
RETRY_AFTER = RETRY.replace("workflows: [Gate]", "workflows: [Gate, Masthead batch]").replace(
    "    if: github.event.workflow_run.name == 'Gate'\n",
    "    if: github.event.workflow_run.name == 'Gate' || github.event.workflow_run.name == 'Masthead batch'\n")

# A called workflow fixed the way the snags say, not deleted (arch-1): the
# diff base keeps github.event.before only behind a batch arm, and the check
# lookup matches both names.
PLAN_AFTER = """name: Plan
on:
  workflow_call:
jobs:
  plan:
    runs-on: ubuntu-latest
    env:
      BASE: ${{ (github.ref == 'refs/heads/landing' && endsWith(github.workflow_ref, '/.github/workflows/masthead-batch.yml@refs/heads/landing')) && 'origin/main' || github.event.before }}
    steps:
      - run: gh api "repos/x/y/commits/$SHA/check-runs" --jq '.check_runs[] | select(.name == "gate" or .name == "gate / gate")'
"""

# ---- Scenario 2: setup points at the lines -----------------------------------

root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": BEFORE,
             ".github/workflows/gate-plan.yml": PLAN, ".github/workflows/retry.yml": RETRY,
             ".github/workflows/other.yml": "name: Other\non:\n  workflow_dispatch:\njobs: {}\n"})
code, out, err = snags(root)
check("S2 snags answers JSON and exits 0", code == 0 and out is not None, err)
out = out or {}
found = {(s["workflow"], s["line"], s["kind"]) for s in out.get("snags", [])}
check("S2 status says there are snags", out.get("status") == "snags", out)
check("INFRA-285 points at a test of github.workflow_ref in the Gate",
      (".github/workflows/gate.yml", 15, "event") in found, found)
check("INFRA-285 does not point at a test for workflow_dispatch: a batch run is a workflow_dispatch run now",
      (".github/workflows/gate-plan.yml", 6, "event") not in found, found)
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
             ".github/workflows/gate-plan.yml": PLAN_AFTER, ".github/workflows/retry.yml": RETRY_AFTER})
code, out, err = snags(root)
check("S2 a Gate fixed the way Kyroco did has no snags",
      code == 0 and out and out.get("status") == "clear" and out.get("snags") == [], out or err)

check("S2 the fixed Gate's called workflow and helper were read",
      out and set(out.get("read", [])) == {".github/workflows/gate.yml", ".github/workflows/gate-plan.yml",
                                           ".github/workflows/retry.yml"}, out)

# A test of the run's name is told about the run's name, not a job's (S2-2),
# even when the Gate also has a job keyed gate.
retry_line = [s for s in each if s["workflow"] == ".github/workflows/retry.yml" and s["line"] == 8]
check("S2 a run-name test is told the run is named Masthead batch",
      retry_line and "Masthead batch" in retry_line[0]["misses"] and "gate / " not in retry_line[0]["misses"],
      retry_line)

# A helper fixed only halfway (its list names Masthead batch, its test still
# only Gate) is still pointed at (arch-1, round 2).
half = RETRY.replace("workflows: [Gate]", "workflows: [Gate, Masthead batch]")
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": AFTER,
             ".github/workflows/gate-plan.yml": PLAN_AFTER, ".github/workflows/retry.yml": half})
code, out, err = snags(root)
check("S2 a half-fixed helper's name test is still pointed at",
      out and [(s["workflow"], s["line"], s["kind"]) for s in out.get("snags", [])]
      == [(".github/workflows/retry.yml", 8, "check")], out or err)

# A run-name test fixed across a folded if: is clear.
folded = RETRY.replace("workflows: [Gate]", "workflows: [Gate, Masthead batch]").replace(
    "    if: github.event.workflow_run.name == 'Gate'\n",
    "    if: >-\n      github.event.workflow_run.name == 'Gate'\n"
    "      || github.event.workflow_run.name == 'Masthead batch'\n")
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": AFTER,
             ".github/workflows/gate-plan.yml": PLAN_AFTER, ".github/workflows/retry.yml": folded})
code, out, err = snags(root)
check("S2 a run-name test fixed across a folded if is clear",
      out and out.get("status") == "clear", out or err)

# Every way to write the workflow_dispatch trigger is a trigger, not a test (FIX-2),
# and a job's own quoted name is not a check lookup (FIX-3).
for label, on in (("an empty map", "on:\n  pull_request:\n  workflow_dispatch: {}\n  workflow_call:\n"),
                  ("null", "on:\n  pull_request:\n  workflow_dispatch: null\n  workflow_call:\n"),
                  ("a flow list", "on: [pull_request, workflow_dispatch, workflow_call]\n"),
                  ("a flow list on its own line", "on:\n  [pull_request, workflow_dispatch, workflow_call]\n"),
                  ("a block list", "on:\n  - pull_request\n  - workflow_dispatch\n  - workflow_call\n"),
                  ("a quoted key", "on:\n  pull_request:\n  'workflow_dispatch':\n    inputs: {}\n  workflow_call:\n")):
    text = "name: Gate\n" + on + "jobs:\n  verdict:\n    name: 'Gate'\n    runs-on: ubuntu-latest\n    steps:\n      - name: \"gate\"\n        run: echo ok\n"
    root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": text})
    code, out, err = snags(root)
    check("S2 a trigger written as {} and quoted job names are clear".format(label),
          code == 0 and out and out.get("status") == "clear", out or err)

# The batch check is "gate / " and the Gate's own job name, so a lookup of a
# Gate job named test is pointed at, and its message names "gate / test" (FIX-1).
TEST_GATE = """name: Checks
on:
  workflow_call:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""
LOOKUP = """name: Notify
on:
  workflow_call:
jobs:
  tell:
    runs-on: ubuntu-latest
    steps:
      - run: gh api "repos/x/y/commits/$SHA/check-runs?check_name=test"
"""
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": TEST_GATE.replace(
    "      - run: echo ok\n", "      - run: echo ok\n  tell:\n    uses: ./.github/workflows/notify.yml\n"),
    ".github/workflows/notify.yml": LOOKUP})
code, out, err = snags(root)
checks = [s for s in (out or {}).get("snags", []) if s["kind"] == "check"]
check("S2 a lookup of the Gate's job test is pointed at",
      [(s["workflow"], s["line"]) for s in checks] == [(".github/workflows/notify.yml", 8)], out or err)
check("S2 its message names the check gate / test", checks and "gate / test" in checks[0]["misses"], checks)

# The push arm INFRA-283 advised is never true once a batch starts on a go (INFRA-285):
# a Gate that still has it is pointed at that line, and told what to put there.
PUSH_ARM = AFTER.replace("github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/landing'",
                         "github.event_name == 'push' && github.ref == 'refs/heads/landing'")
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": PUSH_ARM})
code, out, err = snags(root)
pushes = [s for s in (out or {}).get("snags", []) if s["kind"] == "push"]
check("INFRA-285 the old push arm for a batch run is pointed at, and only that line",
      [(s["line"], s["kind"]) for s in (out or {}).get("snags", [])] == [(18, "push")], out or err)
check("INFRA-285 its message says a batch run starts on a go and gives the workflow_dispatch arm",
      pushes and "says go" in pushes[0]["misses"]
      and "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/landing'" in pushes[0]["misses"],
      pushes)
plain_push = "name: Gate\non:\n  push:\n    branches: [main]\n  workflow_call:\njobs:\n  deploy:\n" \
             "    if: github.event_name == 'push'\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": plain_push})
code, out, err = snags(root)
check("INFRA-285 a push test with no landing or starter beside it is not a batch arm and is clear",
      out and out.get("status") == "clear", out or err)

# s1-C2: a workflow of the repository that runs on every push runs on each push to landing too,
# costing minutes outside the batch run. Snags points at each one; one kept off landing is clear.
def landing_runs(on):
    text = "name: Tests\n" + on + "jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
    root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": AFTER, ".github/workflows/tests.yml": text,
                 ".github/workflows/masthead-batch.yml": "name: Masthead batch\non:\n  workflow_dispatch:\njobs: {}\n"})
    code, out, err = snags(root)
    return [(s["workflow"], s["line"]) for s in (out or {}).get("snags", []) if s["kind"] == "landing-push"], out or err


for label, on, line in (("on: push", "on: push\n", 2),
                        ("a flow list with push", "on: [push, pull_request]\n", 2),
                        ("a push block with no filter", "on:\n  push:\n  pull_request:\n", 3),
                        ("a push to every branch", "on:\n  push:\n    branches: ['**']\n", 3),
                        ("a push that names landing", "on:\n  push:\n    branches: [main, landing]\n", 3),
                        ("a push that ignores only main", "on:\n  push:\n    branches-ignore:\n      - main\n", 3)):
    found, out = landing_runs(on)
    check("s1-C2 a workflow that runs on a push to landing is pointed at ({})".format(label),
          found == [(".github/workflows/tests.yml", line)], out)
for label, on in (("main only", "on:\n  push:\n    branches: [main]\n"),
                  ("landing ignored", "on:\n  push:\n    branches-ignore: [landing]\n"),
                  ("tags only", "on:\n  push:\n    tags: ['v*']\n"),
                  ("no push", "on:\n  pull_request:\n")):
    found, out = landing_runs(on)
    check("s1-C2 a workflow that does not run on a push to landing is clear ({})".format(label), found == [], out)
found, out = landing_runs("on: push\n")
lp = [s for s in out.get("snags", []) if s["kind"] == "landing-push"] if isinstance(out, dict) else []
check("s1-C2 the snag says each landed change runs it and how to keep it off landing",
      lp and "every push to landing" in lp[0]["misses"] and "branches-ignore: [landing]" in lp[0]["misses"], lp)

# A workflow_ref test with no batch arm nearby is still pointed at, even when the
# file names masthead-batch.yml somewhere else.
far = AFTER.replace("    runs-on: ubuntu-latest\n    steps:\n      - run: echo plan\n",
                    "    runs-on: ubuntu-latest\n    steps:\n      - run: echo plan\n"
                    "  picker:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo one\n"
                    "      - run: echo two\n      - run: echo three\n      - run: echo four\n"
                    "      - if: endsWith(github.workflow_ref, '/gate.yml@refs/heads/main')\n        run: echo pick\n")
root = repo({".claude/gate.json": STORED, ".github/workflows/gate.yml": far})
code, out, err = snags(root)
found = {(s["line"], s["kind"]) for s in (out or {}).get("snags", [])}
check("S2 a far-off workflow_ref test is still pointed at", (30, "event") in found, out or err)
check("S2 the workflow_ref test inside the batch arm is not", (19, "event") not in found, found)

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
for words in ("workflow_dispatch", "event `workflow_dispatch`", "ref `refs/heads/landing`",
              "masthead-batch.yml@refs/heads/landing", "github.event.before", "gate / <job>", "Masthead batch"):
    check("S1 setup names " + words + " before the first batch", words in before_push)
check("S1 setup does not tell every repository its check is gate / gate",
      "The verdict check is named `gate / gate`, not `gate`" not in before_push)

# ---- Scenario 3: the batch doc and the README write it down, step by step ----

doc = flat(BATCH_DOC)
readme = flat(README)
readme_part = readme.split("### The optional batch run", 1)[-1].split("### Install options", 1)[0]
for name, text in (("references/batch-run.md", doc), ("README batch section", readme_part)):
    for words in ("workflow_dispatch", "github.workflow_ref", "masthead-batch.yml@refs/heads/landing",
                  "refs/heads/landing", "github.event.before", "gate / <job>", "gate / gate", "Masthead batch",
                  "gate.py snags", "Kyroco"):
        check("S3 {} says {}".format(name, words), words in text)
check("S3 the README does not say every Gate's job is named gate", "and so is your Gate's job" not in readme_part)
OLD_ARM = "github.event_name == 'push' && github.ref == 'refs/heads/landing'"
NEW_ARM = "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/landing'"
for name, text in (("references/batch-run.md", doc), ("README batch section", readme_part), ("setup", before_push)):
    check("INFRA-285 {} no longer gives the push arm as the match for a batch run".format(name),
          OLD_ARM not in text, text[:300])
for name, text in (("references/batch-run.md", doc), ("README batch section", readme_part)):
    check("INFRA-285 {} gives the workflow_dispatch arm".format(name), NEW_ARM in text)
check("s1-C2 the README does not say a push to landing starts nothing at all",
      "a push to `landing` starts nothing" not in readme_part and "starts no batch run" in readme_part, readme_part[:600])
check("s1-C2 setup says the starter must reach main before the first go",
      "must be on main" in flat(SKILL), "")
check("S3 the batch doc calls Kyroco's test an excerpt, not the whole test", "as it reads now" not in doc)
check("S3 the README gives the Gate steps as numbered steps",
      "Make your Gate ready for a batch run" in readme_part and " 1. " in readme_part.split(
          "Make your Gate ready for a batch run", 1)[-1][:3000], readme_part[:200])

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
