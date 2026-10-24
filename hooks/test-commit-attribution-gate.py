#!/usr/bin/env python3
"""Prove commit-attribution-gate.py refuses AI attribution in a commit message
or PR body, allows everything else, and fails open on broken plumbing.

    python3 .claude/hooks/test-commit-attribution-gate.py

DENY CASES FIRST. A hook that allows everything passes every fail-open row, so
the refusals are proven before the allows mean anything. The allow rows matter
just as much: a gate that refuses a grep for the trailer text, or a commit that
merely discusses Claude in its body, gets switched off, and a gate that is off
protects nothing.

Set COMMIT_GATE=<path> to run the suite against a different copy of the hook.
That is how the mutation proof works: mutate a copy, point the suite at it, and
the deny rows must go red.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.environ.get("COMMIT_GATE") or os.path.join(HERE, "commit-attribution-gate.py")

TRAILER = "Claude-Session: https://claude.ai/code/session_01HPDy8sWRBqXFP397evvg9S"


def decide(command, cwd=None, raw=None, tool="Bash"):
    payload = raw if raw is not None else json.dumps({
        "session_id": "test-commit-attribution-gate",
        "cwd": cwd or os.getcwd(),
        "tool_name": tool,
        "tool_input": {"command": command},
    })
    result = subprocess.run(["python3", HOOK], input=payload, capture_output=True,
                            text=True, check=False)
    out = result.stdout.strip()
    if not out:
        return "allow"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "unparseable: " + out[:70]


def main():
    tmp = tempfile.mkdtemp(prefix="commit-gate-")
    trailer_file = os.path.join(tmp, "msg.txt")
    with open(trailer_file, "w") as fh:
        fh.write("Fix the thing\n\nBody.\n\n" + TRAILER + "\n")
    clean_file = os.path.join(tmp, "clean.txt")
    with open(clean_file, "w") as fh:
        fh.write("Fix the thing\n\nBody with no attribution.\n")
    body_file = os.path.join(tmp, "body.md")
    with open(body_file, "w") as fh:
        fh.write("## What\n\nA PR body.\n\nhttps://claude.ai/code/session_01ABC\n")

    heredoc = ('git commit -m "$(cat <<\'EOF\'\nFix the thing\n\nBody.\n\n'
               + TRAILER + '\nEOF\n)"')

    cases = [
        # DENY: the shapes the rule names, in the ways a session writes them.
        ("trailer in -m", 'git commit -m "Fix\n\n' + TRAILER + '"', "deny"),
        ("trailer in heredoc", heredoc, "deny"),
        ("trailer via -F file", "git commit -F msg.txt", "deny"),
        ("trailer via --file=", "git commit --file=msg.txt", "deny"),
        ("trailer after cd chain", "cd /tmp && git commit -q -m 'x\n" + TRAILER + "'", "deny"),
        ("trailer with -C", "git -C /tmp/x commit -m 'x\n" + TRAILER + "'", "deny"),
        ("trailer on amend", "git commit --amend -m 'x\n" + TRAILER + "'", "deny"),
        ("trailer with env prefix", "GIT_AUTHOR_DATE=now git commit -m 'x\n" + TRAILER + "'", "deny"),
        ("co-author claude", 'git commit -m "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"', "deny"),
        ("co-author codex", 'git commit -m "x\n\nCo-authored-by: Codex <bot@openai.com>"', "deny"),
        ("generated with footer", 'git commit -m "x\n\nGenerated with Claude Code"', "deny"),
        ("bare session link", 'git commit -m "x\n\nhttps://claude.ai/code/session_01ABC"', "deny"),
        ("pr create body link", 'gh pr create --title t --body "b\n\nhttps://claude.ai/code/session_01ABC"', "deny"),
        ("pr create body-file link", "gh pr create --title t --body-file body.md", "deny"),
        ("pr create -F link", "gh pr create -t t -F body.md", "deny"),
        ("pr edit body trailer", 'gh pr edit 12 --body "b\n' + TRAILER + '"', "deny"),
        ("just pr --fill with body link", 'gh pr create --fill && gh pr edit --body "x\n' + TRAILER + '"', "deny"),
        # ALLOW: ordinary authoring, and every non-authoring mention of the words.
        ("clean -m", 'git commit -m "Fix the thing"', "allow"),
        ("clean -F file", "git commit -F clean.txt", "allow"),
        ("human co-author", 'git commit -m "x\n\nCo-Authored-By: Dana Ruiz <dana@example.com>"', "allow"),
        ("body discusses claude", 'git commit -m "Teach the Claude Code hook to read the session cwd"', "allow"),
        ("grep for the trailer", "grep -rn 'Claude-Session:' .claude/hooks", "allow"),
        ("log search for trailer", "git log --grep='Claude-Session' --oneline", "allow"),
        ("test of this file", "python3 .claude/hooks/test-commit-attribution-gate.py", "allow"),
        ("echo with trailer", "echo '" + TRAILER + "'", "allow"),
        ("pr view", "gh pr view 12 --json body", "allow"),
        ("pr create clean", 'gh pr create --fill --label no-changelog', "allow"),
        ("commit word inside path", "cat notes/commit-guide.txt", "allow"),
        ("missing -F file", "git commit -F does-not-exist.txt", "allow"),
        # FAIL OPEN: broken plumbing allows.
        ("malformed json", None, "allow", {"raw": "{not json"}),
        ("empty stdin", None, "allow", {"raw": ""}),
        ("other tool", "git commit -m '" + TRAILER + "'", "allow", {"tool": "Write"}),
        ("no command field", None, "allow", {"raw": json.dumps({"tool_name": "Bash", "tool_input": {}})}),
    ]

    failures = []
    for case in cases:
        label, command, expected = case[0], case[1], case[2]
        extra = case[3] if len(case) > 3 else {}
        got = decide(command, cwd=tmp, **extra)
        mark = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures.append(label)
        print("{} {:<34} expected {:<5} got {}".format(mark, label, expected, got))

    print()
    if failures:
        print("{} of {} cases are wrong:".format(len(failures), len(cases)))
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("all {} cases pass".format(len(cases)))


if __name__ == "__main__":
    main()
