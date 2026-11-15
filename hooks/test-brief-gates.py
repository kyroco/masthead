#!/usr/bin/env python3
"""Prove gate-verify-brief refuses and allows what it must.

THE FORM IS EXACT ON PURPOSE (the foreman's ruling on fix check 2 of issue
#20): the gate reads a line that is exactly "Claims:" at column zero, whose
next non-blank line is a "- " bullet of at least four words, and a line that
begins "Re-verify: round N" at column zero. Any other spelling of either label
(a marker before it, a bold label, a numbered item, "What the author claims:",
a round with no number) is refused with the exact form to use. A variant the
gate does not read is not a bug; it is the design.

    python3 hooks/test-brief-gates.py

WHY THIS FILE EXISTS. Until October 27, 2026 four brief checks read every
dispatch (a Korium line, a fix's evidence, a reviewer's claims and seam, an
impossibility's owner). They refused four honest issue-filing briefs in one
day and were replaced by one check (masthead issue #20): a brief to the
verifier or the security reviewer carries a claims list, and a change gets at
most two re-verify rounds, counted from the dispatch log, never from the
number the brief writes.

READ THIS BEFORE ADDING A CASE. The hook exits 0 whether it allows or denies; a
denial is JSON on stdout. A test that keys on the exit code passes every case
and proves nothing. Read the decision, never the status.

Labels:

  HELD   must stay refused. These are the reason the check exists.
  SPOOF  a brief that writes a smaller round number than the log shows. The
         log decides, so it is refused.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engram-protocol.sh")
SESSION = "test-brief-gates"
SESSION8 = SESSION[:8]

CLAIMS = """read_only: true
This is a verification; you change no code.

Scenario: Given a saved note, When the plan limit is reached, Then the save is refused with the limit sentence.
Verify git diff abc123..def456.

Claims:
- the refusal sentence names the month the limit resets
- nothing is written when the save is refused
Not proven: the refusal under two saves at once.
"""

AUTHOR_CLAIMS = """Verify git diff abc123..def456 for the scenario above.

What the author claims: the save is refused and nothing is written.
What the author did not prove: two saves at once.
It leans on Accounts.Plan, which is unchanged.
"""

THIN = """Verify this diff and report what you find.
"""

EMPTY_CLAIMS = """Verify git diff abc123..def456.

Claims:

"""

SECURITY = """Verify git diff abc123..def456 for the ways it can be attacked.

Claims:
- the repository's security conventions in docs/conventions/security.md hold
- the six conventions in your agent file hold
"""

INLINE_CLAIMS = """Verify git diff abc123..def456.

Claims: the refusal sentence names the month the limit resets
"""

SHORT_BULLET = """Verify git diff abc123..def456.

Claims:
- limit sentence true
"""

FOUR_WORD_BULLET = """Verify git diff abc123..def456.

Claims:
- limit sentence is true
"""

BOLD_LABEL_COLON_OUTSIDE = """Verify git diff abc123..def456.

**Claims**:
- the refusal sentence names the month the limit resets
"""

SECOND_CLAIMS_LINE = """Verify git diff abc123..def456.

Claims: none

Claims:
- the refusal sentence names the month the limit resets
"""

ROUND_WITHOUT_NUMBER = """Re-verify: claims 2 and 3
Verify git diff def456..0a1b2c, the fix commits only.

Claims:
- nothing is written when the save is refused
"""

BOLD_REVERIFY = """**Re-verify**: round 1, claims 2 and 3
Verify git diff def456..0a1b2c, the fix commits only.

Claims:
- nothing is written when the save is refused
"""


def re_verify(n):
    return """Re-verify: round {}, claims 2 and 3
Verify git diff def456..0a1b2c, the fix commits only.

Claims:
- claim 2: nothing is written when the save is refused
- claim 3: the limit sentence names the reset month
""".format(n)


def re_verify_extra(name):
    return """Re-verify: extra {}, a saved file is no longer cut short
Verify git diff def456..0a1b2c, the extra's fix commits only.

Claims:
- a save that fails halfway leaves the old file whole
""".format(name)


NO_CLAIMS_THIRD_ROUND = """Re-verify: round 3
Verify the fix commits.
"""


def log_rows(rows):
    """Rows of a dispatches.tsv: (session8, outcome[, type[, branch]]) tuples.

    The temp cwd the cases run in is not a git checkout, so its branch is "-";
    a row on another branch belongs to another issue in a reused session.
    """
    lines = ["when\tsession\tagent\ttype\tmodel\toutcome\treason\tbranch"]
    for row in rows:
        session, outcome = row[0], row[1]
        kind = row[2] if len(row) > 2 else "verifier"
        branch = row[3] if len(row) > 3 else "-"
        lines.append("2026-10-27T14:00:00Z\t{}\tverify\t{}\topus (agent file)\t{}\t(no Model-choice line)\t{}".format(session, kind, outcome, branch))
    return "\n".join(lines) + "\n"


LISTED_CLAIMS = """Verify git diff abc123..def456.

1. Claims:
- the refusal sentence names the month the limit resets
"""

NONE_CLAIMS = """Verify git diff abc123..def456.

Claims: none
"""

NONE_UNDER_CLAIMS = """Verify git diff abc123..def456.

Claims:
none
"""

BOLD_NONE = """Verify git diff abc123..def456.

**Claims:** none
"""

NONE_THEN_MORE = """Verify git diff abc123..def456.

Claims: none
Not proven: everything.
"""

NONE_UNDER_THEN_MORE = """Verify git diff abc123..def456.

Claims:
none
The diff is small.
"""

NOT_PROVEN_ONLY = """Verify git diff abc123..def456.

Claims:
Not proven: everything.
"""

BOLD_LIST = """Verify git diff abc123..def456.

**Claims:**
- the refusal sentence names the month the limit resets
"""


def re_verify_quoted(n):
    return "> - " + re_verify(n)


def re_verify_marked(n):
    return "- " + re_verify(n)


# (label, subagent_type, prompt, log rows or None, expected decision)
CASES = [
    ("a verifier brief with a claims list", "verifier", CLAIMS, None, "allow"),
    ("HELD the author's claims in other words is not the form", "verifier", AUTHOR_CLAIMS, None, "deny"),
    ("HELD thin brief to the verifier", "verifier", THIN, None, "deny"),
    ("HELD a Claims: line with nothing under it", "verifier", EMPTY_CLAIMS, None, "deny"),
    ("a security reviewer with its claims", "security-reviewer", SECURITY, None, "allow"),
    ("HELD a security reviewer with none", "security-reviewer", THIN, None, "deny"),
    ("the same words to general-purpose are not screened", "general-purpose", THIN, None, "allow"),
    ("the same words to a fork are not screened", "fork", THIN, None, "allow"),
    ("a reader is not screened", "reader", THIN, None, "allow"),
    ("the adjudicator is not screened", "adjudicator", THIN, None, "allow"),
    # Claude Code sends a plugin's agent as <plugin>:<agent>, and adds each
    # subfolder of agents/ to the name.
    ("masthead's verifier is screened", "masthead:verifier", THIN, None, "deny"),
    ("masthead's verifier in a subfolder", "masthead:review:verifier", THIN, None, "deny"),
    ("a subfolder named for the verifier is still screened", "masthead:verifier:contract", THIN, None, "deny"),
    ("another plugin's verifier is not masthead's", "otherplugin:verifier", THIN, None, "allow"),

    # The round cap. The log decides, not the brief.
    ("round 1 with an empty log", "verifier", re_verify(1), [], "allow"),
    ("round 2 after one re-verify", "verifier", re_verify(2), [(SESSION8, "re-verify round 1")], "allow"),
    ("HELD round 3 after two re-verifies", "verifier", re_verify(3),
     [(SESSION8, "re-verify round 1"), (SESSION8, "re-verify round 2")], "deny"),
    ("SPOOF a third brief written as round 2", "verifier", re_verify(2),
     [(SESSION8, "re-verify round 1"), (SESSION8, "re-verify round 2")], "deny"),
    ("SPOOF a third brief written as round 1", "verifier", re_verify(1),
     [(SESSION8, "re-verify round 1"), (SESSION8, "re-verify round 1")], "deny"),
    # Outside a branch nothing names the change, so only this session's rows count.
    # On a branch every session's rows count (MAST-38, REPO_CASES below).
    ("outside a branch, another session's re-verifies do not count", "verifier", re_verify(1),
     [("other-se", "re-verify round 1"), ("other-se", "re-verify round 2")], "allow"),
    ("first verifications do not count", "verifier", re_verify(1),
     [(SESSION8, "dispatched"), (SESSION8, "dispatched"), (SESSION8, "dispatched")], "allow"),
    ("a refused dispatch does not count", "verifier", re_verify(1),
     [(SESSION8, "refused"), (SESSION8, "refused")], "allow"),
    # The security reviewer never spends a round and is never capped: it is
    # sent only beside a verifier, after that verifier's row is written.
    ("a security reviewer in round 2, after the round-2 verifier", "security-reviewer", re_verify(2),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 1", "security-reviewer"),
      (SESSION8, "re-verify round 2", "verifier")], "allow"),
    ("HELD no claims and a third round, refused once", "verifier", NO_CLAIMS_THIRD_ROUND,
     [(SESSION8, "re-verify round 1"), (SESSION8, "re-verify round 2")], "deny"),

    # A round is one verifier, plus the security reviewer when a security
    # finding was fixed. Only the verifier's rows spend a round (bugs-1, edge-4).
    ("a security reviewer in round 1 does not spend round 2", "verifier", re_verify(2),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 1", "security-reviewer")], "allow"),
    ("an adjudicator brief with a Re-verify line does not count", "verifier", re_verify(2),
     [(SESSION8, "re-verify round 1", "adjudicator"), (SESSION8, "re-verify round 1", "verifier")], "allow"),
    ("the verifier's rows count under the name Claude Code sends", "verifier", re_verify(3),
     [(SESSION8, "re-verify round 1", "masthead:verifier"), (SESSION8, "re-verify round 2", "masthead:verifier")], "deny"),
    # A reused session's next issue is on another branch and starts at zero (words-4).
    ("another branch's rounds do not count", "verifier", re_verify(1),
     [(SESSION8, "re-verify round 1", "verifier", "robert/9-last-issue"), (SESSION8, "re-verify round 2", "verifier", "robert/9-last-issue")], "allow"),
    ("this branch's rounds count", "verifier", re_verify(3),
     [(SESSION8, "re-verify round 1", "verifier", "-"), (SESSION8, "re-verify round 2", "verifier", "-")], "deny"),
    # The Re-verify line is read under the same markdown prefixes as the Claims line (bugs-3).
    ("HELD a third round as a list item is still refused", "verifier", re_verify_marked(3),
     [(SESSION8, "re-verify round 1"), (SESSION8, "re-verify round 2")], "deny"),
    # The Claims line under an ordered-list prefix, and an empty list in words (edge-3).
    ("HELD a Claims: line as a numbered item is not the form", "verifier", LISTED_CLAIMS, None, "deny"),
    ("HELD Claims: none is no list", "verifier", NONE_CLAIMS, None, "deny"),
    ("HELD none under Claims: is no list", "verifier", NONE_UNDER_CLAIMS, None, "deny"),
    ("HELD a bold Claims: none is no list", "verifier", BOLD_NONE, None, "deny"),
    ("HELD Claims: none followed by more text is no list", "verifier", NONE_THEN_MORE, None, "deny"),
    ("HELD none under Claims: followed by more text is no list", "verifier", NONE_UNDER_THEN_MORE, None, "deny"),
    ("HELD Not proven under an empty Claims: is no list", "verifier", NOT_PROVEN_ONLY, None, "deny"),
    ("HELD a bold Claims: label is not the form", "verifier", BOLD_LIST, None, "deny"),
    ("HELD a bold label with the colon outside is not the form", "verifier", BOLD_LABEL_COLON_OUTSIDE, None, "deny"),
    ("HELD claims on the Claims: line itself is not the form", "verifier", INLINE_CLAIMS, None, "deny"),
    ("HELD a first bullet of three words is no claim", "verifier", SHORT_BULLET, None, "deny"),
    ("a first bullet of four words is a claim", "verifier", FOUR_WORD_BULLET, None, "allow"),
    ("HELD the first Claims: line decides; a second one is not read", "verifier", SECOND_CLAIMS_LINE, None, "deny"),
    # A re-verify variant is refused whatever the log holds: no marker, no missing number.
    ("HELD a re-verify line with no round number is not the form", "verifier", ROUND_WITHOUT_NUMBER, [], "deny"),
    ("HELD a bold Re-verify label is not the form", "verifier", BOLD_REVERIFY, [], "deny"),
    ("HELD a re-verify line as a list item is not the form, even in round 1", "verifier", re_verify_marked(1), [], "deny"),
    # Two markdown prefixes at once (a quoted list item).
    ("HELD a third round as a quoted list item is still refused", "verifier", re_verify_quoted(3),
     [(SESSION8, "re-verify round 1"), (SESSION8, "re-verify round 2")], "deny"),
    # MAST-35 scenario 6: the architecture reviewer re-checks a fixed finding
    # inside the same cap of two rounds. A round is spent by the verifier, the
    # architecture reviewer, or both sent in it under one round number.
    ("the round-1 verifier joins the architecture re-check's round", "verifier", re_verify(1),
     [(SESSION8, "re-verify round 1", "architecture-reviewer")], "allow"),
    ("round 2 after an architecture-only round 1", "verifier", re_verify(2),
     [(SESSION8, "re-verify round 1", "architecture-reviewer")], "allow"),
    ("HELD a third round after a verifier round and an architecture round", "verifier", re_verify(3),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 2", "architecture-reviewer")], "deny"),
    ("SPOOF that third round written as round 1", "verifier", re_verify(1),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 2", "architecture-reviewer")], "deny"),
    ("HELD a third round after two architecture-only rounds", "verifier", re_verify(3),
     [(SESSION8, "re-verify round 1", "architecture-reviewer"), (SESSION8, "re-verify round 2", "architecture-reviewer")], "deny"),
    ("rounds shared by both agents count once each", "verifier", re_verify(2),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 1", "architecture-reviewer")], "allow"),
    ("HELD a third round after two shared rounds", "verifier", re_verify(3),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 1", "architecture-reviewer"),
      (SESSION8, "re-verify round 2", "architecture-reviewer"), (SESSION8, "re-verify round 2", "verifier")], "deny"),
    ("the architecture reviewer's rows count under the name Claude Code sends", "verifier", re_verify(3),
     [(SESSION8, "re-verify round 1", "masthead:architecture-reviewer"), (SESSION8, "re-verify round 2", "masthead:architecture-reviewer")], "deny"),
    ("another plugin's architecture reviewer rows do not count", "verifier", re_verify(1),
     [(SESSION8, "re-verify round 1", "otherplugin:architecture-reviewer"), (SESSION8, "re-verify round 2", "otherplugin:architecture-reviewer")], "allow"),
    ("the first architecture review does not count", "verifier", re_verify(2),
     [(SESSION8, "dispatched", "architecture-reviewer"), (SESSION8, "re-verify round 1", "verifier")], "allow"),
    # Another plugin's verifier is not masthead's; its rows do not count.
    ("another plugin's verifier rows do not count", "verifier", re_verify(1),
     [(SESSION8, "re-verify round 1", "otherplugin:verifier"), (SESSION8, "re-verify round 2", "otherplugin:verifier")], "allow"),
]


def decision_for(subagent, prompt, rows, env_extra=None):
    cwd = tempfile.mkdtemp(prefix="verify-brief-")
    try:
        if rows is not None:
            state = os.path.join(cwd, ".claude", "state")
            os.makedirs(state)
            with open(os.path.join(state, "dispatches.tsv"), "w") as fh:
                fh.write(log_rows(rows))
        payload = json.dumps({
            "session_id": SESSION,
            "cwd": cwd,
            "tool_name": "Agent",
            "tool_input": {"subagent_type": subagent, "prompt": prompt},
        })
        env = dict(os.environ)
        env.pop("MASTHEAD_BRIEF_GATE", None)
        env.pop("CLAUDE_PROJECT_DIR", None)
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            ["bash", HOOK, "gate-verify-brief"],
            input=payload, capture_output=True, text=True, check=False, env=env,
        )
    finally:
        shutil.rmtree(cwd, ignore_errors=True)

    out = result.stdout.strip()
    if not out:
        return "allow", ""
    if out.count('"hookSpecificOutput"') != 1:
        return "two decisions: " + out[:80], out
    try:
        decoded = json.loads(out)["hookSpecificOutput"]
        return decoded["permissionDecision"], decoded.get("permissionDecisionReason", "")
    except Exception:
        return "unparseable: " + out[:80], out


BRANCH = "robert/mast-38-cap"
OTHER8 = "newsess1"
FIRST_VERIFY = """Verify git diff abc123..def456.

Claims:
- the refusal sentence names the month the limit resets
"""


def repo_rows(*specs):
    """(session8, outcome, type) rows on BRANCH."""
    return [(s, o, t, BRANCH) for s, o, t in specs]


# MAST-38: the cap counts per change. A change is its branch: every session's
# rows on it count, wherever in the checkout the brief is sent from and in
# whichever folder PROJECT_STATE_DIR puts the log.
# (label, prompt, rows, where, expected): where is "top", "sub" or "statedir",
# or a dict of extra environment.
TWO_ROUNDS = repo_rows((OTHER8, "re-verify round 1", "masthead:verifier"),
                       (OTHER8, "re-verify round 2", "masthead:verifier"))
REPO_CASES = [
    ("HELD a third round from a new session on the same branch", re_verify(3), TWO_ROUNDS, "top", "deny"),
    ("HELD a third round written as round 1 from a new session", re_verify(1), TWO_ROUNDS, "top", "deny"),
    ("HELD a third round sent from a subfolder of the checkout", re_verify(3), TWO_ROUNDS, "sub", "deny"),
    ("HELD a third round, with the log where PROJECT_STATE_DIR says", re_verify(3), TWO_ROUNDS, "statedir", "deny"),
    ("round 2 from a new session after one round", re_verify(2),
     repo_rows((OTHER8, "re-verify round 1", "masthead:verifier")), "top", "allow"),
    # Scenario 3: after the adjudicator has judged a verification, another
    # verifier is a re-verify, so a brief without its Re-verify line is refused.
    ("HELD a re-verify brief with no Re-verify line, after the adjudicator", FIRST_VERIFY,
     repo_rows((OTHER8, "dispatched", "masthead:verifier"), (OTHER8, "dispatched", "masthead:adjudicator")), "top", "deny"),
    ("the first verification's verifiers, before any adjudicator", FIRST_VERIFY,
     repo_rows((OTHER8, "dispatched", "masthead:verifier"), (OTHER8, "dispatched", "masthead:verifier")), "top", "allow"),
    ("a refused adjudicator dispatch judged nothing", FIRST_VERIFY,
     repo_rows((OTHER8, "dispatched", "masthead:verifier"), (OTHER8, "refused", "masthead:adjudicator")), "top", "allow"),
    ("HELD a verifier that ran with no Re-verify line after the adjudicator counts as a round", re_verify(2),
     repo_rows((OTHER8, "dispatched", "masthead:verifier"), (OTHER8, "dispatched", "masthead:adjudicator"),
               (OTHER8, "re-verify round 1", "masthead:verifier"), (OTHER8, "dispatched", "masthead:adjudicator"),
               (OTHER8, "dispatched", "masthead:verifier")), "top", "deny"),
    # A cap a person raised in the environment that starts Claude Code.
    ("a third round under MASTHEAD_REVERIFY_CAP=3", re_verify(3), TWO_ROUNDS,
     {"MASTHEAD_REVERIFY_CAP": "3"}, "allow"),
    ("HELD a fourth round under MASTHEAD_REVERIFY_CAP=3", re_verify(4),
     TWO_ROUNDS + repo_rows((OTHER8, "re-verify round 3 (cap raised to 3)", "masthead:verifier")),
     {"MASTHEAD_REVERIFY_CAP": "3"}, "deny"),
    ("HELD a cap that is not a number is the usual two", re_verify(3), TWO_ROUNDS,
     {"MASTHEAD_REVERIFY_CAP": "lots"}, "deny"),
    ("HELD the brief's approval line does not open the cap",
     "Approved past the cap by Robert\n" + re_verify(3), TWO_ROUNDS, "top", "deny"),
    # MAST-42: an extra scored 8 or more and fixed in the PR gets one round of
    # its own, outside the two the scenario claims spend.
    ("an extra's round after a first verification", re_verify_extra("E1"),
     repo_rows((OTHER8, "dispatched", "masthead:verifier"), (OTHER8, "dispatched", "masthead:adjudicator")),
     "top", "allow"),
    ("an extra's round after both scenario rounds", re_verify_extra("E1"),
     TWO_ROUNDS + repo_rows((OTHER8, "dispatched", "masthead:adjudicator")), "top", "allow"),
    ("HELD a second round for the same extra", re_verify_extra("E1"),
     TWO_ROUNDS + repo_rows((OTHER8, "re-verify extra e1", "masthead:verifier")), "top", "deny"),
    ("HELD a second round for the same extra, spelled in other letter case", re_verify_extra("e1"),
     repo_rows((OTHER8, "re-verify extra e1", "masthead:verifier")), "top", "deny"),
    ("another extra's round after one extra had its own", re_verify_extra("E2"),
     TWO_ROUNDS + repo_rows((OTHER8, "re-verify extra e1", "masthead:verifier")), "top", "allow"),
    ("a refused extra round spent nothing", re_verify_extra("E1"),
     repo_rows((OTHER8, "refused", "masthead:verifier")), "top", "allow"),
    ("an extra's round spends no scenario round", re_verify(2),
     repo_rows((OTHER8, "re-verify round 1", "masthead:verifier"),
               (OTHER8, "re-verify extra e1", "masthead:verifier")), "top", "allow"),
    # Round 1 fixes: a name read with a trailing period is the same extra (F2),
    # and a branch gets no more extra rounds than the cap, so a made-up name
    # cannot buy rounds past it (F1).
    ("HELD a second round for the same extra, its name followed by a period",
     "Re-verify: extra E1. a saved file is no longer cut short\nVerify.\n\nClaims:\n- a save that fails halfway leaves the old file whole\n",
     repo_rows((OTHER8, "re-verify extra e1", "masthead:verifier")), "top", "deny"),
    ("HELD a third extra's round once two extras had theirs", re_verify_extra("E3"),
     TWO_ROUNDS + repo_rows((OTHER8, "re-verify extra e1", "masthead:verifier"),
                            (OTHER8, "re-verify extra e2", "masthead:verifier")), "top", "deny"),
    ("a third extra's round under MASTHEAD_REVERIFY_CAP=3", re_verify_extra("E3"),
     TWO_ROUNDS + repo_rows((OTHER8, "re-verify extra e1", "masthead:verifier"),
                            (OTHER8, "re-verify extra e2", "masthead:verifier")),
     {"MASTHEAD_REVERIFY_CAP": "3"}, "allow"),
    ("HELD an extra line with no name for the extra", "Re-verify: extra\nVerify.\n\nClaims:\n- the extra's fix keeps the saved file whole\n",
     [], "top", "deny"),
]


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull))


def repo_decision(prompt, rows, where):
    """The gate's decision in a throwaway git checkout on BRANCH."""
    root = os.path.realpath(tempfile.mkdtemp(prefix="verify-brief-repo-"))
    try:
        git("init", "-q", "-b", BRANCH, ".", cwd=root)
        os.makedirs(os.path.join(root, "app", "lib"))
        os.makedirs(os.path.join(root, ".claude"))
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("MASTHEAD_"):
                env.pop(key)
        env["CLAUDE_PROJECT_DIR"] = root
        state = os.path.join(root, ".claude", "state")
        if where == "statedir":
            with open(os.path.join(root, ".claude", "settings.json"), "w") as fh:
                json.dump({"env": {"PROJECT_STATE_DIR": ".work/state"}}, fh)
            state = os.path.join(root, ".work", "state")
        if isinstance(where, dict):
            env.update(where)
        os.makedirs(state)
        with open(os.path.join(state, "dispatches.tsv"), "w") as fh:
            fh.write(log_rows(rows))
        cwd = os.path.join(root, "app", "lib") if where == "sub" else root
        payload = json.dumps({"session_id": SESSION, "cwd": cwd, "tool_name": "Agent",
                              "tool_input": {"subagent_type": "masthead:verifier", "prompt": prompt}})
        result = subprocess.run(["bash", HOOK, "gate-verify-brief"], input=payload,
                                capture_output=True, text=True, check=False, env=env)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    out = result.stdout.strip()
    if not out:
        return "allow", ""
    try:
        decoded = json.loads(out)["hookSpecificOutput"]
        return decoded["permissionDecision"], decoded.get("permissionDecisionReason", "")
    except Exception:
        return "unparseable: " + out[:80], out


def architecture_brief(doc_line, alignment="ADR alignment:\n- \"Billing data is reached only through Billing.Accounts, which hands back an Account.\""):
    return """read_only: true
This is an architecture review; you change no code.

Issue: MAST-34.
Review git diff abc123..def456. Write your findings to .claude/state/review/findings-architecture-reviewer-mast34.json.
ADR: docs/adr/ADR-0007-billing.md
{}
{}
Principles: CLAUDE.md
Mockup: none
""".format(alignment, doc_line)


# The reviewer's brief for a batch of setup's review of existing code, filled in
# from the shape in references/dispatch-brief.md, "A review of existing code".
SWEEP_BRIEF = """read_only: true
This is an architecture review of existing code; you change no code.

Sweep: the files listed in /repo/.claude/state/architecture-review-batch-1.txt, at commit 824f48c0e7b1d2a3f4e5d6c7b8a9f0e1d2c3b4a5.
Lenses: Direction, One way in and out.
Write your findings to
.claude/state/review/findings-architecture-reviewer-sweep-1-boundaries.json (the real path).
ADR: none
ADR alignment: none, this reviews existing code against the doc
Architecture doc: {doc}
Principles: CLAUDE.md.
Mockup: none.
Who uses this: people who run Claude Code in their own repositories.

Use code_locate with repo "masthead" before reading code. Capture your
review with agent_capture and return its thought_id with your findings.
"""


# MAST-34 scenario 6: a brief to the architecture reviewer carries the ADR's
# alignment lines and the architecture doc's path, the one the project records.
# (label, subagent_type, prompt, recorded doc path or None, expected decision)
ARCHITECTURE_CASES = [
    ("an architecture brief naming the recorded doc", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md"), "docs/architecture.md", "allow"),
    ("the recorded doc by its full path", "architecture-reviewer",
     architecture_brief("Architecture doc: {root}/docs/architecture.md"), "docs/architecture.md", "allow"),
    ("masthead's architecture reviewer is screened", "masthead:architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md"), "docs/architecture.md", "allow"),
    ("HELD no architecture doc line", "architecture-reviewer",
     architecture_brief(""), "docs/architecture.md", "deny"),
    ("HELD masthead's reviewer with no doc line", "masthead:architecture-reviewer",
     architecture_brief(""), "docs/architecture.md", "deny"),
    ("HELD none when the project records a doc", "architecture-reviewer",
     architecture_brief("Architecture doc: none recorded"), "docs/architecture.md", "deny"),
    ("HELD another file than the recorded doc", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/other.md"), "docs/architecture.md", "deny"),
    ("HELD a bold doc label is not the form", "architecture-reviewer",
     architecture_brief("**Architecture doc:** docs/architecture.md"), "docs/architecture.md", "deny"),
    # Scenario 8: with no doc recorded the reviewer still runs, on the principles alone.
    ("no doc recorded, and the brief says so", "architecture-reviewer",
     architecture_brief("Architecture doc: none recorded"), None, "allow"),
    ("HELD no doc recorded, and the brief names one", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md"), None, "deny"),
    ("HELD no doc recorded, and no doc line", "architecture-reviewer",
     architecture_brief(""), None, "deny"),
    ("HELD no ADR alignment line", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md", alignment=""), "docs/architecture.md", "deny"),
    ("HELD an ADR alignment line with nothing under it", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md", alignment="ADR alignment:\n"), "docs/architecture.md", "deny"),
    ("HELD a first alignment bullet of three words", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md", alignment="ADR alignment:\n- conforms to doc"),
     "docs/architecture.md", "deny"),
    ("an issue that builds no ADR says so, with why", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md",
                        alignment="ADR alignment: none, the issue builds no ADR"), "docs/architecture.md", "allow"),
    ("HELD a bare none is no alignment", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md", alignment="ADR alignment: none"),
     "docs/architecture.md", "deny"),
    ("HELD a bold alignment label is not the form", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md",
                        alignment="**ADR alignment:**\n- \"Billing data is reached only through Billing.Accounts.\""),
     "docs/architecture.md", "deny"),
    # Round 1, fix F3: the reviewer cannot open a link, so the ADR line names a
    # path it can read, or "none".
    ("HELD an ADR given as a link", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md").replace(
         "ADR: docs/adr/ADR-0007-billing.md", "ADR: https://github.com/o/r/wiki/ADR-0007"), "docs/architecture.md", "deny"),
    ("HELD no ADR line", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md").replace(
         "ADR: docs/adr/ADR-0007-billing.md\n", ""), "docs/architecture.md", "deny"),
    ("an issue that builds no ADR names none", "architecture-reviewer",
     architecture_brief("Architecture doc: docs/architecture.md",
                        alignment="ADR alignment: none, the issue builds no ADR").replace(
         "ADR: docs/adr/ADR-0007-billing.md", "ADR: none"), "docs/architecture.md", "allow"),
    ("another plugin's architecture reviewer is not masthead's", "otherplugin:architecture-reviewer",
     THIN, "docs/architecture.md", "allow"),
    # MAST-36 scenarios 2 and 3: setup's review of existing code sends the same
    # reviewer, with the brief references/dispatch-brief.md gives, and it passes.
    ("a review of existing code names the recorded doc", "masthead:architecture-reviewer",
     SWEEP_BRIEF.format(doc="docs/architecture.md"), "docs/architecture.md", "allow"),
    ("HELD a review of existing code that says no doc when one is recorded", "masthead:architecture-reviewer",
     SWEEP_BRIEF.format(doc="none recorded"), "docs/architecture.md", "deny"),
]


def arch_re_verify(n, marker=""):
    """An architecture reviewer's re-verify brief: the fixed findings only (MAST-35 scenario 6)."""
    return marker + "Re-verify: round {}, findings arch-2\n".format(n) + architecture_brief(
        "Architecture doc: docs/architecture.md")


# (label, subagent_type, prompt, log rows, expected decision); the doc is recorded.
ARCHITECTURE_ROUND_CASES = [
    ("an architecture re-check with an empty log", "architecture-reviewer", arch_re_verify(1), [], "allow"),
    ("an architecture re-check beside the round-1 verifier", "architecture-reviewer", arch_re_verify(1),
     [(SESSION8, "re-verify round 1", "verifier")], "allow"),
    ("an architecture-only round 2", "architecture-reviewer", arch_re_verify(2),
     [(SESSION8, "re-verify round 1", "verifier")], "allow"),
    ("HELD an architecture re-check in a third round", "architecture-reviewer", arch_re_verify(3),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 2", "verifier")], "deny"),
    ("HELD a third architecture-only round", "architecture-reviewer", arch_re_verify(3),
     [(SESSION8, "re-verify round 1", "architecture-reviewer"), (SESSION8, "re-verify round 2", "architecture-reviewer")], "deny"),
    ("SPOOF a third architecture re-check written as round 1", "architecture-reviewer", arch_re_verify(1),
     [(SESSION8, "re-verify round 1", "architecture-reviewer"), (SESSION8, "re-verify round 1", "verifier"),
      (SESSION8, "re-verify round 2", "verifier"), (SESSION8, "re-verify round 2", "architecture-reviewer")], "deny"),
    ("masthead's architecture reviewer is capped too", "masthead:architecture-reviewer", arch_re_verify(3),
     [(SESSION8, "re-verify round 1", "verifier"), (SESSION8, "re-verify round 2", "verifier")], "deny"),
    ("another branch's rounds do not count", "architecture-reviewer", arch_re_verify(1),
     [(SESSION8, "re-verify round 1", "verifier", "robert/9-last-issue"), (SESSION8, "re-verify round 2", "verifier", "robert/9-last-issue")], "allow"),
    ("HELD an architecture re-verify line as a list item is not the form", "architecture-reviewer",
     arch_re_verify(1, marker="- "), [], "deny"),
    ("HELD a bold architecture Re-verify label is not the form", "architecture-reviewer",
     arch_re_verify(1).replace("Re-verify:", "**Re-verify**:", 1), [], "deny"),
]


def architecture_decision(subagent, prompt, doc, rows=None):
    """The gate's decision in a throwaway repository that records `doc` (or none)."""
    root = os.path.realpath(tempfile.mkdtemp(prefix="arch-brief-"))
    try:
        os.makedirs(os.path.join(root, ".git"))
        if rows is not None:
            os.makedirs(os.path.join(root, ".claude", "state"))
            with open(os.path.join(root, ".claude", "state", "dispatches.tsv"), "w") as fh:
                fh.write(log_rows(rows))
        os.makedirs(os.path.join(root, "docs"))
        for name in ("architecture.md", "other.md"):
            with open(os.path.join(root, "docs", name), "w") as fh:
                fh.write("# Architecture\n")
        os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
        with open(os.path.join(root, ".claude", "settings.json"), "w") as fh:
            json.dump({"env": {"ARCHITECTURE_DOC": doc}} if doc else {"env": {}}, fh)
        payload = json.dumps({
            "session_id": SESSION,
            "cwd": root,
            "tool_name": "Agent",
            "tool_input": {"subagent_type": subagent, "prompt": prompt.replace("{root}", root)},
        })
        env = dict(os.environ)
        env.pop("MASTHEAD_BRIEF_GATE", None)
        env["CLAUDE_PROJECT_DIR"] = root
        result = subprocess.run(
            ["bash", HOOK, "gate-verify-brief"],
            input=payload, capture_output=True, text=True, check=False, env=env,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
    out = result.stdout.strip()
    if not out:
        return "allow", ""
    try:
        decoded = json.loads(out)["hookSpecificOutput"]
        return decoded["permissionDecision"], decoded.get("permissionDecisionReason", "")
    except Exception:
        return "unparseable: " + out[:80], out


def main():
    failures = 0
    for label, subagent, prompt, doc, expected in ARCHITECTURE_CASES:
        actual, _ = architecture_decision(subagent, prompt, doc)
        ok = actual == expected
        failures += 0 if ok else 1
        print("{:4}  {:<52} expected {:<5} got {}".format("ok" if ok else "FAIL", label, expected, actual))

    for label, subagent, prompt, rows, expected in ARCHITECTURE_ROUND_CASES:
        actual, _ = architecture_decision(subagent, prompt, "docs/architecture.md", rows)
        ok = actual == expected
        failures += 0 if ok else 1
        print("{:4}  {:<52} expected {:<5} got {}".format("ok" if ok else "FAIL", label, expected, actual))

    # The refusal names the doc the project records, so the worker can copy it.
    _, reason = architecture_decision("architecture-reviewer", architecture_brief(""), "docs/architecture.md")
    ok = "docs/architecture.md" in reason and "Architecture doc:" in reason and "ADR alignment:' at column zero" not in reason
    failures += 0 if ok else 1
    print("{:4}  {:<52} the refusal names the recorded doc".format("ok" if ok else "FAIL", ""))

    for label, subagent, prompt, rows, expected in CASES:
        actual, reason = decision_for(subagent, prompt, rows)
        ok = actual == expected
        failures += 0 if ok else 1
        print("{:4}  {:<52} expected {:<5} got {}".format("ok" if ok else "FAIL", label, expected, actual))
        if label.startswith("HELD no claims and a third round"):
            both = "claims" in reason.lower() and "round" in reason.lower()
            failures += 0 if both else 1
            print("{:4}  {:<52} one decision carries both reasons".format("ok" if both else "FAIL", ""))

    for label, prompt, rows, where, expected in REPO_CASES:
        actual, _ = repo_decision(prompt, rows, where)
        ok = actual == expected
        failures += 0 if ok else 1
        print("{:4}  {:<52} expected {:<5} got {}".format("ok" if ok else "FAIL", label, expected, actual))

    # The cap's refusal says how a person raises it, and that the brief cannot.
    _, reason = repo_decision(re_verify(3), TWO_ROUNDS, "top")
    ok = "MASTHEAD_REVERIFY_CAP" in reason and "settings cannot" in reason
    failures += 0 if ok else 1
    print("{:4}  {:<52} the cap's refusal says how to raise it".format("ok" if ok else "FAIL", ""))

    actual, _ = decision_for("verifier", THIN, None, {"MASTHEAD_BRIEF_GATE": "off"})
    ok = actual == "allow"
    failures += 0 if ok else 1
    print("{:4}  {:<52} expected allow got {}".format("ok" if ok else "FAIL", "the operator's brief escape", actual))

    # The refusal asks for the scenario's Then lines and the customer sentences,
    # and for no claim of the author's own (Robert, 2026-11-11: "6 relates to
    # 1&2", the blind reviewer confirms the scenario's test and the bug's test).
    _, reason = decision_for("verifier", THIN, None)
    ok = "scenario's Then lines" in reason and "no claim of your own" in reason and "author claims" not in reason
    failures += 0 if ok else 1
    print("{:4}  {:<52} the refusal asks for no claim beyond the scenario".format("ok" if ok else "FAIL", ""))

    print("")
    if failures:
        print("{} cases wrong".format(failures))
        return 1
    print("all {} cases correct".format(len(CASES) + len(ARCHITECTURE_CASES) + len(ARCHITECTURE_ROUND_CASES) + len(REPO_CASES) + 5))
    return 0


if __name__ == "__main__":
    sys.exit(main())
