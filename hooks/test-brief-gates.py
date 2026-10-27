#!/usr/bin/env python3
"""Prove gate-verify-brief refuses and allows what it must.

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

Claims: the repository's security conventions in docs/conventions/security.md,
and the six in your agent file.
"""


def re_verify(n):
    return """Re-verify: round {}, claims 2 and 3
Verify git diff def456..0a1b2c, the fix commits only.

Claims:
- claim 2: nothing is written when the save is refused
- claim 3: the limit sentence names the reset month
""".format(n)


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
    ("the author's claims, in those words", "verifier", AUTHOR_CLAIMS, None, "allow"),
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
    ("another session's re-verifies do not count", "verifier", re_verify(1),
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
    ("a Claims: line as a numbered item", "verifier", LISTED_CLAIMS, None, "allow"),
    ("HELD Claims: none is no list", "verifier", NONE_CLAIMS, None, "deny"),
    ("HELD none under Claims: is no list", "verifier", NONE_UNDER_CLAIMS, None, "deny"),
    ("HELD a bold Claims: none is no list", "verifier", BOLD_NONE, None, "deny"),
    ("HELD Claims: none followed by more text is no list", "verifier", NONE_THEN_MORE, None, "deny"),
    ("HELD none under Claims: followed by more text is no list", "verifier", NONE_UNDER_THEN_MORE, None, "deny"),
    ("HELD Not proven under an empty Claims: is no list", "verifier", NOT_PROVEN_ONLY, None, "deny"),
    ("a bold Claims: with a list under it", "verifier", BOLD_LIST, None, "allow"),
    # Two markdown prefixes at once (a quoted list item).
    ("HELD a third round as a quoted list item is still refused", "verifier", re_verify_quoted(3),
     [(SESSION8, "re-verify round 1"), (SESSION8, "re-verify round 2")], "deny"),
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


def main():
    failures = 0
    for label, subagent, prompt, rows, expected in CASES:
        actual, reason = decision_for(subagent, prompt, rows)
        ok = actual == expected
        failures += 0 if ok else 1
        print("{:4}  {:<52} expected {:<5} got {}".format("ok" if ok else "FAIL", label, expected, actual))
        if label.startswith("HELD no claims and a third round"):
            both = "claims" in reason.lower() and "round" in reason.lower()
            failures += 0 if both else 1
            print("{:4}  {:<52} one decision carries both reasons".format("ok" if both else "FAIL", ""))

    actual, _ = decision_for("verifier", THIN, None, {"MASTHEAD_BRIEF_GATE": "off"})
    ok = actual == "allow"
    failures += 0 if ok else 1
    print("{:4}  {:<52} expected allow got {}".format("ok" if ok else "FAIL", "the operator's brief escape", actual))

    print("")
    if failures:
        print("{} cases wrong".format(failures))
        return 1
    print("all {} cases correct".format(len(CASES) + 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
