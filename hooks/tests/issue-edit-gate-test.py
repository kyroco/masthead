#!/usr/bin/env python3
"""Prove issue-edit-gate.py refuses a `gh issue edit` whose new body drops a
line quoted as the user's, or carries a [NEEDS CLARIFICATION] question with no
"looked in:" part, and allows every other edit (issue #21).

    python3 hooks/tests/issue-edit-gate-test.py

DENY CASES FIRST, as in test-commit-attribution-gate.py: a hook that allows
everything passes every allow row, so the refusals are proven before the
allows mean anything.

A stub `gh` on PATH answers `gh issue view` with the old body held in
STUB_OLD_BODY, so no network is touched. The checkout is a throwaway git
repository whose user.name is "Robert Sfeir", so the user's first name is
Robert.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.environ.get("ISSUE_EDIT_GATE") or os.path.join(os.path.dirname(HERE), "issue-edit-gate.py")

OLD = """## Why

Nothing shows the status today. Robert said "one thing should get me account statuses".

**Robert, October 20, 2026:**
- "the code shouldn't know who to call to read and who to update"

## Scenarios

- Given an account, When it is read, Then one call answers. (ADR-0170 Decision 16: "nothing else reads or writes those columns"; the user: "it's basic abstraction concepts".)
- Given a plan named "Foo", When asked, Then it behaves as Small Business. (ADR-0170 Decision 1: "No code checks a plan's name".)

## Out of scope

- Billing: #3372.

## Questions

None open.
"""


def edit_cmd(body, number="21", extra=""):
    return "gh issue edit {} {}--body-file - <<'BODY'\n{}BODY".format(number, extra, body)


def decide(command, tmp, old=OLD, raw=None, tool="Bash"):
    payload = raw if raw is not None else json.dumps({
        "session_id": "test-issue-edit-gate",
        "cwd": tmp,
        "tool_name": tool,
        "tool_input": {"command": command},
    })
    env = dict(os.environ)
    env["PATH"] = os.path.join(tmp, "bin") + os.pathsep + env.get("PATH", "")
    env["STUB_OLD_BODY"] = old if old is not None else ""
    env["STUB_GH_FAIL"] = "1" if old is None else ""
    result = subprocess.run(["python3", HOOK], input=payload, capture_output=True,
                            text=True, check=False, env=env, cwd=tmp)
    out = result.stdout.strip()
    if not out:
        return "allow"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "unparseable: " + out[:70]


def main():
    tmp = tempfile.mkdtemp(prefix="issue-edit-gate-")
    os.makedirs(os.path.join(tmp, "bin"))
    stub = os.path.join(tmp, "bin", "gh")
    with open(stub, "w") as fh:
        fh.write("#!/bin/sh\n"
                 "[ -n \"$STUB_GH_FAIL\" ] && { echo 'gh: not signed in' >&2; exit 4; }\n"
                 "case \"$*\" in *' view '*) printf '%s' \"$STUB_OLD_BODY\" ;; esac\n"
                 "exit 0\n")
    os.chmod(stub, 0o755)
    subprocess.run(["git", "init", "-q", tmp], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.name", "Robert Sfeir"], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.email", "robert@example.com"], check=True)

    drop_said = OLD.replace('Robert said "one thing should get me account statuses".', "Robert said nothing.")
    drop_bullet = OLD.replace('- "the code shouldn\'t know who to call to read and who to update"\n', "")
    drop_the_user = OLD.replace('; the user: "it\'s basic abstraction concepts"', "")
    swap_adr = OLD.replace('"nothing else reads or writes those columns"', '"one module is the only way in and out"')
    drop_foo = OLD.replace('named "Foo"', "named Foo")
    rewrapped = OLD.replace('Robert said "one thing should get me account statuses".',
                            'Robert said "one thing should get me\naccount statuses".')
    curly = OLD.replace('"one thing should get me account statuses"', "“one thing should get me account statuses”")
    with_question = OLD.replace("None open.", "- [NEEDS CLARIFICATION: which plans show the line?]")
    half_looked = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line? looked in: ADR-0170 Decision 12, README rule 3]')
    full_looked = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line?; looked in: ADR-0170 Decision 12, README rule 3, Korium "sign-in status line"]')
    full_looked_record = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line?; looked in: no decision record names it, README rule 3, Korium "sign-in status line"]')

    body_file = os.path.join(tmp, "body.md")
    with open(body_file, "w") as fh:
        fh.write(drop_said)
    clean_file = os.path.join(tmp, "clean.md")
    with open(clean_file, "w") as fh:
        fh.write(OLD)

    cases = [
        # DENY: a line quoted as the user's is gone.
        ("drops a quote on a line naming the user", edit_cmd(drop_said), "deny"),
        ("drops a quote bullet under the user's heading", edit_cmd(drop_bullet), "deny"),
        ("drops a quote on a line saying the user", edit_cmd(drop_the_user), "deny"),
        ("drops the quote via --body-file path", "gh issue edit 21 --body-file body.md", "deny"),
        ("drops the quote via -F path", "gh issue edit 21 -F body.md", "deny"),
        ("drops the quote via --body", 'gh issue edit 21 --body "' + drop_said.replace('"', '\\"') + '"', "deny"),
        ("drops the quote with --repo and a URL", edit_cmd(drop_said, number="https://github.com/kyroco/masthead/issues/21", extra="--repo kyroco/masthead "), "deny"),
        # DENY: a question without its "looked in:" part.
        ("question without looked in", edit_cmd(with_question), "deny"),
        ("question naming only two of the three", edit_cmd(half_looked), "deny"),
        # DENY: a body the check cannot read.
        ("body piped from a command", "cat new.md | gh issue edit 21 --body-file -", "deny"),
        ("body from a missing file", "gh issue edit 21 --body-file does-not-exist.md", "deny"),
        # ALLOW: the user's lines survive; document quotes may change.
        ("same body", edit_cmd(OLD), "allow"),
        ("same body from a file", "gh issue edit 21 --body-file clean.md", "allow"),
        ("quote re-wrapped across lines", edit_cmd(rewrapped), "allow"),
        ("quote with curly quotes", edit_cmd(curly), "allow"),
        ("swaps an ADR quote on a line without the user", edit_cmd(swap_adr), "allow"),
        ("drops a two-word quote", edit_cmd(drop_foo), "allow"),
        ("question with the three names", edit_cmd(full_looked), "allow"),
        ("question naming decision record in words", edit_cmd(full_looked_record), "allow"),
        ("edit with no body", "gh issue edit 21 --add-label needs-decision", "allow"),
        ("issue view", "gh issue view 21 --json body", "allow"),
        ("issue create", "gh issue create --title t --body-file body.md", "allow"),
        ("pr edit body", "gh pr edit 21 --body-file body.md", "allow"),
        ("old body unreachable", edit_cmd(drop_said), "allow", {"old": None}),
        # FAIL OPEN: broken plumbing allows.
        ("malformed json", None, "allow", {"raw": "{not json"}),
        ("empty stdin", None, "allow", {"raw": ""}),
        ("other tool", edit_cmd(drop_said), "allow", {"tool": "Write"}),
        ("no command field", None, "allow", {"raw": json.dumps({"tool_name": "Bash", "tool_input": {}})}),
    ]

    failures = []
    for case in cases:
        label, command, expected = case[0], case[1], case[2]
        extra = case[3] if len(case) > 3 else {}
        got = decide(command, tmp, **extra)
        mark = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures.append(label)
        print("{} {:<46} expected {:<5} got {}".format(mark, label, expected, got))

    print()
    if failures:
        print("{} of {} cases are wrong:".format(len(failures), len(cases)))
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("all {} cases pass".format(len(cases)))


if __name__ == "__main__":
    main()
