#!/usr/bin/env python3
"""PreToolUse gate that refuses a GitHub connector call building a commit on GitHub from file contents (push_files, create_or_update_file, delete_file), so work reaches GitHub only through git push and its test receipt check (issue #27); fails open."""
import json
import os
import re
import sys

# The connector tools that write a commit, by the last part of the tool name.
COMMIT_TOOLS = re.compile(r"^mcp__.+__(push_files|create_or_update_file|delete_file)$")


def main():
    # The push gate's off switch: with it off, git push is unguarded too.
    if os.environ.get("MASTHEAD_DONE_GATE", "on").lower() in ("off", "0", "false", "no"):
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    m = COMMIT_TOOLS.match(str(data.get("tool_name") or ""))
    if not m:
        sys.exit(0)
    reason = (
        "Blocked: the GitHub connector's {} writes a commit on GitHub from file contents, so it never "
        "exists in the checkout and the pre-push test receipt hard-gate.sh checks is never asked for "
        "it. Commit with git and send it with git push, which runs that check (issue #27)."
    ).format(m.group(1))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
