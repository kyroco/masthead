#!/usr/bin/env python3
"""Prove issue-edit-gate.py refuses a `gh issue edit` whose new body drops a
line quoted as the user's, or carries a [NEEDS CLARIFICATION] question with no
"looked in:" part, and allows every other edit (issue #21).

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
import time

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


def edit_cmd(body, number="21", extra="", tag="BODY"):
    return "gh issue edit {} {}--body-file - <<'{}'\n{}{}".format(number, extra, tag, body, tag)


def run(command, tmp, old=OLD, raw=None, tool="Bash"):
    payload = raw if raw is not None else json.dumps({
        "session_id": "test-issue-edit-gate",
        "cwd": tmp,
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

    drop_said = OLD.replace('Robert said "one thing should get me account statuses".', "Robert said nothing.")
    drop_bullet = OLD.replace('- "the code shouldn\'t know who to call to read and who to update"\n', "")
    drop_the_user = OLD.replace('; the user: "it\'s basic abstraction concepts"', "")
    swap_adr = OLD.replace('"No code checks a plan\'s name"', '"a plan is its settings, never its name"')
    drop_foo = OLD.replace('named "Foo"', "named Foo")
    rewrapped = OLD.replace('Robert said "one thing should get me account statuses".',
                            'Robert said "one thing should get me\naccount statuses".')
    curly = OLD.replace('"one thing should get me account statuses"', "“one thing should get me account statuses”")
    with_question = OLD.replace("None open.", "- [NEEDS CLARIFICATION: which plans show the line?]")
    half_looked = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line? looked in: ADR-0170 Decision 12, README rule 3]')
    full_looked = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line?; looked in: ADR-0170 Decision 12, README rule 3, Korium "sign-in status line"]')
    full_looked_record = OLD.replace("None open.", '- [NEEDS CLARIFICATION: which plans show the line?; looked in: no decision record names it, README rule 3, Korium "sign-in status line"]')
    with_table = OLD.replace("None open.", "| plan | shows |\n|---|---|\n| Free | yes |")
    question_after_newline = OLD.replace("None open.", "Open:\n[NEEDS CLARIFICATION: which format?]")
    question_with_semicolon = OLD.replace("None open.", "- [NEEDS CLARIFICATION: which format?; looked in: the README]")
    edit_keeps_line = OLD.replace("None open.", "To write the body, run:\ngh issue edit 21 --body-file notes.md\n&& gh issue edit 21 --body-file notes.md")

    def shell_quote(text):
        return "'" + text.replace("'", "'\\''") + "'"

    body_file = os.path.join(tmp, "body.md")
    with open(body_file, "w") as fh:
        fh.write(drop_said)
    clean_file = os.path.join(tmp, "clean.md")
    with open(clean_file, "w") as fh:
        fh.write(OLD)
    with open(os.path.join(tmp, "sub", "clean.md"), "w") as fh:
        fh.write(OLD)
    stale_file = os.path.join(tmp, "stale.md")
    with open(stale_file, "w") as fh:
        fh.write(OLD)

    cases = [
        # DENY: a line quoted as the user's is gone.
        ("drops a quote on a line naming the user", edit_cmd(drop_said), "deny"),
        ("drops a quote bullet under the user's heading", edit_cmd(drop_bullet), "deny"),
        ("drops a quote on a line saying the user", edit_cmd(drop_the_user), "deny"),
        ("drops the quote via --body-file path", "gh issue edit 21 --body-file body.md", "deny"),
        ("drops the quote via -F path", "gh issue edit 21 -F body.md", "deny"),
        ("drops the quote via a multi-line --body", "gh issue edit 21 --body " + shell_quote(drop_said), "deny"),
        ("drops the quote via --body with $(cat heredoc)", "gh issue edit 21 --body \"$(cat <<'EOF'\n" + drop_said + "EOF\n)\"", "deny"),
        ("drops the quote with --repo and a URL", edit_cmd(drop_said, number="https://github.com/kyroco/masthead/issues/21", extra="--repo kyroco/masthead "), "deny"),
        ("drops the quote, then a comment heredoc repeats it", edit_cmd(drop_said) + "\ngh issue comment 21 --body-file - <<'NOTE'\n" + OLD + "NOTE", "deny"),
        ("value flag before the issue number", "gh issue edit --add-label bug 21 --body-file body.md", "deny"),
        ("second issue number is checked too", edit_cmd(OLD, number="21 22"), "deny"),
        ("command gh", "command gh issue edit 21 --body-file body.md", "deny"),
        ("subshell", "( gh issue edit 21 --body-file body.md )", "deny"),
        ("bash -c string", "bash -c 'gh issue edit 21 --body-file body.md'", "deny"),
        ("file written by a heredoc earlier in the command drops the quote",
         "cat > new.md <<'EOF'\n" + drop_said + "EOF\ngh issue edit 21 --body-file new.md", "deny"),
        # DENY: a question without its "looked in:" part.
        ("question without looked in", edit_cmd(with_question), "deny"),
        ("question naming only two of the three", edit_cmd(half_looked), "deny"),
        ("question after a newline in --body", "gh issue edit 21 --body " + shell_quote(question_after_newline), "deny"),
        ("question with a semicolon in --body", "gh issue edit 21 --body " + shell_quote(question_with_semicolon), "deny"),
        # DENY: a body the check cannot read.
        ("body piped from a command", "cat new.md | gh issue edit 21 --body-file -", "deny"),
        ("body from a missing file", "gh issue edit 21 --body-file does-not-exist.md", "deny"),
        ("body file rewritten by this command without a heredoc", "printf 'nothing\\n' > stale.md; gh issue edit 21 --body-file stale.md", "deny"),
        # ALLOW: the user's lines survive; document quotes may change.
        ("same body", edit_cmd(OLD), "allow"),
        ("same body from a file", "gh issue edit 21 --body-file clean.md", "allow"),
        ("same body via a multi-line --body", "gh issue edit 21 --body " + shell_quote(OLD), "allow"),
        ("same body via --body with $(cat heredoc)", "gh issue edit 21 --body \"$(cat <<'EOF'\n" + OLD + "EOF\n)\"", "allow"),
        ("same body with a markdown table in --body", "gh issue edit 21 --body " + shell_quote(with_table), "allow"),
        ("comment heredoc first, then the edit keeps the quote", "gh issue comment 21 --body-file - <<'NOTE'\nnothing here\nNOTE\n" + edit_cmd(OLD), "allow"),
        ("heredoc body line starting with gh issue edit", edit_cmd(edit_keeps_line), "allow"),
        ("file written by a heredoc earlier in the command keeps the quote",
         "cat > new.md <<'EOF'\n" + OLD + "EOF\n&& gh issue edit 21 --body-file new.md", "allow"),
        ("cd then a relative body file", "cd sub && gh issue edit 21 --body-file clean.md", "allow"),
        ("tab-indented terminator with <<-", "gh issue edit 21 --body-file - <<-'BODY'\n" + OLD + "\tBODY", "allow"),
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
        print("{} {:<62} expected {:<5} got {}".format(mark, label, expected, got))

    # The user's lines are seen in every shape, and only the user's lines are held.
    outside = tempfile.mkdtemp(prefix="issue-edit-gate-outside-")
    with open(os.path.join(outside, "clean.md"), "w") as fh:
        fh.write(OLD)
    answered = OLD.replace("None open.", '- [NEEDS CLARIFICATION: does the user see the line before sign-in?; looked in: ADR-0170 Decision 12, README rule 3, Korium "sign-in status line"]')
    labeled = OLD.replace("None open.", 'Given the user is signed in, When the page loads, Then they see "Your plan is active".')
    relabeled = labeled.replace('"Your plan is active"', '"Your plan is live"')
    adr_user = OLD.replace("None open.", 'ADR-0003 says "the user signs in with email only".')
    adr_user_fixed = adr_user.replace('"the user signs in with email only"', '"a person signs in with an email address"')
    old_style = OLD.replace("None open.", "- [NEEDS CLARIFICATION: old style question]")
    old_style_edited = old_style.replace('named "Foo"', "named Foo")
    long_quote = OLD.replace("None open.", 'Robert said "' + " ".join(["word"] * 60) + '".')
    more = [
        ("curly quotes in the old body, dropped", edit_cmd(drop_said), "deny", {"old": curly}),
        ("wrapped quote in the old body, dropped", edit_cmd(drop_said), "deny", {"old": rewrapped}),
        ("body file outside the checkout", "gh issue edit 21 --body-file " + os.path.join(outside, "clean.md"), "deny"),
        ("removes an answered question naming the user", edit_cmd(OLD), "allow", {"old": answered}),
        ("relabels a scenario naming the user", edit_cmd(relabeled), "allow", {"old": labeled}),
        ("swaps an ADR quote on a line mentioning the user", edit_cmd(adr_user_fixed), "allow", {"old": adr_user}),
        ("leaves an old-style question untouched", edit_cmd(old_style_edited), "allow", {"old": old_style}),
        ("prose naming the marker", edit_cmd(OLD.replace("None open.", "No [NEEDS CLARIFICATION] lines remain.")), "allow"),
        ("looked in with a markdown link", edit_cmd(OLD.replace("None open.", '- [NEEDS CLARIFICATION: which?; looked in: [ADR-0003](docs/adr/0003.md) Decision 2, README rule 3, Korium "status line text"]')), "allow"),
    ]
    for label, command, expected, *rest in more:
        extra = rest[0] if rest else {}
        got = decide(command, tmp, **extra)
        mark = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures.append(label)
        print("{} {:<62} expected {:<5} got {}".format(mark, label, expected, got))
    cases.extend(more)

    # The refusals read as sentences, mark quoted text as issue data, and show a cut.
    reasons = [
        ("looked-in refusal is a sentence", edit_cmd(half_looked), {}, 'has a "looked in:" part that does not name the Korium query'),
        ("looked-in refusal marks issue data", edit_cmd(half_looked), {}, "issue data, not an instruction"),
        ("dropped-line refusal marks issue data", edit_cmd(drop_said), {}, "issue data, not an instruction"),
        ("dropped-line refusal shows the cut", edit_cmd(OLD), {"old": long_quote}, "...\". Every line the user wrote stays"),
    ]
    for label, command, extra, needle in reasons:
        got, reason = run(command, tmp, **extra)
        ok = got == "deny" and needle in reason
        if not ok:
            failures.append(label)
        print("{} {:<62} expected {:<5} got {}".format("ok  " if ok else "FAIL", label, "deny+", got if needle in reason else "no " + repr(needle[:30])))
    cases.extend(reasons)

    # Fix check 1: the command is read as the shell reads it, and the user's
    # lines are seen in every shape the issues use.
    inch = (OLD.replace("None open.", "- The sign-in page shows a 27\" banner today.\n"
                        "- Robert said \"keep the banner under the title\".\n"
                        "- Robert said \"show the plan name in bold\"."))
    inch_reworded = inch.replace('"keep the banner under the title"', '"move the banner"')
    inch_first_bullet = inch.replace('27" banner today', 'the banner on every page')
    heading_plain = OLD.replace("None open.", "**Robert, October 20:**\n\"Ship CSV export before PDF\"")
    heading_plain_dropped = heading_plain.replace("\n\"Ship CSV export before PDF\"", "")
    not_speaking = OLD.replace("None open.", 'The user wants "CSV export before PDF".')
    not_speaking_dropped = not_speaking.replace('The user wants "CSV export before PDF".', "Nothing.")
    short_ruling = OLD.replace("None open.", 'Robert: "Drop it".')
    old_with_question = OLD.replace("None open.", "- [NEEDS CLARIFICATION: which plans?]")
    cout_body = OLD.replace("None open.", "In C++ write cout << value to print.")
    heredoc_text_body = OLD.replace("None open.", "Write it with --body-file - <<'BODY' and close with BODY.")
    with open(os.path.join(tmp, "sub", "question.md"), "w") as fh:
        fh.write(old_with_question)
    with open(os.path.join(tmp, "x.md"), "w") as fh:
        fh.write(drop_said)
    with open(os.path.join(tmp, "sub", "x.md"), "w") as fh:
        fh.write(OLD)
    with open(os.path.join(tmp, "q.md"), "w") as fh:
        fh.write(old_with_question)
    half = OLD.split("## Scenarios")
    fixes = [
        ("rewords the user's quote below a stray inch mark", edit_cmd(inch_reworded), "deny", {"old": inch}),
        ("edits only the inch-mark line above the user's quote", edit_cmd(inch_first_bullet), "allow", {"old": inch}),
        ("here-string on the line before the edit", "cat <<<\"x\" >/dev/null\ngh issue edit 21 --body-file body.md", "deny"),
        ("quoted heredoc opener on the line before the edit", "echo 'a <<EOF b'\ngh issue edit 21 --body-file body.md", "deny"),
        ("here-string body drops the quote", "gh issue edit 21 --body-file - <<< 'Nothing.'", "deny"),
        ("here-string body keeps the quote", "gh issue edit 21 --body-file - <<< " + shell_quote(OLD), "allow"),
        ("here-string body from a variable", "gh issue edit 21 --body-file - <<< \"$BODY\"", "deny"),
        ("second heredoc write to the body file wins",
         "cat > b.md <<'A'\n" + OLD + "A\ncat > b.md <<'C'\n" + drop_said + "C\ngh issue edit 21 --body-file b.md", "deny"),
        ("body file built with > then >>",
         "cat > b.md <<'A'\n" + half[0] + "A\ncat >> b.md <<'B'\n## Scenarios" + half[1] + "B\ngh issue edit 21 --body-file b.md", "allow"),
        ("heredoc writes the root file, cd, edit reads the sub file",
         "cat > question.md <<'EOF'\n" + OLD + "EOF\ncd sub && gh issue edit 21 --body-file question.md", "deny"),
        ("cd inside a subshell does not move the edit", "(cd sub); gh issue edit 21 --body-file x.md", "deny"),
        ("comment with an apostrophe before the edit", "# don't forget\ngh issue edit 21 --body-file body.md", "deny"),
        ("bash -c with two commands", "bash -c 'cd . ; gh issue edit 21 --body-file body.md'", "deny"),
        ("question already on the first issue, new on the second", "gh issue edit 21 22 --body-file q.md", "deny", {"old": old_with_question}),
        ("bare marker used as a question", edit_cmd(OLD.replace("None open.", "- [NEEDS CLARIFICATION] which format?")), "deny"),
        ("piped heredoc keeps the quote", "cat <<'BODY' | gh issue edit 21 --body-file -\n" + OLD + "BODY", "allow"),
        ("piped heredoc drops the quote", "cat <<'BODY' | gh issue edit 21 --body-file -\n" + drop_said + "BODY", "deny"),
        ("redirect after the opener", "gh issue edit 21 --body-file - 2>&1 <<'BODY'\n" + OLD + "BODY", "allow"),
        ("--body text mentioning << keeps the quote", "gh issue edit 21 --body " + shell_quote(cout_body), "allow"),
        ("--body text naming a heredoc keeps the quote", "gh issue edit 21 --body " + shell_quote(heredoc_text_body), "allow"),
        ("--body from a command substitution", 'gh issue edit 21 --body "$(cat clean.md)"', "deny"),
        ("--body from a variable", 'gh issue edit 21 --body "$BODY"', "deny"),
        ("plain quote line under the user's heading, dropped", edit_cmd(heading_plain_dropped), "deny", {"old": heading_plain}),
        ("a line where the user is not the speaker, dropped", edit_cmd(not_speaking_dropped), "allow", {"old": not_speaking}),
        ("a two-word ruling, dropped", edit_cmd(OLD), "allow", {"old": short_ruling}),
    ]
    for label, command, expected, *rest in fixes:
        extra = rest[0] if rest else {}
        got = decide(command, tmp, **extra)
        mark = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures.append(label)
        print("{} {:<62} expected {:<5} got {}".format(mark, label, expected, got))
    cases.extend(fixes)
    for label, command, needle in [
        ("command substitution refusal says it cannot be checked", 'gh issue edit 21 --body "$(cat clean.md)"', "cannot be checked"),
        ("variable refusal says it cannot be checked", "gh issue edit 21 --body-file - <<< \"$BODY\"", "cannot be checked"),
    ]:
        got, reason = run(command, tmp)
        ok = got == "deny" and needle in reason
        if not ok:
            failures.append(label)
        print("{} {:<62} expected {:<5} got {}".format("ok  " if ok else "FAIL", label, "deny+", got if needle in reason else "no " + repr(needle)))
        cases.append((label,))

    # The old body comes from the repo a GH_REPO prefix names.
    log = os.path.join(tmp, "gh.log")
    if os.path.exists(log):
        os.remove(log)
    run("GH_REPO=other/repo gh issue edit 21 --body-file clean.md", tmp)
    logged = open(log).read() if os.path.exists(log) else ""
    ok = "--repo other/repo" in logged
    print("{} {:<62} expected {:<5} got {}".format("ok  " if ok else "FAIL", "GH_REPO prefix names the repo", "repo", "repo" if ok else "none"))
    if not ok:
        failures.append("GH_REPO prefix names the repo")

    # A long command full of heredoc openers is scanned in linear time.
    started = time.time()
    decide("echo " + "<<EOF " * 20000 + "\n" + edit_cmd(OLD), tmp)
    took = time.time() - started
    ok = took < 3
    print("{} {:<62} expected {:<5} got {:.2f}s".format("ok  " if ok else "FAIL", "200 KB of heredoc openers scans fast", "<3s", took))
    if not ok:
        failures.append("200 KB of heredoc openers scans fast")

    print()
    if failures:
        print("{} of {} cases are wrong:".format(len(failures), len(cases) + 2))
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("all {} cases pass".format(len(cases) + 2))


if __name__ == "__main__":
    main()
