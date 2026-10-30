#!/usr/bin/env python3
"""Prove connector-commit-gate.py refuses a GitHub connector call that builds a
commit on GitHub from file contents, allows every other call, and fails open
on broken plumbing (issue #27).

    python3 hooks/tests/connector-commit-gate-test.py

A commit made that way never exists in the checkout, so the pre-push test
receipt hard-gate.sh checks is never asked for it. Work reaches GitHub through
git push instead. DENY CASES FIRST: a hook that allows everything passes every
allow row.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.environ.get("CONNECTOR_COMMIT_GATE") or os.path.join(os.path.dirname(HERE), "connector-commit-gate.py")


def payload(tool, **fields):
    return json.dumps({
        "session_id": "test-connector-commit-gate",
        "tool_name": tool,
        "tool_input": dict({"owner": "kyroco", "repo": "masthead", "branch": "robert/27-x"}, **fields),
    })


def run(raw, env_extra=None):
    env = dict(os.environ)
    env.pop("MASTHEAD_DONE_GATE", None)
    env.update(env_extra or {})
    result = subprocess.run(["python3", HOOK], input=raw, capture_output=True, text=True,
                            check=False, env=env)
    out = result.stdout.strip()
    if not out:
        return "allow", ""
    try:
        parsed = json.loads(out)["hookSpecificOutput"]
        return parsed["permissionDecision"], parsed.get("permissionDecisionReason", "")
    except Exception:
        return "unparseable: " + out[:70], ""


def main():
    files = [{"path": "a.py", "content": "x = 1\n"}]
    cases = [
        # DENY: every connector tool that writes a commit.
        ("push_files", payload("mcp__claude_ai_GitHub__push_files", message="m", files=files), "deny"),
        ("create_or_update_file", payload("mcp__claude_ai_GitHub__create_or_update_file",
                                          path="a.py", content="x", message="m"), "deny"),
        ("delete_file", payload("mcp__claude_ai_GitHub__delete_file", path="a.py", message="m"), "deny"),
        ("a local GitHub server's push_files", payload("mcp__github__push_files", message="m", files=files), "deny"),
        ("the GitHub plugin's push_files", payload("mcp__plugin_github_github__push_files",
                                                   message="m", files=files), "deny"),
        # ALLOW: the connector's other calls, and git itself.
        ("create_branch", payload("mcp__claude_ai_GitHub__create_branch", from_branch="main"), "allow"),
        ("get_file_contents", payload("mcp__claude_ai_GitHub__get_file_contents", path="a.py"), "allow"),
        ("create_pull_request", payload("mcp__claude_ai_GitHub__create_pull_request", title="t",
                                        head="b", base="main", body="Fixes #27"), "allow"),
        ("issue_write", payload("mcp__claude_ai_GitHub__issue_write", method="update", issue_number=27,
                                body="b"), "allow"),
        ("a tool named like one but not an MCP call", payload("push_files", message="m"), "allow"),
        ("git push in Bash", json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}}), "allow"),
        # FAIL OPEN: broken plumbing allows.
        ("malformed json", "{not json", "allow"),
        ("empty stdin", "", "allow"),
    ]
    failures = []
    for label, raw, expected in cases:
        got = run(raw)[0]
        if got != expected:
            failures.append(label)
        print("{} {:<44} expected {:<5} got {}".format("ok  " if got == expected else "FAIL", label, expected, got))

    # The refusal names git push and the receipt; the push gate's off switch turns this off too.
    got, reason = run(payload("mcp__claude_ai_GitHub__push_files", message="m", files=files))
    for label, ok in [
        ("refusal says to push with git", got == "deny" and "git push" in reason),
        ("refusal names the test receipt", got == "deny" and "receipt" in reason),
        ("MASTHEAD_DONE_GATE=off allows",
         run(payload("mcp__claude_ai_GitHub__push_files", message="m", files=files),
             {"MASTHEAD_DONE_GATE": "off"})[0] == "allow"),
    ]:
        if not ok:
            failures.append(label)
        print("{} {}".format("ok  " if ok else "FAIL", label))

    total = len(cases) + 3
    print()
    if failures:
        print("{} of {} cases are wrong:".format(len(failures), total))
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("all {} cases pass".format(total))


if __name__ == "__main__":
    main()
