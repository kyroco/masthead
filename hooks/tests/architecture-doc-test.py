#!/usr/bin/env python3
"""Linear issue MAST-30: /setup finds or starts the project's architecture doc.

Scenario 1: `architecture-doc.py find` names the architecture docs at the
common paths, so setup can ask whether the one it found is the project's.
Scenario 5: `project_fact.py --architecture-doc` prints the recorded doc's
path, read from ARCHITECTURE_DOC in the same env block as every other fact.
Scenarios 3 and 6: `architecture-doc.py check` passes a doc only when it
states each of the seven lenses as a rule (or says why one does not apply),
cites the principles by number, and copies none of their text.

Run from anywhere: python3 hooks/tests/architecture-doc-test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
FACT = os.path.join(PLUGIN, "hooks", "project_fact.py")
DOC = os.path.join(PLUGIN, "skills", "setup", "architecture-doc.py")
TEMPLATE = os.path.join(PLUGIN, "skills", "setup", "architecture-template.md")

passed = 0
failed = 0


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


def repo():
    root = os.path.realpath(tempfile.mkdtemp(prefix="arch-doc-"))
    os.mkdir(os.path.join(root, ".git"))
    os.mkdir(os.path.join(root, ".claude"))
    return root


def write(root, rel, text=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    return path


def settings(root, env, leaf="settings.json"):
    write(root, os.path.join(".claude", leaf), json.dumps({"env": env}))


def clean_env(project=None):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("CLAUDE_CODE_REMOTE", None)
    if project:
        env["CLAUDE_PROJECT_DIR"] = project
    return env


def fact(root, cwd=None, project=True):
    """project=False is a skill's Bash call, where Claude Code sets no CLAUDE_PROJECT_DIR."""
    out = subprocess.run([sys.executable, FACT, "--architecture-doc"], cwd=cwd or root,
                         env=clean_env(root if project else None),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def find(root, cwd=None):
    out = subprocess.run([sys.executable, DOC, "find"], cwd=cwd or root, env=clean_env(),
                         capture_output=True, text=True)
    return out.returncode, out.stdout.split()


def check(doc, principles=None):
    args = [sys.executable, DOC, "check", doc] + ([principles] if principles else [])
    out = subprocess.run(args, env=clean_env(), capture_output=True, text=True)
    return out.returncode, out.stdout


# Scenario 1: setup finds an architecture doc at a common path.
root = repo()
expect("no doc anywhere", find(root), (0, []))
write(root, "docs/architecture.md", "# Architecture\n")
expect("docs/architecture.md", find(root), (0, ["docs/architecture.md"]))
root = repo()
write(root, "ARCHITECTURE.md", "# Architecture\n")
expect("ARCHITECTURE.md at the top", find(root), (0, ["ARCHITECTURE.md"]))
root = repo()
write(root, "docs/engram/architecture.md", "# Engram\n")  # Korium's own layout
write(root, "docs/architecture/README.md", "# Architecture\n")
write(root, "node_modules/pkg/docs/architecture.md", "not ours\n")
write(root, "docs/notes.md", "not a doc\n")
expect("one folder down in docs, and a docs/architecture folder", find(root),
       (0, ["docs/architecture/README.md", "docs/engram/architecture.md"]))
os.mkdir(os.path.join(root, "lib"))
expect("run from a folder inside the repository", find(root, cwd=os.path.join(root, "lib")),
       (0, ["docs/architecture/README.md", "docs/engram/architecture.md"]))

# Scenario 5: the recorded path comes from the same env block as every other fact.
root = repo()
write(root, "docs/architecture.md", "# Architecture\n")
expect("no fact recorded", fact(root), "")
settings(root, {"ISSUE_TRACKER": "linear", "ARCHITECTURE_DOC": "docs/architecture.md"})
expect("fact in settings.json", fact(root), os.path.join(root, "docs", "architecture.md"))
expect("a skill's shell, no CLAUDE_PROJECT_DIR", fact(root, project=False),
       os.path.join(root, "docs", "architecture.md"))
os.mkdir(os.path.join(root, "lib"))
expect("a skill's shell in a folder inside", fact(root, cwd=os.path.join(root, "lib"), project=False),
       os.path.join(root, "docs", "architecture.md"))
write(root, "ARCHITECTURE.md", "# Mine\n")
settings(root, {"ARCHITECTURE_DOC": "ARCHITECTURE.md"}, "settings.local.json")
expect("the personal file wins, as for the tracker", fact(root), os.path.join(root, "ARCHITECTURE.md"))
root = repo()
settings(root, {"ARCHITECTURE_DOC": "docs/gone.md"})
expect("a recorded doc that is no longer there", fact(root), "")
outside = write(os.path.realpath(tempfile.mkdtemp()), "architecture.md", "# Not this repo\n")
settings(root, {"ARCHITECTURE_DOC": outside})
expect("a path outside the repository", fact(root), "")
settings(root, {"ARCHITECTURE_DOC": "../" + os.path.basename(os.path.dirname(outside)) + "/architecture.md"})
expect("a relative path that climbs out", fact(root), "")

# Scenario 5 in a real worktree: the main checkout's fact, the worktree's own copy of the doc.
main = os.path.realpath(tempfile.mkdtemp(prefix="arch-main-"))
subprocess.run(["git", "init", "-q", main], check=True)
write(main, "docs/architecture.md", "# Architecture\n")
subprocess.run(["git", "-C", main, "add", "."], check=True)
subprocess.run(["git", "-C", main, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-q", "-m", "init"], check=True)
settings(main, {"ARCHITECTURE_DOC": "docs/architecture.md"})
tree = os.path.join(os.path.realpath(tempfile.mkdtemp(prefix="arch-tree-")), "wt")
subprocess.run(["git", "-C", main, "worktree", "add", "-q", tree], check=True)
expect("a worker's shell in a worktree", fact(tree, project=False),
       os.path.join(tree, "docs", "architecture.md"))

# Another repository's settings name no doc for this session.
other = repo()
write(other, "docs/architecture.md", "x\n")
settings(other, {"ARCHITECTURE_DOC": "docs/architecture.md"})
out = subprocess.run([sys.executable, FACT, "--root", other, "--architecture-doc"],
                     env=clean_env(repo()), capture_output=True, text=True, check=True).stdout.strip()
expect("another repository's settings", out, "")

# Scenarios 3 and 6: the doc states the seven lenses as rules and cites principles by number.
PRINCIPLES = """# Project

## Principles

- P1. Tenants are kept apart at two layers: the database's row security is the
  real filter, and code sets the tenant once per request.
- P4. A route that carries business logic hands it to a service and stays thin.
- P9. One way in and out. A body of data is reached through one module: the
  caller asks for what it needs, and nothing else reads or writes its tables.
"""
GOOD = """# Architecture

## The seven rules

- **Direction.** The core never names an extension, and extensions do not lean on each other.
- **One way in and out.** Billing data is reached only through one module, which hands back an object (P9).
- **Call shape.** A route asks one service one question and gets a whole answer back (P4).
- **Seams.** Does not apply: this project has one provider of each kind, so no seam is a real swap yet.
- **What each build carries.** The open-source build runs every page with billing absent.
- **Leftovers.** One rule lives in one place; a copy left behind by a move is deleted in the same PR.
- **Tests and checks.** A test proves behavior through the module's door, never by reading its tables (P1).
"""
root = repo()
principles = write(root, "CLAUDE.md", PRINCIPLES)
good = write(root, "docs/architecture.md", GOOD)
code, out = check(good, principles)
expect("a doc that states all seven rules and cites principles", code, 0)
code, out = check(good)
expect("no principles file given", code, 0)

bad = write(root, "missing.md", GOOD.replace(
    "- **Leftovers.** One rule lives in one place; a copy left behind by a move is deleted in the same PR.\n", ""))
code, out = check(bad, principles)
expect("a lens left out fails", code, 1)
expect("the failure names the lens", "Leftovers" in out, True)

bad = write(root, "empty.md", GOOD.replace(
    "Billing data is reached only through one module, which hands back an object (P9).", ""))
code, out = check(bad, principles)
expect("a lens with no rule fails", code, 1)
expect("the failure names that lens", "One way in and out" in out, True)

bad = write(root, "noreason.md", GOOD.replace(
    "Does not apply: this project has one provider of each kind, so no seam is a real swap yet.",
    "Does not apply."))
code, out = check(bad, principles)
expect("does not apply with no reason fails", code, 1)
expect("the failure names Seams", "Seams" in out, True)

bad = write(root, "copied.md", GOOD + "\nP9: A body of data is reached through one module: the caller asks for what it needs.\n")
code, out = check(bad, principles)
expect("principle text copied into the doc fails", code, 1)
expect("the failure names the principle", "P9" in out, True)

bad = write(root, "uncited.md", GOOD.replace(" (P9)", "").replace(" (P4)", "").replace(" (P1)", ""))
code, out = check(bad, principles)
expect("principles exist but none is cited", code, 1)
code, out = check(bad)
expect("no principles to cite", code, 0)

bad = write(root, "wrongnumber.md", GOOD.replace("(P4)", "(P7)"))
code, out = check(bad, principles)
expect("a principle number the project does not have fails", code, 1)
expect("the failure names P7", "P7" in out, True)

bad = write(root, "placeholder.md", GOOD.replace(
    "The core never names an extension, and extensions do not lean on each other.", "<the rule for this project>"))
code, out = check(bad, principles)
expect("a placeholder left in fails", code, 1)

headed = write(root, "headed.md", GOOD.replace(
    "- **Direction.** The core never", "### Direction\n\nThe core never"))
code, out = check(headed, principles)
expect("a lens written as a heading with its rule below", code, 0)
bad = write(root, "headed-empty.md", GOOD.replace(
    "- **Direction.** The core never names an extension, and extensions do not lean on each other.",
    "### Direction\n\n### Other"))
code, out = check(bad, principles)
expect("a lens heading with no rule below fails", code, 1)

# Round 1, finding s6.c1: a heading or a sentence that merely starts with a lens
# name is not that lens's rule.
bad = write(root, "heading-as-rule.md", "## One way in and out for each body of data\n\n" + GOOD.replace(
    "Billing data is reached only through one module, which hands back an object (P9).",
    "<rule, such as \"billing data is reached only through one module\">"))
code, out = check(bad, principles)
expect("a section heading that starts with a lens name is not its rule", code, 1)
expect("the failure names One way in and out", "One way in and out" in out, True)
PROSE = """# Architecture

Direction of travel for the team this year is to ship faster.
One way in and out of the cluster is the load balancer.
Call shape varies a lot across the codebase today.
Seams are where we split the monolith into services.
What each build carries depends on the customer contract.
Leftovers from the old system are still being cleaned up (P1).
Tests and checks run on every push to the main branch.
"""
code, out = check(write(root, "prose.md", PROSE), principles)
expect("sentences that start with lens names are not rules", code, 1)
expect("all seven lenses are named as missing", all(lens in out for lens in (
    "Direction", "One way in and out", "Call shape", "Seams", "What each build carries",
    "Leftovers", "Tests and checks")), True)

code, out = check(TEMPLATE, principles)
expect("the unfilled template fails", code, 1)
expect("the template names all seven lenses", all(lens in open(TEMPLATE).read() for lens in (
    "Direction", "One way in and out", "Call shape", "Seams", "What each build carries",
    "Leftovers", "Tests and checks")), True)

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
