#!/usr/bin/env python3
"""Linear issue MAST-31: each new ADR says how it applies the architecture doc and which builds it must work in.

1. With an architecture doc recorded, a new ADR with no section citing the doc is refused,
   and the refusal says what the section needs.
2. The section gives each part of the doc it names a verdict (conforms, or diverges and why)
   and lists the builds the work must work in.
3. An ADR naming only the parts it touches is accepted.
4. An ADR already in git history is not asked for the new section.
5. With no architecture doc recorded, the gates behave as before.
6. Opening a pull request whose ADR diverges from the doc is refused unless the same pull
   request edits the doc. For an ADR folder outside the repository (a wiki clone), the
   pull request's ADRs are the ones its title, body or commits name by number.

Run from anywhere: python3 hooks/tests/architecture-alignment-test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS_GATE = os.path.join(HOOKS, "adr-sections-gate.py")
STRUCTURE_GATE = os.path.join(HOOKS, "adr-structure-gate.sh")

T = os.path.realpath(tempfile.mkdtemp(prefix="arch-alignment-test."))
BASE_ENV = {k: v for k, v in os.environ.items()
            if k not in ("ADR_DIR", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "ADR_STRUCTURE_GATE")}

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print("ok   - %s" % name)
    else:
        failed += 1
        print("FAIL - %s %s" % (name, detail))


DOC = """# Shop architecture

The target shape.

## The parts

- core in lib/core, the shop; billing in lib/billing, an extension.

## One way in and out for each body of data

- Orders are reached only through Orders, which hands back an Order.

## Core and extensions

The core never names billing.

## What each build ships

- Hosted: core and billing.
- Self-hosted: core alone, and it still takes orders.

## The seven rules

- **Direction.** The core never names an extension.
- **Seams.** Does not apply: there is one provider.
"""

ALIGNED = """## Architecture Alignment

- `Core and extensions`: conforms. Billing plugs in through the hook the core offers.
- **Direction**: conforms, the core never names billing.

Builds: Hosted, Self-hosted
"""

DIVERGES = """## Architecture Alignment

- `One way in and out for each body of data`: diverges, because reports read orders straight from the table for speed.

Builds: Hosted
"""


def adr(alignment="", title="ADR-0007: take orders"):
    return """# %s

## Status

Proposed

## Principle Alignment

P1 conforms.

## Context

`lib/core/orders.ex:1`.

## Options Considered

One.

## Decision

This one.

## Rationale

Because.

## Acceptance Criteria

- AC-1: an order is taken.
- AC-2: a bad order is refused.

## You Are Done When

Both hold.

## Falsifiability

If orders are lost, revisit.

%s""" % (title, alignment)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
                           "-c", "user.email=t@example.com"] + list(args),
                          capture_output=True, text=True, check=True).stdout


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def make_repo(name, adr_dir="docs/adr", doc=True, base_doc=DOC):
    """A repository on main with one commit; it records the doc only when `doc`."""
    repo = os.path.join(T, name)
    os.makedirs(os.path.join(repo, ".claude"))
    git(repo, "init", "-q", "-b", "main")
    env = {"ADR_DIR": adr_dir}
    if doc:
        env["ARCHITECTURE_DOC"] = "docs/architecture.md"
        write(os.path.join(repo, "docs", "architecture.md"), base_doc)
    write(os.path.join(repo, ".claude", "settings.json"), json.dumps({"env": env}))
    write(os.path.join(repo, "README.md"), "x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def commit(repo, files, message):
    for rel, text in files.items():
        write(os.path.join(repo, rel), text)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", message)


def gate(repo, tool, tool_input):
    """The write-time gate's refusal reason, or '' when it allows."""
    env = dict(BASE_ENV, CLAUDE_PROJECT_DIR=repo)
    out = subprocess.run([sys.executable, SECTIONS_GATE],
                         input=json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": repo}),
                         capture_output=True, text=True, cwd=repo, env=env).stdout
    if not out.strip():
        return ""
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


def write_adr(repo, text, rel="docs/adr/ADR-0007-take-orders.md"):
    return gate(repo, "Write", {"file_path": os.path.join(repo, rel), "content": text})


def stop_gate(repo):
    env = dict(BASE_ENV, CLAUDE_PROJECT_DIR=repo)
    r = subprocess.run(["bash", STRUCTURE_GATE], input="", capture_output=True, text=True, cwd=repo, env=env)
    return r.returncode, r.stderr


def pr(repo, body="Builds the order page.", extra=""):
    return gate(repo, "Bash", {"command": "gh pr create --title 'Take orders' --body '%s'%s" % (body, extra)})


# ------------------------------------------------------------------ scenario 1
r = make_repo("s1")
why = write_adr(r, adr())
check("1: a new ADR with no alignment section is refused", "`## Architecture Alignment` is absent" in why, why)
check("1: the refusal names the doc and says what the section needs",
      "docs/architecture.md" in why and "conforms, or diverges and why" in why and "`Builds:`" in why, why)

why = write_adr(r, adr("## Architecture Alignment\n\nWe follow the doc.\n\nBuilds: Hosted\n"))
check("1: a section that cites no part of the doc is refused, listing the doc's parts",
      "names no part of the architecture doc" in why and "`Core and extensions`" in why
      and "`Direction`" in why, why)

# ------------------------------------------------------------------ scenario 2
why = write_adr(r, adr("## Architecture Alignment\n\n- `Core and extensions`: billing plugs in.\n\nBuilds: Hosted\n"))
check("2: a part named with no verdict is refused", "`Core and extensions` with no verdict" in why, why)

why = write_adr(r, adr("## Architecture Alignment\n\n- `Core and extensions`: diverges.\n\nBuilds: Hosted\n"))
check("2: a divergence with no why is refused", "diverges from `Core and extensions` but not why" in why, why)

why = write_adr(r, adr("## Architecture Alignment\n\n- `Core and extensions`: conforms.\n"))
check("2: a section with no Builds line is refused", "lists no builds" in why, why)

why = write_adr(r, adr("## Architecture Alignment\n\n- `Core and extensions`: conforms.\n\nBuilds:\n"))
check("2: an empty Builds line is refused", "lists no builds" in why, why)

why = write_adr(r, adr(ALIGNED))
check("2: a section with a verdict per part and its builds is accepted", why == "", why)

why = write_adr(r, adr(DIVERGES))
check("2: a divergence that says why is accepted at write time", why == "", why)

why = write_adr(r, adr("## Architecture Alignment\n\n### Core and extensions\n\nConforms: billing plugs in "
                       "through the hook.\n\n**Builds:**\n\n- Hosted\n- Self-hosted\n"))
check("2: one heading per part and a bulleted Builds list are read too", why == "", why)

# ------------------------------------------------------------------ scenario 3
why = write_adr(r, adr("## Architecture Alignment\n\n- **Direction**: conforms.\n\nBuilds: Self-hosted\n"))
check("3: an ADR naming one part of the doc is accepted; the other parts are not asked for", why == "", why)

# ------------------------------------------------------------------ the Stop gate holds the same section
r = make_repo("s1-stop")
write(os.path.join(r, "docs/adr/ADR-0007-take-orders.md"), adr())
code, err = stop_gate(r)
check("1: the Stop gate holds a new ADR with no alignment section",
      code == 2 and "Architecture Alignment` is absent" in err, "%s %s" % (code, err))
write(os.path.join(r, "docs/adr/ADR-0007-take-orders.md"), adr(ALIGNED))
code, err = stop_gate(r)
check("2: the Stop gate passes one with the section", code == 0, "%s %s" % (code, err))

# ------------------------------------------------------------------ scenario 4
r = make_repo("s4")
commit(r, {"docs/adr/ADR-0007-take-orders.md": adr()}, "an ADR from before")
why = write_adr(r, adr().replace("Proposed", "Accepted"))
check("4: an ADR already in git history is edited without the new section", why == "", why)
why = gate(r, "Edit", {"file_path": os.path.join(r, "docs/adr/ADR-0007-take-orders.md"),
                       "old_string": "Proposed", "new_string": "Accepted"})
check("4: an Edit of it is not asked for the section either", why == "", why)
write(os.path.join(r, "docs/adr/ADR-0007-take-orders.md"), adr().replace("Proposed", "Accepted"))
code, err = stop_gate(r)
check("4: nor is the Stop gate", code == 0, "%s %s" % (code, err))

# ------------------------------------------------------------------ scenario 5
r = make_repo("s5", doc=False)
why = write_adr(r, adr())
check("5: with no doc recorded, a new ADR without the section is accepted", why == "", why)
why = write_adr(r, adr().replace("## Falsifiability", "## Not it"))
check("5: and the shape is held as before, with no word of the alignment section",
      "Falsifiability` is absent" in why and "Architecture Alignment" not in why, why)
r = make_repo("s5-missing-file", doc=False)
write(os.path.join(r, ".claude", "settings.json"),
      json.dumps({"env": {"ADR_DIR": "docs/adr", "ARCHITECTURE_DOC": "docs/gone.md"}}))
why = write_adr(r, adr())
check("5: a recorded doc that is not there asks for nothing new", why == "", why)

# ------------------------------------------------------------------ scenario 6, the ADR travels in the pull request
r = make_repo("s6")
git(r, "switch", "-q", "-c", "feature")
commit(r, {"docs/adr/ADR-0007-take-orders.md": adr(DIVERGES)}, "Write ADR-0007")
why = pr(r)
check("6: a pull request whose ADR diverges and leaves the doc unchanged is refused",
      "docs/adr/ADR-0007-take-orders.md" in why
      and "`One way in and out for each body of data`" in why and "docs/architecture.md" in why, why)
why = gate(r, "mcp__github__create_pull_request",
           {"title": "Take orders", "body": "x", "base": "main", "head": "feature"})
check("6: the connector's pull request is refused the same way", "ADR-0007-take-orders.md" in why, why)
why = gate(r, "Bash", {"command": "gh pr view"})
check("6: a command that opens no pull request is not held", why == "", why)

commit(r, {"docs/architecture.md": DOC + "\nReports may read orders from the table (ADR-0007).\n"}, "Update the doc")
why = pr(r)
check("6: the same pull request with the doc edited is allowed", why == "", why)

r = make_repo("s6-conforms")
git(r, "switch", "-q", "-c", "feature")
commit(r, {"docs/adr/ADR-0007-take-orders.md": adr(ALIGNED)}, "Write ADR-0007")
check("6: a pull request whose ADR conforms is allowed", pr(r) == "")

r = make_repo("s6-old-divergence")
commit(r, {"docs/adr/ADR-0007-take-orders.md": adr(DIVERGES)}, "an older divergence, already answered")
git(r, "switch", "-q", "-c", "feature")
commit(r, {"docs/adr/ADR-0007-take-orders.md": adr(DIVERGES).replace("Proposed", "Accepted")}, "Accept it")
check("6: an edit that adds no new divergence is allowed", pr(r) == "")

# ------------------------------------------------------------------ scenario 6, an ADR folder outside the repository
wiki = os.path.join(T, "wiki", "ADR")
write(os.path.join(wiki, "Current", "ADR-0007-take-orders.md"), adr(DIVERGES))
write(os.path.join(wiki, "Current", "ADR-0008-ship-orders.md"), adr(ALIGNED, "ADR-0008: ship"))

r = make_repo("s6-wiki", adr_dir=wiki)
git(r, "switch", "-q", "-c", "feature")
commit(r, {"lib/orders.ex": "x\n"}, "Build reports")
check("6: a pull request that names no ADR is not held", pr(r) == "")
why = pr(r, body="Builds ADR-0007 reports.")
check("6: a wiki ADR named in the body that diverges is refused, saying which and where",
      "ADR-0007, named in the pull request's title or body" in why
      and os.path.join(wiki, "Current", "ADR-0007-take-orders.md") in why, why)
check("6: a wiki ADR named that conforms is allowed", pr(r, body="Builds ADR-0008.") == "")

body_file = os.path.join(r, "body.md")
write(body_file, "Fixes MAST-1. Builds ADR 7.\n")
why = pr(r, body="", extra=" --body-file body.md")
check("6: an ADR named in a --body-file is read", "named in the pull request's title or body" in why, why)

commit(r, {"lib/reports.ex": "x\n"}, "Read orders for reports (ADR-0007)")
why = pr(r)
check("6: a wiki ADR named in a commit message is found, naming the commit",
      "ADR-0007, named in commit " in why, why)

commit(r, {"docs/architecture.md": DOC + "\nReports read orders from the table.\n"}, "Update the doc")
check("6: with the doc edited in the pull request it is allowed", pr(r, body="Builds ADR-0007.") == "")

r = make_repo("s6-wiki-cited", adr_dir=wiki, base_doc=DOC + "\nReports read orders from the table (ADR-0007).\n")
git(r, "switch", "-q", "-c", "feature")
commit(r, {"lib/orders.ex": "x\n"}, "More reports")
check("6: a wiki ADR whose divergence the doc already cites is allowed", pr(r, body="Builds ADR-0007.") == "")

r = make_repo("s6-no-doc", adr_dir=wiki, doc=False)
git(r, "switch", "-q", "-c", "feature")
commit(r, {"lib/orders.ex": "x\n"}, "More reports")
check("5: with no doc recorded, opening a pull request is not held", pr(r, body="Builds ADR-0007.") == "")

# ------------------------------------------------------------------ round 1: how an entry and its verdict are read
r = make_repo("r1-entries")


def section(body):
    return adr("## Architecture Alignment\n\n%s\n\nBuilds: Hosted\n" % body)


why = write_adr(r, section("- `Core and extensions`: diverges from the doc."))
check("2: a divergence whose only words name the doc is refused for no why",
      "diverges from `Core and extensions` but not why" in why, why)
why = write_adr(r, section("- Diverges from `One way in and out for each body of data`."))
check("2: a divergence whose only words name the part is refused for no why",
      "but not why" in why, why)
why = write_adr(r, section("- `Core and extensions`: does not conform."))
check("2: 'does not conform' is a divergence and needs its why",
      "diverges from `Core and extensions` but not why" in why, why)
why = write_adr(r, section("- `Core and extensions`: billing plugs in.\n\nConformance tests run nightly."))
check("2: prose after the entry does not give the entry a verdict",
      "`Core and extensions` with no verdict" in why, why)

CONFORMS_NOT_DIVERGES = ("- `Core and extensions`: conforms; it does not diverge, billing plugs in through the hook.\n\n"
                         "Nothing else here diverges from the doc.")
why = write_adr(r, section(CONFORMS_NOT_DIVERGES))
check("3: 'conforms; it does not diverge' and later prose are read as conforming", why == "", why)
why = write_adr(r, adr("## Architecture Alignment\n\nBuilds:\n\n- Hosted\n\n"
                       "- `Core and extensions`: conforms, billing plugs in through the hook.\n"))
check("3: a part entry after a bulleted Builds list is read as an entry, not a build", why == "", why)
why = write_adr(r, section("- **Direction**: conforms, the core never names billing.\n  - Seams stay as they are."))
check("3: a sub-bullet naming another part does not ask that part for a verdict", why == "", why)

r = make_repo("r1-pr-conforms")
git(r, "switch", "-q", "-c", "feature")
commit(r, {"docs/adr/ADR-0007-take-orders.md": section(CONFORMS_NOT_DIVERGES)}, "Write ADR-0007")
why = pr(r)
check("6: a pull request whose ADR says it does not diverge is allowed", why == "", why)

# ------------------------------------------------------------------ round 1: the builds listed
r = make_repo("r1-builds")
ENTRY = "- `Core and extensions`: conforms, billing plugs in through the hook.\n\n"
why = write_adr(r, adr("## Architecture Alignment\n\n" + ENTRY + "Builds: none\n"))
check("2: 'Builds: none' is refused", "lists no builds" in why, why)
why = write_adr(r, adr("## Architecture Alignment\n\n" + ENTRY + "Builds: TBD\n"))
check("2: a placeholder build is refused", "lists no builds" in why, why)
why = write_adr(r, adr("## Architecture Alignment\n\n" + ENTRY + "Builds: Hosted, Cloud\n"))
check("2: a build the doc does not name is refused, listing the doc's builds",
      "`Cloud`" in why and "`Hosted`" in why and "`Self-hosted`" in why, why)
why = write_adr(r, adr("## Architecture Alignment\n\n" + ENTRY + "Builds: Hosted (core and billing), Self-hosted\n"))
check("2: builds the doc names, with words after them, are accepted", why == "", why)

# ------------------------------------------------------------------ round 1: a doc whose parts are top-level headings
FLAT_DOC = "\n\n".join("# %s\n\nThe core never names an extension." % lens for lens in (
    "Direction", "One way in and out", "Call shape", "Seams", "What each build carries",
    "Leftovers", "Tests and checks"))
r = make_repo("r1-flat-doc", base_doc=FLAT_DOC)
why = write_adr(r, adr("## Architecture Alignment\n\n- Direction: conforms, the core names no extension.\n\n"
                       "Builds: Hosted\n"))
check("1: a doc whose parts are top-level headings has parts an ADR can name", why == "", why)
why = write_adr(r, adr("## Architecture Alignment\n\nWe follow it.\n\nBuilds: Hosted\n"))
check("1: and the refusal lists them", "`Direction`" in why and "no headings yet" not in why, why)

# ------------------------------------------------------------------ round 1: an old ADR renamed or moved
r = make_repo("r1-renamed")
commit(r, {"docs/adr/ADR-0007-take-orders.md": adr()}, "an ADR from before")
git(r, "mv", "docs/adr/ADR-0007-take-orders.md", "docs/adr/ADR-0007-take-and-ship-orders.md")
code, err = stop_gate(r)
check("4: an old ADR renamed with git mv is not asked for the new section at stop", code == 0, "%s %s" % (code, err))
why = write_adr(r, adr().replace("Proposed", "Accepted"), "docs/adr/ADR-0007-take-and-ship-orders.md")
check("4: nor when it is then written under its new name", why == "", why)

r = make_repo("r1-moved")
commit(r, {"docs/adr/proposed/ADR-0007-take-orders.md": adr()}, "an ADR from before")
os.makedirs(os.path.join(r, "docs/adr/current"))
os.rename(os.path.join(r, "docs/adr/proposed/ADR-0007-take-orders.md"),
          os.path.join(r, "docs/adr/current/ADR-0007-take-orders.md"))
code, err = stop_gate(r)
check("4: an old ADR moved to another folder, unstaged, is not asked for the new section",
      code == 0, "%s %s" % (code, err))

shutil.rmtree(T, ignore_errors=True)
print()
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
