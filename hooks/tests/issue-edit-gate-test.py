#!/usr/bin/env python3
"""Prove issue-edit-gate.py refuses a `gh issue edit` whose new body drops a
line quoted as the user's, or adds a [NEEDS CLARIFICATION] question with no
"looked in:" part; reads one exact form (`--body-file <path>`, a real file
inside the checkout) and refuses every other way of giving the body with that
form to use; and allows every other edit (issue #21).

    python3 hooks/tests/issue-edit-gate-test.py

DENY CASES FIRST, as in test-commit-attribution-gate.py: a hook that allows
everything passes every allow row, so the refusals are proven before the
allows mean anything.

A stub `gh` on PATH answers `gh issue view` with a saved body per issue
number (21 and 22; any other reference fails as real gh would), and logs its
arguments, so no network is touched. The checkout is a throwaway git
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

OLD_22 = """## Why

Robert said "a second issue keeps its own line".
"""

STUB = r"""#!/bin/sh
echo "$*" >> "$STUB_LOG"
[ -n "$STUB_GH_FAIL" ] && { echo 'gh: not signed in' >&2; exit 4; }
case "$1 $2" in
  "issue view")
    case "$3" in
      21|*/21) printf '%s' "$STUB_OLD_BODY" ;;
      22|*/22) printf '%s' "$STUB_OLD_BODY_22" ;;
      *) echo "could not resolve to an issue: $3" >&2; exit 1 ;;
    esac ;;
esac
exit 0
"""


def run(command, tmp, old=OLD, raw=None, tool="Bash", cwd=None):
    payload = raw if raw is not None else json.dumps({
        "session_id": "test-issue-edit-gate",
        "cwd": cwd or tmp,
        "tool_name": tool,
        "tool_input": {"command": command},
    })
    env = dict(os.environ)
    env["PATH"] = os.path.join(tmp, "bin") + os.pathsep + env.get("PATH", "")
    env["STUB_OLD_BODY"] = old if old is not None else ""
    env["STUB_OLD_BODY_22"] = OLD_22
    env["STUB_GH_FAIL"] = "1" if old is None else ""
    env["STUB_LOG"] = os.path.join(tmp, "gh.log")
    result = subprocess.run(["python3", HOOK], input=payload, capture_output=True,
                            text=True, check=False, env=env, cwd=tmp)
    out = result.stdout.strip()
    if not out:
        return "allow", ""
    try:
        parsed = json.loads(out)["hookSpecificOutput"]
        return parsed["permissionDecision"], parsed.get("permissionDecisionReason", "")
    except Exception:
        return "unparseable: " + out[:70], ""


def decide(command, tmp, **extra):
    return run(command, tmp, **extra)[0]


def shell_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def main():
    tmp = tempfile.mkdtemp(prefix="issue-edit-gate-")
    os.makedirs(os.path.join(tmp, "bin"))
    os.makedirs(os.path.join(tmp, "sub"))
    stub = os.path.join(tmp, "bin", "gh")
    with open(stub, "w") as fh:
        fh.write(STUB)
    os.chmod(stub, 0o755)
    subprocess.run(["git", "init", "-q", tmp], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.name", "Robert Sfeir"], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.email", "robert@example.com"], check=True)
    outside = tempfile.mkdtemp(prefix="issue-edit-gate-outside-")

    def body(name, text, refs="21"):
        """Write a body file and return the edit command that sends it."""
        with open(os.path.join(tmp, name), "w") as fh:
            fh.write(text)
        return "gh issue edit {} --body-file {}".format(refs, name)

    drop_said = OLD.replace('Robert said "one thing should get me account statuses".', "Robert said nothing.")
    drop_bullet = OLD.replace('- "the code shouldn\'t know who to call to read and who to update"\n', "")
    drop_the_user = OLD.replace('; the user: "it\'s basic abstraction concepts"', "")
    swap_adr = OLD.replace('"No code checks a plan\'s name"', '"a plan is its settings, never its name"')
    drop_foo = OLD.replace('named "Foo"', "named Foo")
    rewrapped = OLD.replace('Robert said "one thing should get me account statuses".',
                            'Robert said "one thing should get me\naccount statuses".')
    curly = OLD.replace('"one thing should get me account statuses"', "“one thing should get me account statuses”")
    with_question = OLD.replace("None open.", "- [NEEDS CLARIFICATION: which plans show the line?]")
    bare_marker = OLD.replace("None open.", "- [NEEDS CLARIFICATION] which format?")
    half_looked = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line? looked in: ADR-0170 Decision 12, README rule 3]')
    full_looked = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line?; looked in: ADR-0170 Decision 12, README rule 3, Korium "sign-in status line"]')
    full_looked_record = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line?; looked in: no decision record names it, README rule 3, Korium "sign-in status line"]')
    linked = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which?; looked in: [ADR-0003](docs/adr/0003.md) Decision 2, README rule 3, Korium "status line text"]')
    prose_marker = OLD.replace("None open.", "No [NEEDS CLARIFICATION] lines remain.")
    with_table = OLD.replace("None open.", "| plan | shows |\n|---|---|\n| Free | yes |")
    inch = OLD.replace("None open.", '- The sign-in page shows a 27" banner today.\n'
                       '- Robert said "keep the banner under the title".\n'
                       '- Robert said "show the plan name in bold".')
    inch_reworded = inch.replace('"keep the banner under the title"', '"move the banner"')
    inch_first_bullet = inch.replace('27" banner today', 'the banner on every page')
    heading_plain = OLD.replace("None open.", '**Robert, October 20:**\n"Ship CSV export before PDF"')
    heading_plain_dropped = heading_plain.replace('\n"Ship CSV export before PDF"', "")
    not_speaking = OLD.replace("None open.", 'The user wants "CSV export before PDF".')
    not_speaking_dropped = not_speaking.replace('The user wants "CSV export before PDF".', "Nothing.")
    short_ruling = OLD.replace("None open.", 'Robert: "Drop it".')
    answered = OLD.replace("None open.", '- [NEEDS CLARIFICATION: does the user see the line before sign-in?; looked in: ADR-0170 Decision 12, README rule 3, Korium "sign-in status line"]')
    labeled = OLD.replace("None open.", 'Given the user is signed in, When the page loads, Then they see "Your plan is active".')
    relabeled = labeled.replace('"Your plan is active"', '"Your plan is live"')
    adr_user = OLD.replace("None open.", 'ADR-0003 says "the user signs in with email only".')
    adr_user_fixed = adr_user.replace('"the user signs in with email only"', '"a person signs in with an email address"')
    old_style = OLD.replace("None open.", "- [NEEDS CLARIFICATION: old style question]")
    old_style_edited = old_style.replace('named "Foo"', "named Foo")
    long_quote = OLD.replace("None open.", 'Robert said "' + " ".join(["word"] * 60) + '".')
    cout_body = OLD.replace("None open.", "In C++ write cout << value to print.")

    with open(os.path.join(outside, "clean.md"), "w") as fh:
        fh.write(OLD)
    with open(os.path.join(tmp, "sub", "clean.md"), "w") as fh:
        fh.write(OLD)
    os.symlink(os.path.join(outside, "clean.md"), os.path.join(tmp, "link.md"))
    body("clean.md", OLD)
    body("clean-copy.md", OLD)
    body("drop", OLD)
    body("drop#said.md", drop_said)
    os.symlink(os.path.join(tmp, "clean.md"), os.path.join(tmp, "inner-link.md"))

    cases = [
        # DENY: a line quoted as the user's is gone.
        ("drops a quote on a line naming the user", body("drop-said.md", drop_said), "deny"),
        ("drops a quote bullet under the user's heading", body("drop-bullet.md", drop_bullet), "deny"),
        ("drops a quote on a line saying the user", body("drop-the-user.md", drop_the_user), "deny"),
        ("drops the quote via -F", "gh issue edit 21 -F drop-said.md", "deny"),
        ("drops the quote via --body-file=", "gh issue edit 21 --body-file=drop-said.md", "deny"),
        ("drops the quote with --repo and a URL", "gh issue edit https://github.com/kyroco/masthead/issues/21 --repo kyroco/masthead --body-file drop-said.md", "deny"),
        ("value flag before the issue number", "gh issue edit --add-label bug 21 --body-file drop-said.md", "deny"),
        ("second issue number is checked too", "gh issue edit 21 22 --body-file clean.md", "deny"),
        ("curly quotes in the old body, dropped", "gh issue edit 21 --body-file drop-said.md", "deny", {"old": curly}),
        ("wrapped quote in the old body, dropped", "gh issue edit 21 --body-file drop-said.md", "deny", {"old": rewrapped}),
        ("rewords the user's quote below a stray inch mark", body("inch-reworded.md", inch_reworded), "deny", {"old": inch}),
        ("plain quote line under the user's heading, dropped", body("heading-dropped.md", heading_plain_dropped), "deny", {"old": heading_plain}),
        ("wrapper before gh is still an edit", "command gh issue edit 21 --body-file drop-said.md", "deny"),
        ("edit inside a subshell is still an edit", "( gh issue edit 21 --body-file drop-said.md )", "deny"),
        ("edit inside bash -c is still an edit", "bash -c 'gh issue edit 21 --body-file drop-said.md'", "deny"),
        ("edit after a comment line is still an edit", "# don't forget\ngh issue edit 21 --body-file drop-said.md", "deny"),
        ("edit after a cd reads the path from the session folder", "cd sub && gh issue edit 21 --body-file drop-said.md", "deny"),
        # DENY: a question without its "looked in:" part.
        ("question without looked in", body("question.md", with_question), "deny"),
        ("bare marker used as a question", body("bare-marker.md", bare_marker), "deny"),
        ("question naming only two of the three", body("half-looked.md", half_looked), "deny"),
        ("question already on the first issue, new on the second", "gh issue edit 21 22 --body-file question.md", "deny", {"old": with_question}),
        # DENY: every other way of giving the body, with the form to use.
        ("--body on one line", "gh issue edit 21 --body 'nothing'", "deny"),
        ("--body over several lines", "gh issue edit 21 --body " + shell_quote(OLD), "deny"),
        ("-b", "gh issue edit 21 -b 'nothing'", "deny"),
        ("--body=", "gh issue edit 21 --body='nothing'", "deny"),
        ("--body with a command substitution", 'gh issue edit 21 --body "$(cat clean.md)"', "deny"),
        ("--body-file -", "gh issue edit 21 --body-file - <<'BODY'\n" + OLD + "BODY", "deny"),
        ("-F -", "cat clean.md | gh issue edit 21 -F -", "deny"),
        ("here-string", "gh issue edit 21 --body-file - <<< " + shell_quote(OLD), "deny"),
        ("heredoc on the edit line into a file flag", "gh issue edit 21 --body-file clean.md <<'X'\nX", "deny"),
        ("body from a missing file", "gh issue edit 21 --body-file does-not-exist.md", "deny"),
        ("body file written by this command", "cat > later.md <<'EOF'\n" + OLD + "EOF\ngh issue edit 21 --body-file later.md", "deny"),
        ("body file outside the checkout", "gh issue edit 21 --body-file " + os.path.join(outside, "clean.md"), "deny"),
        ("symlink to a file outside the checkout", "gh issue edit 21 --body-file link.md", "deny"),
        # DENY: a shell shape the check does not read (issue #23), each with a
        # body that would pass, so only the shape refuses it.
        ("sudo wrapper", "sudo -u me gh issue edit 21 --body-file clean.md", "deny"),
        ("env wrapper", "env -i gh issue edit 21 --body-file clean.md", "deny"),
        ("time wrapper", "time -p gh issue edit 21 --body-file clean.md", "deny"),
        ("command wrapper", "command -p gh issue edit 21 --body-file clean.md", "deny"),
        ("variable before gh", "GH_REPO=kyroco/other gh issue edit 21 --body-file clean.md", "deny"),
        ("command substitution", "x=$(gh issue edit 21 --body-file clean.md)", "deny"),
        ("backticks", "x=`gh issue edit 21 --body-file clean.md`", "deny"),
        ("eval", "eval 'gh issue edit 21 --body-file clean.md'", "deny"),
        ("xargs", "echo 21 | xargs -I{} gh issue edit {} --body-file clean.md", "deny"),
        ("shell keyword before the edit", "if true; then gh issue edit 21 --body-file clean.md; fi", "deny"),
        ("another command before the edit", "true && gh issue edit 21 --body-file clean.md", "deny"),
        ("two edits in one call", "gh issue edit 21 --body-file clean.md\ngh issue edit 22 --body-file clean.md", "deny"),
        ("short flag joined to its file", "gh issue edit 21 -Fdrop-said.md", "deny"),
        ("hash inside the file name", "gh issue edit 21 --body-file drop#said.md", "deny"),
        ("joined flag on a continued line", "gh issue edit 21 \\\n  -Fdrop-said.md", "deny"),
        ("body file on a continued line", "gh issue edit 21 \\\n  --body-file drop-said.md", "deny"),
        ("line ending in an escaped backslash is not joined", "gh issue edit 21 -F drop-said.md --title a\\\\\n  x -F clean.md", "deny"),
        ("body file after a title with a line break", "gh issue edit 21 --title 'two\nlines' --body-file drop-said.md", "deny"),
        ("file the same command rewrites", "cp drop-said.md clean-copy.md; gh issue edit 21 --body-file clean-copy.md", "deny"),
        ("cd into another folder first", "cd sub && gh issue edit 21 --body-file clean.md", "deny"),
        ("link to a file inside the checkout", "gh issue edit 21 --body-file inner-link.md", "deny"),
        ("session folder that is not a checkout", "gh issue edit 21 --body-file clean.md", "deny", {"cwd": outside}),
        ("unbalanced quote", "gh issue edit 21 --title 'half --body-file clean.md", "deny"),
        ("dot-dot path out of the checkout", "gh issue edit 21 --body-file sub/../../" + os.path.basename(outside) + "/clean.md", "deny"),
        # ALLOW: the user's lines survive; document quotes may change.
        ("same body", "gh issue edit 21 --body-file clean.md", "allow"),
        ("same body from a sub folder", "gh issue edit 21 --body-file sub/clean.md", "allow"),
        ("quote re-wrapped across lines", body("rewrapped.md", rewrapped), "allow"),
        ("quote with curly quotes", body("curly.md", curly), "allow"),
        ("body with a markdown table", body("table.md", with_table), "allow"),
        ("body mentioning <<", body("cout.md", cout_body), "allow"),
        ("swaps an ADR quote on a line without the user", body("swap-adr.md", swap_adr), "allow"),
        ("swaps an ADR quote on a line mentioning the user", body("adr-user-fixed.md", adr_user_fixed), "allow", {"old": adr_user}),
        ("drops a two-word quote", body("drop-foo.md", drop_foo), "allow"),
        ("a two-word ruling, dropped", "gh issue edit 21 --body-file clean.md", "allow", {"old": short_ruling}),
        ("a line where the user is not the speaker, dropped", body("not-speaking-dropped.md", not_speaking_dropped), "allow", {"old": not_speaking}),
        ("edits only the inch-mark line above the user's quote", body("inch-first.md", inch_first_bullet), "allow", {"old": inch}),
        ("removes an answered question naming the user", "gh issue edit 21 --body-file clean.md", "allow", {"old": answered}),
        ("relabels a scenario naming the user", body("relabeled.md", relabeled), "allow", {"old": labeled}),
        ("leaves an old-style question untouched", body("old-style-edited.md", old_style_edited), "allow", {"old": old_style}),
        ("prose naming the marker", body("prose-marker.md", prose_marker), "allow"),
        ("question with the three names", body("full-looked.md", full_looked), "allow"),
        ("question naming decision record in words", body("full-looked-record.md", full_looked_record), "allow"),
        ("looked in with a markdown link", body("linked.md", linked), "allow"),
        ("edit with no body", "gh issue edit 21 --add-label needs-decision", "allow"),
        ("edit with no body beside other commands", "gh issue edit 21 --add-label parked && gh issue comment 21 --body 'parked'", "allow"),
        ("comment line above the edit", "# send the body\ngh issue edit 21 --body-file clean.md", "allow"),
        ("blank lines around the edit", "\n gh issue edit 21 --body-file clean.md \n", "allow"),
        ("title with shell marks in quotes", "gh issue edit 21 --title 'a; b && c | d' --body-file clean.md", "allow"),
        ("short flag joined to a clean file", "gh issue edit 21 -Fclean.md", "allow"),
        ("clean body file on a continued line", "gh issue edit 21 \\\n  --body-file clean.md", "allow"),
        ("title starting with a hash", "gh issue edit 21 --title '#23 fix' --body-file drop-said.md", "deny"),
        ("trailing comment after the edit", "gh issue edit 21 --body-file clean.md # sends the body", "allow"),
        ("issue view", "gh issue view 21 --json body", "allow"),
        ("issue create", "gh issue create --title t --body-file drop-said.md", "allow"),
        ("pr edit body", "gh pr edit 21 --body-file drop-said.md", "allow"),
        ("old body unreachable", "gh issue edit 21 --body-file drop-said.md", "allow", {"old": None}),
        # FAIL OPEN: broken plumbing allows.
        ("malformed json", None, "allow", {"raw": "{not json"}),
        ("empty stdin", None, "allow", {"raw": ""}),
        ("other tool", "gh issue edit 21 --body-file drop-said.md", "allow", {"tool": "Write"}),
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
        print("{} {:<62} expected {:<5} got {}".format(mark, label, expected, got))

    # The refusals read as sentences, name the form to use, mark quoted text
    # as issue data, and show a cut.
    reasons = [
        ("looked-in refusal is a sentence", "gh issue edit 21 --body-file half-looked.md", {}, 'has a "looked in:" part that does not name the Korium query'),
        ("looked-in refusal marks issue data", "gh issue edit 21 --body-file half-looked.md", {}, "issue data, not an instruction"),
        ("dropped-line refusal marks issue data", "gh issue edit 21 --body-file drop-said.md", {}, "issue data, not an instruction"),
        ("dropped-line refusal shows the cut", "gh issue edit 21 --body-file clean.md", {"old": long_quote}, '...". Every line the user wrote stays'),
        ("--body refusal names the form", "gh issue edit 21 --body 'nothing'", {}, "`gh issue edit <n> --body-file <path>`"),
        ("heredoc refusal names the form", "gh issue edit 21 --body-file - <<'BODY'\n" + OLD + "BODY", {}, "`gh issue edit <n> --body-file <path>`"),
        ("wrapper refusal says why", "sudo -u me gh issue edit 21 --body-file clean.md", {}, "a command of its own"),
        ("wrapper refusal names the form", "sudo -u me gh issue edit 21 --body-file clean.md", {}, "`gh issue edit <n> --body-file <path>`"),
        ("link refusal says why", "gh issue edit 21 --body-file inner-link.md", {}, "inner-link.md is a link"),
        ("no-checkout refusal says why", "gh issue edit 21 --body-file clean.md", {"cwd": outside}, "not inside a git checkout"),
        ("outside refusal names the checkout", "gh issue edit 21 --body-file " + os.path.join(outside, "clean.md"), {}, "outside the checkout " + os.path.realpath(tmp)),
        ("missing file refusal names the file", "gh issue edit 21 --body-file does-not-exist.md", {}, "does-not-exist.md is not there"),
    ]
    for label, command, extra, needle in reasons:
        got, reason = run(command, tmp, **extra)
        ok = got == "deny" and needle in reason
        if not ok:
            failures.append(label)
        print("{} {:<62} expected {:<5} got {}".format("ok  " if ok else "FAIL", label, "deny+", got if needle in reason else "no " + repr(needle[:30])))

    total = len(cases) + len(reasons)
    print()
    if failures:
        print("{} of {} cases are wrong:".format(len(failures), total))
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("all {} cases pass".format(total))


if __name__ == "__main__":
    main()
