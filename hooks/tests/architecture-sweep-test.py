#!/usr/bin/env python3
"""Linear issue MAST-36: /setup brings an existing project in line with its architecture doc.

Scenario 1: `parts` says when a repository holds no code, so setup asks about a review only
when there is code to review.
Scenario 2: a targeted `plan` takes only the code under the parts the person names.
Scenario 3: a sweep `plan` takes every code file in the repository.
Scenario 6: `rules` and `builds` print the doc lines an issue quotes and the builds it needs a
scenario for.
Scenario 8: a review never sends more than one session's share of batches in one run, and
`left` names each part not reviewed when it stops early.

Run from anywhere: python3 hooks/tests/architecture-sweep-test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
SWEEP = os.path.join(PLUGIN, "skills", "setup", "architecture-sweep.py")

passed = 0
failed = 0


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


def repo(files):
    root = os.path.realpath(tempfile.mkdtemp(prefix="arch-sweep-"))
    for rel, lines in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("".join("line {}\n".format(i) for i in range(lines)))
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "start"]):
        subprocess.run(["git"] + args, cwd=root, env=env, check=True, capture_output=True)
    return root


def run(root, *args):
    out = subprocess.run([sys.executable, SWEEP] + list(args), cwd=root, capture_output=True, text=True)
    return out.returncode, out.stdout


def ledger_files(root, ledger):
    """Every code file the ledger's batches cover, by expanding each part's pattern."""
    with open(ledger) as handle:
        data = json.load(handle)
    tracked = [p for p in subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
               if not p.endswith(".md")]
    covered = set()
    for batch in data["batches"]:
        for part in batch["parts"]:
            for path in tracked:
                if part == "*" and "/" not in path:
                    covered.add(path)
                elif part.endswith("/**") and path.startswith(part[:-2]):
                    covered.add(path)
                elif part.endswith("/*") and path.startswith(part[:-1]) and "/" not in path[len(part) - 1:]:
                    covered.add(path)
                elif part == path:
                    covered.add(path)
    return covered, data


# Scenario 1: no code, nothing to review.
docs_only = repo({"README.md": 5, "docs/architecture.md": 20})
code, out = run(docs_only, "parts")
expect("a repository of docs holds no code", (code, out.strip()), (3, "this repository holds no code"))

CODE = {
    "mix.exs": 10,
    "lib/billing/plan.ex": 30,
    "lib/billing/meter.ex": 25,
    "lib/account/status.ex": 20,
    "lib/app.ex": 15,
    "test/billing_test.exs": 12,
    "docs/architecture.md": 40,
    "README.md": 8,
    "node_modules/x/index.js": 500,
}
root = repo(CODE)
code, out = run(root, "parts", "--budget", "60")
patterns = [line.split("\t")[0] for line in out.splitlines()]
expect("parts exits 0 on a repository with code", code, 0)
expect("a folder over the budget is split into its folders and its own files",
       patterns, ["*", "lib/*", "lib/account/**", "lib/billing/**", "test/**"])
expect("docs and dependencies are not code", [p for p in patterns if p.startswith(("docs", "node_modules"))], [])

# Scenario 2: targeted takes only the named parts.
ledger = os.path.join(root, ".claude", "state", "architecture-review.json")
code, out = run(root, "plan", "--ledger", ledger, "--budget", "60", "lib/billing", "lib/account/")
covered, data = ledger_files(root, ledger)
expect("a targeted plan is written", code, 0)
expect("a targeted plan covers only the named parts",
       covered, {"lib/billing/plan.ex", "lib/billing/meter.ex", "lib/account/status.ex"})
expect("a targeted plan records what was named", data["scope"], ["lib/billing", "lib/account/"])
code, out = run(root, "plan", "--ledger", ledger, "--fresh", "lib/payments")
expect("a part with no code is refused, by name", (code, out.strip()), (2, "no code under: lib/payments"))

# Scenario 3: a sweep takes every code file.
code, out = run(root, "plan", "--ledger", ledger, "--budget", "60", "--fresh")
covered, data = ledger_files(root, ledger)
expect("a sweep plan is written", code, 0)
expect("a sweep covers every code file",
       covered, {p for p in CODE if not p.startswith(("docs/", "node_modules/")) and not p.endswith(".md")})
expect("a sweep records its scope as everything", data["scope"], ["everything"])
expect("no batch is over the budget", [b["lines"] for b in data["batches"] if b["lines"] > 60], [])
expect("the plan names the commit it was made at", len(data["head"] or ""), 40)

# A part done review is not overwritten by accident.
code, out = run(root, "plan", "--ledger", ledger, "--budget", "60")
expect("plan refuses over a review that is part done", code, 4)

# Scenario 8: one session's share, then stop and say what is left.
big = repo({"src/part{}/m.py".format(i): 40 for i in range(9)})
ledger = os.path.join(big, ".claude", "state", "architecture-review.json")
code, out = run(big, "plan", "--ledger", ledger, "--budget", "50")
expect("nine parts of 40 lines make nine batches at a budget of 50", out.splitlines()[0].split()[0], "9")
expect("plan says the rest waits for the next run", out.splitlines()[1],
       "one session reviews 6 batches; the other 3 wait for the next run")
ids = []
for _ in range(6):
    code, out = run(big, "next", "--ledger", ledger)
    batch = json.loads(out)
    ids.append(batch["id"])
    run(big, "done", "--ledger", ledger, str(batch["id"]), ".claude/state/review/findings-architecture-reviewer-x.json")
expect("next hands out each batch once, in order", ids, [1, 2, 3, 4, 5, 6])
code, out = run(big, "next", "--ledger", ledger)
expect("a seventh batch in one run is refused", code, 6)
code, out = run(big, "left", "--ledger", ledger)
expect("left names each part not reviewed", out.split(), ["src/part6/**", "src/part7/**", "src/part8/**"])
code, out = run(big, "resume", "--ledger", ledger)
expect("a new session resumes the review", out.strip(), "run 2: 3 of 9 batches left, planned at head " + json.load(open(ledger))["head"])
for _ in range(3):
    code, out = run(big, "next", "--ledger", ledger)
    run(big, "done", "--ledger", ledger, str(json.loads(out)["id"]))
code, out = run(big, "next", "--ledger", ledger)
expect("next says when every batch is reviewed", (code, out.strip()), (5, "every batch is reviewed"))
code, out = run(big, "left", "--ledger", ledger)
expect("left says when nothing is left", out.strip(), "nothing left")
code, out = run(big, "plan", "--ledger", ledger, "--budget", "50")
expect("a finished review can be planned again", code, 0)

# A single file over the budget stands on its own, so nothing is left out.
huge = repo({"lib/huge.ex": 120, "lib/small.ex": 10})
code, out = run(huge, "parts", "--budget", "50")
expect("a file over the budget is its own part",
       [line.split("\t")[0] for line in out.splitlines()], ["lib/huge.ex", "lib/small.ex"])

# Scenario 6: the doc's rules and builds, for the issue to quote.
doc = os.path.join(root, "docs", "architecture.md")
with open(doc, "w") as handle:
    handle.write("""# Shop architecture

## What each build ships

- Hosted: core and billing; billing must meter every save.
- Marketplace: core only; sign-in and erasure must still work without billing.

## The seven rules

- **Direction.** The core never names the billing app.
- **One way in and out.** Billing data is reached only through Billing.Accounts.
- **Call shape.** Callers ask one question of a service and get one answer.
- **Seams.** Does not apply: there is one provider of everything.
- **What each build carries.** Each build in the list above starts and serves its pages.
- **Leftovers.** No rule is written in two apps.
- **Tests and checks.** Each rule above has a check that reads code, not text.
""")
code, out = run(root, "builds", doc)
expect("builds lists each build the doc names", out.splitlines(), [
    "Hosted: core and billing; billing must meter every save.",
    "Marketplace: core only; sign-in and erasure must still work without billing."])
code, out = run(root, "rules", doc)
expect("rules lists the seven rules", out.splitlines()[0], "Direction: The core never names the billing app")
expect("rules lists all seven", len(out.splitlines()), 7)
code, out = run(root, "builds", os.path.join(root, "README.md"))
expect("a doc that names no build says so by its exit", code, 1)

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
