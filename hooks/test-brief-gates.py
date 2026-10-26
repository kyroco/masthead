#!/usr/bin/env python3
"""Prove gate-fix-evidence and gate-wave-brief refuse and allow what they must.

    python3 .claude/hooks/test-brief-gates.py

WHY THIS FILE EXISTS. Both gates refused honest briefs on 2026-08-19 and passed
only once the operator recited the phrases they grep for. A gate you get past by
guessing the right synonym is not a gate, and the fix for that is not "grep for
more synonyms" - it is a declaration an author can make, plus tests that pin
BOTH sides, so the next widening cannot quietly turn the gate off.

READ THIS BEFORE ADDING A CASE. The hook exits 0 whether it allows or denies; a
denial is JSON on stdout. A test that keys on the exit code passes every case
and proves nothing. Read the decision, never the status.

The seam cases are not invented. The two headings in REVIEW_CLAIMS_AND_PLURAL_SEAM
and REVIEW_CLAIMS_AND_SINGULAR_SEAM are verbatim from the brief this gate refused
and then accepted on 2026-08-19, and the one word between them is the whole
defect. Both are here on purpose: a fix that made the refused wording pass while
breaking the accepted one would be a move, not a repair.

The gate-fix-evidence refusal from the same day could NOT be reproduced from the
fragments that survived, so nothing here is a test of it. What is tested is the
declaration that means an author never has to guess the phrasing again.

Every other case is a brief somebody could plausibly write. Three of them are the ones
that make the difference and are marked in their labels:

  REGRESSION  refused before this change, must pass now.
  TRAP        mentions the escape hatch without declaring it, must still be
              refused. A declaration is a line of its own near the top; if a
              mention were enough, every brief that discusses these gates would
              exempt itself, this file included.
  HELD        must stay refused. These are the reason the gates exist.
"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engram-protocol.sh")


# --- gate-fix-evidence -------------------------------------------------------

DECLARED_READ_ONLY = """read_only: true

Audit the hook wiring in .claude/settings.json against the hooks it names. I
want to know which gates have a matcher behind them and which are prose only.
Tell me what you find; I will decide what to fix and I will commit it myself.
"""

DECLARED_CODE_CHANGE_FALSE = """code_change: false

Go through the ADRs under docs/adr/ that mention tenancy and tell me which two
contradict each other. I will patch whatever you turn up.
"""

PROSE_READ_ONLY = """Audit the hook wiring in .claude/settings.json. Change nothing: I want the
list of gates, and whether each one has a matcher behind it. I will fix what
needs fixing once I have read your report.
"""

LEADING_NO_CODE_CHANGE = """No code change.

Read the ten ADRs under docs/adr/ that mention tenancy and tell me which ones
contradict each other. I will patch whatever you find.
"""

MENTIONS_DECLARATION_BUT_BUILDS = """Repair the seam check in the brief gates.

A brief whose seam paragraph says "the code your changes depend on" is refused
today because the pattern wants the singular. Repair that, and while you are in
there accept a declared field of the form read_only: true so an author has a
plain way to say what the work is. Commit it on a branch when it works.
"""

BUILD_NO_EVIDENCE = """The tenant plug drops the GUC when the request is retried, so the second
attempt runs with no tenant set. Fix it in the plug and make sure the pool
still hands back the connection. Commit on a branch, do not push.
"""

BUILD_WITH_EVIDENCE = """The tenant plug drops the GUC when the request is retried, so the second
attempt runs with no tenant set. Fix it in the plug.

Prove it with a real failure, not a stub of one: drive an actual retry through
the plug and let the query hit Postgres with no tenant set, so the test fails
the way production fails. Baseline the suite first.
"""

DOCS_ONLY = """Docs only. Rewrite the tenancy section of docs/engram/architecture.md so it
matches what with_tenant actually does. No behaviour change; nothing under
products/ is touched. Commit it.
"""



# Review briefs sent to an agent type other than reviewer or security-reviewer
# are not screened, so these rows expect allow for general-purpose.
REVIEW_OF_A_PATCH = "Review this patch and report findings."
REVIEW_OF_A_COMMIT = "Review commit abc123 and report findings."
REVIEW_MENTIONING_FIX = (
    "Review the change and report findings so the author can fix them."
)
BUILD_ORDERING_A_FIX = (
    "Fix three review findings in the extractor pool. "
    "Prove each one with the real failure, and baseline the suite first."
)

# --- gate-wave-brief ---------------------------------------------------------

_REAL_BRIEF_BODY = """Review the four setup defects on this branch.

## What I claim, and what I could not prove

I claim the four defects below are real and that I have read the code for three
of them. I did not prove whether wiring the project copy alongside the
account-level copy causes any double-denial or latency problem.

{seam_heading}

The seam that matters is `.claude/settings.json` to `.claude/hooks/*`. A rule in
CLAUDE.md is only real if a PreToolUse matcher in a settings file routes a tool
call to a hook that exits with a denial.
"""

# VERBATIM, both of them. The gate refused the first heading and passed the
# second, and that one word is the entire difference between the two briefs.
REVIEW_CLAIMS_AND_PLURAL_SEAM = _REAL_BRIEF_BODY.format(
    seam_heading="## The seam (code outside your changes that your changes depend on)")

REVIEW_CLAIMS_AND_SINGULAR_SEAM = _REAL_BRIEF_BODY.format(
    seam_heading="## The seam: unchanged code this change depends on")

REVIEW_CLAIMS_DID_NOT_PROVE = """Review this diff.

The author's position is that the drain is idempotent under replay. The author did not
prove that two workers draining the same batch converge.

Nothing outside the diff moved, but the change leans on Oban's uniqueness
guarantee, which is unchanged. Start there.
"""

# gate-fix-evidence reads review briefs too, and this is the wording that trips
# its write detector. Kept as its own fixture so the KNOWN case below cannot go
# green by accident when another fixture is reworded.
REVIEW_SAYING_PATCH = """Review the tenancy harness conversion.

What the author claims: every tenant read goes through the harness. What the
author could not prove: whether a test opening its own connection inherits it.

It leans on Accounts.Tenancy, which is unchanged. Read that, not just the patch.
"""

REVIEW_CLAIMS_NO_SEAM = """Review the tenancy harness conversion on this branch.

What the author claims: every test that asks for a tenant now goes through the
harness. What the author could not prove: whether a test that opens its own
connection still inherits the setting.

Report anything you find as a numbered list with a severity.
"""

REVIEW_NO_CLAIMS = """Review the tenancy harness conversion on this branch. Read the diff and report
what you find, worst first. The change depends on Accounts.Tenancy, which is
unchanged, so read that too.
"""

READ_ONLY_REVIEW_NO_CLAIMS = """read_only: true

Review the tenancy harness conversion. Change nothing, just tell me what you
find. It leans on Accounts.Tenancy, which is unchanged.
"""

# The brief below deliberately carries no file path. An earlier version cited a
# plausible-looking audit path as sample text, and check-doc-links.sh tried to
# resolve it and failed the build: a link checker cannot tell fixture data from
# a real pointer. Fixtures in this file must not contain repo-shaped paths.
BUILD_REPORTS_FINDINGS = """Fix the three defects listed in the audit I sent you.

Three findings are held back; they are not yours. Prove each of the rest by
driving the real failure, and report your findings
back to me when you are done: what changed, the test command, and
its actual output.
"""

BUILD_PLAIN = """Add the changelog entry for the tenancy harness work under changelog.d/ and
commit it. Prove it by running the changelog check and reading its output.
"""

THIN_BRIEF_FOR_A_NAMED_REVIEWER = """Here is the diff for the tenancy harness conversion. Grade it.
"""

# The shape of a reviewer brief refused on 2026-10-05: no read_only line, and
# "fixes" and "commit" in the body, so the write detector fired on a brief that
# went to an agent whose own file forbids editing code.
REVIEW_ON_THE_FIXES_ANGLE = """Angle: fixes. This is the last review round on this branch.

Review the diff from the previous head to the new one: two commits, one pins
the static rows, one fixes the earlier Nits. What the author claims: the new
tests pass. What the author did not verify: the full pre-push check.
"""

# The read-only agents skip the check only while the brief does not order a
# change; this one does, and says nothing of how it will be proven.
READ_ONLY_AGENT_ORDERED_TO_FIX = """Fix the two findings in the tenant plug and commit on a branch.
"""


# (label, gate, subagent_type, prompt, expected decision)
CASES = [
    # gate-fix-evidence
    ("declared read_only, audit", "gate-fix-evidence", "general-purpose",
     DECLARED_READ_ONLY, "allow"),
    ("declared code_change false", "gate-fix-evidence", "general-purpose",
     DECLARED_CODE_CHANGE_FALSE, "allow"),
    ("REGRESSION prose 'change nothing'", "gate-fix-evidence", "general-purpose",
     PROSE_READ_ONLY, "allow"),
    ("leading 'No code change.'", "gate-fix-evidence", "general-purpose",
     LEADING_NO_CODE_CHANGE, "allow"),
    ("TRAP mentions read_only, builds", "gate-fix-evidence", "general-purpose",
     MENTIONS_DECLARATION_BUT_BUILDS, "deny"),
    ("HELD build, no evidence plan", "gate-fix-evidence", "thiago",
     BUILD_NO_EVIDENCE, "deny"),
    ("build with an evidence plan", "gate-fix-evidence", "thiago",
     BUILD_WITH_EVIDENCE, "allow"),
    ("docs only", "gate-fix-evidence", "general-purpose", DOCS_ONLY, "allow"),
    ("REGRESSION reviewer brief, fixes angle", "gate-fix-evidence", "reviewer",
     REVIEW_ON_THE_FIXES_ANGLE, "allow"),
    ("security reviewer brief, no declaration", "gate-fix-evidence", "security-reviewer",
     REVIEW_SAYING_PATCH, "allow"),
    ("diagnoser brief, no declaration", "gate-fix-evidence", "diagnoser",
     REVIEW_SAYING_PATCH, "allow"),
    ("reader brief, no declaration", "gate-fix-evidence", "reader",
     REVIEW_SAYING_PATCH, "allow"),
    ("a reviewer ordered to fix still needs proof", "gate-fix-evidence", "reviewer",
     READ_ONLY_AGENT_ORDERED_TO_FIX, "deny"),
    ("the same brief to a builder is refused", "gate-fix-evidence", "general-purpose",
     REVIEW_ON_THE_FIXES_ANGLE, "deny"),

    # gate-wave-brief
    ("REGRESSION seam says 'depend on'", "gate-wave-brief", "reviewer",
     REVIEW_CLAIMS_AND_PLURAL_SEAM, "allow"),
    ("the wording it accepted before", "gate-wave-brief", "reviewer",
     REVIEW_CLAIMS_AND_SINGULAR_SEAM, "allow"),
    ("REGRESSION claims say 'did not prove'", "gate-wave-brief", "reviewer",
     REVIEW_CLAIMS_DID_NOT_PROVE, "allow"),
    ("HELD review with no seam", "gate-wave-brief", "general-purpose",
     REVIEW_CLAIMS_NO_SEAM, "allow"),
    ("HELD review with no claims", "gate-wave-brief", "general-purpose",
     REVIEW_NO_CLAIMS, "allow"),
    ("HELD read-only review, no claims", "gate-wave-brief", "general-purpose",
     READ_ONLY_REVIEW_NO_CLAIMS, "allow"),
    ("a research brief using review words", "gate-wave-brief", "reader",
     REVIEW_NO_CLAIMS, "allow"),
    ("a named reviewer with no claims", "gate-wave-brief", "reviewer",
     REVIEW_NO_CLAIMS, "deny"),
    ("a security reviewer with no seam", "gate-wave-brief", "security-reviewer",
     REVIEW_CLAIMS_NO_SEAM, "deny"),
    ("HELD thin brief, named reviewer", "gate-wave-brief", "reviewer",
     THIN_BRIEF_FOR_A_NAMED_REVIEWER, "deny"),
    ("REGRESSION build reports findings", "gate-wave-brief", "thiago",
     BUILD_REPORTS_FINDINGS, "allow"),
    ("REGRESSION review of a patch", "gate-wave-brief", "general-purpose",
     REVIEW_OF_A_PATCH, "allow"),
    ("REGRESSION review of a commit", "gate-wave-brief", "general-purpose",
     REVIEW_OF_A_COMMIT, "allow"),
    ("REGRESSION 'fix' mentioned, not ordered", "gate-wave-brief", "general-purpose",
     REVIEW_MENTIONING_FIX, "allow"),
    ("a brief that ORDERS a fix still skips", "gate-wave-brief", "thiago",
     BUILD_ORDERING_A_FIX, "allow"),
    ("build brief, no review words", "gate-wave-brief", "thiago",
     BUILD_PLAIN, "allow"),

    # WHERE THE TWO GATES MEET, stated rather than hidden.
    #
    # gate-fix-evidence reads a review brief too, and a review brief that says
    # "read them, not just the patch" trips its write detector on the word patch.
    # So an undeclared review brief is refused for having no evidence plan, which
    # is an over-fire and is the same shape of complaint that produced the
    # declaration in the first place. It is left as it is on purpose: narrowing
    # the write detector would let real build briefs through, and the remedy
    # costs one line. A review brief that declares itself passes.
    ("KNOWN review brief saying 'patch'", "gate-fix-evidence", "general-purpose",
     REVIEW_SAYING_PATCH, "deny"),
    ("declared review brief passes", "gate-fix-evidence", "general-purpose",
     READ_ONLY_REVIEW_NO_CLAIMS, "allow"),

    # PLUGIN AGENT NAMES. Claude Code sends a plugin's agent as
    # "<plugin>:<agent>", so "masthead:reviewer" must be screened and exempted
    # exactly as "reviewer" is. On 2026-10-26 gate-agent refused five
    # masthead:reviewer briefs and one masthead:adjudicator brief for having no
    # Korium line, though both are meant to get none.
    ("REGRESSION plugin reviewer, no Korium line", "gate-agent", "masthead:reviewer",
     REVIEW_CLAIMS_AND_PLURAL_SEAM, "allow"),
    ("REGRESSION plugin adjudicator, no Korium line", "gate-agent", "masthead:adjudicator",
     REVIEW_CLAIMS_AND_PLURAL_SEAM, "allow"),
    ("a builder with no Korium line is refused", "gate-agent", "general-purpose",
     BUILD_PLAIN, "deny"),
    ("REGRESSION plugin reviewer with no claims", "gate-wave-brief", "masthead:security-reviewer",
     REVIEW_NO_CLAIMS, "deny"),
    ("REGRESSION plugin diagnoser, no declaration", "gate-fix-evidence", "masthead:diagnoser",
     REVIEW_SAYING_PATCH, "allow"),
    ("REGRESSION plugin reviewer told it is impossible", "gate-brief-inference", "masthead:reviewer",
     "Review the diff. A retry is impossible here.", "allow"),
    ("another plugin's reviewer is not masthead's", "gate-wave-brief", "otherplugin:reviewer",
     REVIEW_NO_CLAIMS, "allow"),
    ("another plugin's reviewer gets no exemption", "gate-agent", "otherplugin:reviewer",
     REVIEW_CLAIMS_AND_PLURAL_SEAM, "deny"),
    # Claude Code adds each subfolder of agents/ to the name, so masthead's
    # agents are matched on the part after the last colon.
    ("masthead's reviewer in a subfolder, no Korium line", "gate-agent", "masthead:review:reviewer",
     REVIEW_CLAIMS_AND_PLURAL_SEAM, "allow"),
]


def decision_for(gate, subagent, prompt):
    payload = json.dumps({
        "session_id": "test-brief-gates",
        "tool_name": "Agent",
        "tool_input": {"subagent_type": subagent, "prompt": prompt},
    })

    # gate-agent only bites once the session's Korium search found something,
    # so its cases run against a private state folder holding one such search.
    env = dict(os.environ)
    with tempfile.TemporaryDirectory() as data:
        if gate == "gate-agent":
            session = os.path.join(data, "state", "claude-engram", "test-brief-gates")
            os.makedirs(session)
            with open(os.path.join(session, "searches.tsv"), "w") as f:
                f.write("3\tthe change under review\n")
            env["CLAUDE_PLUGIN_DATA"] = data
            env.pop("MASTHEAD_BRIEF_GATE", None)

        result = subprocess.run(
            ["bash", HOOK, gate],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    # The hook exits 0 either way. The decision is the stdout, or its absence.
    out = result.stdout.strip()
    if not out:
        return "allow"

    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "unparseable: " + out[:80]


def main():
    failures = 0

    for label, gate, subagent, prompt, expected in CASES:
        actual = decision_for(gate, subagent, prompt)
        ok = actual == expected
        failures += 0 if ok else 1
        print("{:4}  {:<20} {:<36} expected {:<5} got {}".format(
            "ok" if ok else "FAIL", gate.replace("gate-", ""), label, expected, actual))

    print("")
    if failures:
        print("{} of {} cases wrong".format(failures, len(CASES)))
        return 1

    print("all {} cases correct".format(len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
