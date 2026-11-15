#!/usr/bin/env python3
"""PreToolUse gate: in a repository that opted in with ADR_DIR, refuse a new ADR short of the shape in adr_shape.py, or an Edit that removes one of its sections."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adr_shape  # noqa: E402


def refuse(reasons):
    body = "\n\n".join("- %s" % r for r in reasons)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "This ADR is missing part of its required shape. Everything below is "
                "listed at once so one editing pass answers the lot.\n\n" + body +
                "\n\nThis repository asked Masthead to hold its decision records to this "
                "shape (the ADR_DIR setting). This gate proves the sections are there, not "
                "that they are good; that part is still yours."
            ),
        }
    }))


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        where = adr_shape.folder()
        # Not opted in: no folder named, so no record is held to this shape.
        if not where:
            return
        tool = data.get("tool_name")
        ti = data.get("tool_input") or {}
        if not isinstance(ti, dict):
            return
        reasons = []

        if tool == "Write":
            path = ti.get("file_path") or ""
            content = ti.get("content") or ""
            if not adr_shape.is_adr(path, where) or not content.strip():
                return
            reasons = adr_shape.check(path, content)

        elif tool == "Edit":
            if not adr_shape.is_adr(ti.get("file_path") or "", where):
                return
            reasons = adr_shape.removed(ti.get("old_string") or "", ti.get("new_string") or "")

        elif tool == "Bash":
            # Refuse a new ADR created through the shell, since its sections cannot be read there.
            cmd = (ti.get("command") or "").replace("~/", os.path.expanduser("~") + "/")
            if where not in cmd:
                return
            for m in re.finditer(r"(?:>>?\s*|\btee\s+(?:-a\s+)?|\bcp\s+\S+\s+|\bmv\s+\S+\s+)"
                                 r"(\S*" + re.escape(where) + r"(?:[^\s/;|&'\"]+/)*[^\s/;|&'\"]+\.md)", cmd):
                target = m.group(1)
                if adr_shape.is_adr(target, where) and adr_shape.committed(target) is None:
                    reasons.append(
                        "This creates a new ADR (%s) through the shell, where its "
                        "sections cannot be read. Write it with the Write tool "
                        "instead, which is checked. Editing an ADR the repository "
                        "already carries is unaffected." % target)
                    break

        if reasons:
            refuse(reasons)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
