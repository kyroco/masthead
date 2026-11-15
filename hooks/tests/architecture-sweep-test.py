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
    """Every file the ledger's batches hand the reviewers, a line range counted as its file."""
    with open(ledger) as handle:
        data = json.load(handle)
    covered = set()
    for batch in data["batches"]:
        for entry in batch["files"]:
            covered.add(entry.split("#L")[0])
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
expect("a review reviewed and not judged is not planned over", code, 4)
run(big, "judged", "--ledger", ledger)
code, out = run(big, "plan", "--ledger", ledger, "--budget", "50")
expect("a finished review can be planned again", code, 0)

# Round 1, F-9: a file over the budget is split into line ranges, so no batch is over it.
huge = repo({"lib/huge.ex": 120, "lib/small.ex": 10})
code, out = run(huge, "parts", "--budget", "50")
expect("a file over the budget is its own part",
       [line.split("\t")[0] for line in out.splitlines()], ["lib/huge.ex", "lib/small.ex"])
ledger = os.path.join(huge, ".claude", "state", "architecture-review.json")
code, out = run(huge, "plan", "--ledger", ledger, "--budget", "50")
_, data = ledger_files(huge, ledger)
expect("a file over the budget is read in ranges that fit",
       [b["files"] for b in data["batches"]],
       [["lib/huge.ex#L1-50"], ["lib/huge.ex#L51-100"], ["lib/huge.ex#L101-120", "lib/small.ex"]])
expect("no batch is over the budget, even with a file over it",
       [b["lines"] for b in data["batches"] if b["lines"] > 50], [])

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

# Round 1, F-1: code in any language counts, and lock files and docs do not.
other = repo({"src/main.zig": 40, "src/model.jl": 30, "engine/core.cxx": 50, "site/index.html": 20,
              "pnpm-lock.yaml": 9000, "Cargo.lock": 400, "LICENSE": 200, "docs/guide.md": 10,
              "logo.png": 3})
code, out = run(other, "parts")
expect("code in a language with no list entry is still code", code, 0)
ledger = os.path.join(other, ".claude", "state", "architecture-review.json")
run(other, "plan", "--ledger", ledger)
covered, _ = ledger_files(other, ledger)
expect("every code file is reviewed, and no lock file, licence, doc or image",
       covered, {"src/main.zig", "src/model.jl", "engine/core.cxx", "site/index.html"})

# Round 1, F-2: a targeted review at the default budget hands over only what was named.
named = repo({"lib/billing/plan.ex": 30, "lib/billing/meter.ex": 25, "lib/account/status.ex": 20,
              "lib/app.ex": 15, "lib/web/router.ex": 40})
ledger = os.path.join(named, ".claude", "state", "architecture-review.json")
run(named, "plan", "--ledger", ledger, "lib/billing", "lib/account")
covered, data = ledger_files(named, ledger)
expect("a targeted review at the default budget hands over only the named code",
       covered, {"lib/billing/plan.ex", "lib/billing/meter.ex", "lib/account/status.ex"})
expect("its parts name only what was picked",
       [p for b in data["batches"] for p in b["parts"]], ["lib/account/**", "lib/billing/**"])
run(named, "plan", "--ledger", ledger, "--fresh", "lib/billing/plan.ex")
covered, _ = ledger_files(named, ledger)
expect("one named file is the only file handed over", covered, {"lib/billing/plan.ex"})
run(named, "plan", "--ledger", ledger, "--fresh", "lib/*")
covered, _ = ledger_files(named, ledger)
expect("a folder's own files, by the row parts prints, leave its subfolders out", covered, {"lib/app.ex"})

# Round 1, F-3: a folder whose name holds glob characters is handed over by its real path.
routes = repo({"app/[slug]/page.tsx": 30, "app/blog/page.tsx": 30, "app/layout.tsx": 10})
ledger = os.path.join(routes, ".claude", "state", "architecture-review.json")
run(routes, "plan", "--ledger", ledger, "--budget", "40")
covered, _ = ledger_files(routes, ledger)
expect("a folder named with brackets is reviewed", "app/[slug]/page.tsx" in covered, True)
code, out = run(routes, "next", "--ledger", ledger)
batch = json.loads(out)
with open(os.path.join(routes, batch["list"])) as handle:
    expect("next writes the batch's exact file list for the reviewers",
           handle.read().split("\n")[:-1], batch["files"])

# Round 1, F-10: a batch reviewed but never judged reaches the next run's judge.
ledger = os.path.join(big, ".claude", "state", "architecture-review.json")
run(big, "plan", "--ledger", ledger, "--budget", "50", "--fresh")
for _ in range(2):
    code, out = run(big, "next", "--ledger", ledger)
    run(big, "done", "--ledger", ledger, str(json.loads(out)["id"]), "f-{}.json".format(json.loads(out)["id"]))
run(big, "resume", "--ledger", ledger)
code, out = run(big, "next", "--ledger", ledger)
run(big, "done", "--ledger", ledger, str(json.loads(out)["id"]), "f-3.json")
code, out = run(big, "findings", "--ledger", ledger)
expect("the judge gets every batch reviewed and not judged, from any run", out.split(), ["f-1.json", "f-2.json", "f-3.json"])
run(big, "judged", "--ledger", ledger)
code, out = run(big, "findings", "--ledger", ledger)
expect("a judged batch is not judged twice", out.split(), [])

# Round 1, E-1: before any review, left answers plainly.
fresh = os.path.join(big, ".claude", "state", "no-such-review.json")
code, out = run(big, "left", "--ledger", fresh)
expect("left with no review yet says nothing is left", (code, out.strip()), (0, "nothing left"))

# Round 1, F-7: a rule or a build wrapped over several lines is read whole.
wrapped = os.path.join(root, "docs", "wrapped.md")
with open(wrapped, "w") as handle:
    handle.write("""# Shop architecture

## What each build ships

- Hosted: core and billing; billing must meter
  every save.
- Marketplace: core only.

## The seven rules

- **Direction.** The core never names the billing app, and no extension names
  another extension.
- **One way in and out.** Billing data is reached only through Billing.Accounts.
- **Call shape.** Callers ask one question of a service and get one answer.
- **Seams.** Does not apply: there is one provider of everything.
- **What each build carries.** Each build in the list above starts and serves its pages.
- **Leftovers.** No rule is written in two apps.
- **Tests and checks.** Each rule above has a check that reads code, not text.
""")
code, out = run(root, "rules", wrapped)
expect("a wrapped rule is quoted whole", out.splitlines()[0],
       "Direction: The core never names the billing app, and no extension names another extension")
code, out = run(root, "builds", wrapped)
expect("a wrapped build is one build", out.splitlines(),
       ["Hosted: core and billing; billing must meter every save.", "Marketplace: core only."])
plain = os.path.join(root, "docs", "plain.md")
with open(plain, "w") as handle:
    handle.write("""## What each build ships

Hosted carries core and billing, and billing
must meter every save.

Marketplace carries the core only.
""")
code, out = run(root, "builds", plain)
expect("a build written as a paragraph is one build", out.splitlines(),
       ["Hosted carries core and billing, and billing must meter every save.",
        "Marketplace carries the core only."])
table = os.path.join(root, "docs", "table.md")
with open(table, "w") as handle:
    handle.write("""## What each build ships

| Build | Carries |
| -- | -- |
| Hosted | core and billing |
| Marketplace | core only |
""")
code, out = run(root, "builds", table)
expect("a build table gives its rows, not its header", out.splitlines(),
       ["Hosted: core and billing", "Marketplace: core only"])

# Re-verify 1, claim 4: a folder named build, target, dist, deps, vendor or doc inside the code
# is code; only dependencies the repository keeps are left out.
nested = repo({"lib/shop/build/release.ex": 10, "lib/shop/target/campaign.ex": 10,
               "src/doc/render.py": 10, "lib/shop.ex": 10, "assets/node_modules/x/index.js": 50,
               "vendor/lib/a.go": 50, "CMakeLists.txt": 12, "requirements.txt": 5, "notes.txt": 9})
ledger = os.path.join(nested, ".claude", "state", "architecture-review.json")
run(nested, "plan", "--ledger", ledger)
covered, _ = ledger_files(nested, ledger)
expect("a sweep reviews code in folders named like build output, and build files",
       covered, {"lib/shop/build/release.ex", "lib/shop/target/campaign.ex", "src/doc/render.py",
                 "lib/shop.ex", "CMakeLists.txt", "requirements.txt"})

# Re-verify 1, claim 6: every batch reviewed, the session ended before its judge.
ended = repo({"src/a.py": 10})
ledger = os.path.join(ended, ".claude", "state", "architecture-review.json")
run(ended, "plan", "--ledger", ledger)
code, out = run(ended, "next", "--ledger", ledger)
run(ended, "done", "--ledger", ledger, "1", "f-1.json")
code, out = run(ended, "left", "--ledger", ledger)
expect("left says nothing is left to review", out.strip(), "nothing left")
code, out = run(ended, "findings", "--ledger", ledger)
expect("findings still names what is not judged", out.split(), ["f-1.json"])
code, out = run(ended, "plan", "--ledger", ledger)
expect("a new review is refused over findings not judged", code, 4)

# Re-verify 1, claim 7: builds one line each, numbered, with + bullets or sub-bullets, and a
# rule wrapped under a lens heading.
def builds_of(text):
    path = os.path.join(root, "docs", "shape.md")
    with open(path, "w") as handle:
        handle.write("## What each build ships\n\n" + text)
    return run(root, "builds", path)[1].splitlines()

expect("builds one line each, as the template asks, are each a build",
       builds_of("Hosted: core and billing; billing must meter every save.\nMarketplace: core only.\n"),
       ["Hosted: core and billing; billing must meter every save.", "Marketplace: core only."])
expect("a numbered list of builds",
       builds_of("1. Hosted: core and billing.\n2. Marketplace: core only.\n"),
       ["Hosted: core and billing.", "Marketplace: core only."])
expect("a + list of builds", builds_of("+ Hosted\n+ Marketplace\n"), ["Hosted", "Marketplace"])
expect("sub-bullets belong to their build",
       builds_of("- Hosted carries:\n  - core\n  - billing\n- Marketplace carries the core.\n"),
       ["Hosted carries: core, billing", "Marketplace carries the core."])
headed = os.path.join(root, "docs", "headed.md")
with open(headed, "w") as handle:
    handle.write("""## The seven rules

### Direction

The core never names the billing app, and no extension names
another extension.

### One way in and out

Billing data is reached only through Billing.Accounts.
""")
code, out = run(root, "rules", headed)
expect("a wrapped rule under a lens heading is quoted whole", out.splitlines()[0],
       "Direction: The core never names the billing app, and no extension names another extension.")

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
