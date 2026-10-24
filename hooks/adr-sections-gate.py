#!/usr/bin/env python3
"""PreToolUse gate: refuse an ADR Write missing Principle Alignment, Acceptance Criteria (two or more) or You Are Done When, or an Edit that removes one."""
import json
import os
import re
import sys

REQUIRED = [
    ("Principle Alignment",
     "cite each implicated principle with a conforms / diverges / N/A verdict, "
     "in the canonical form `- P1 (tenant isolation): conforms -- new table declared FORCE RLS`"),
    ("Acceptance Criteria",
     "the checkable half of the ADR: numbered AC-1, AC-2, one assertion each, "
     "observable from outside, with the failure paths and the named boundary values, "
     "written so a reviewer who never saw the code can check every line"),
    ("You Are Done When",
     "the closing checklist: every AC with the evidence that demonstrates it, the "
     "gates that must be green by name, and what is explicitly not done in this unit"),
]

MIN_CRITERIA = 2


def _tracked_in_git(path):
    """Return True when HEAD already carries this ADR; any doubt returns False."""
    if not path:
        return False
    try:
        import subprocess
        # Ask HEAD, not the index, whether the repository already carries this ADR.
        full = os.path.abspath(path)
        d = os.path.dirname(full) or "."
        top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if top.returncode != 0:
            return False
        rel = os.path.relpath(full, top.stdout.strip())
        r = subprocess.run(["git", "-C", d, "cat-file", "-e", "HEAD:" + rel],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def adr_dir():
    """Return the repo's ADR folder from ADR_DIR (else docs/adr), ending in a slash."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from project_fact import fact
        value = fact("ADR_DIR", "docs/adr")
    except Exception:
        value = "docs/adr"
    value = os.path.expanduser(value).replace("\\", "/")
    if value.startswith("/"):
        return value.rstrip("/") + "/"
    return value.strip("/") + "/"


def is_adr(path):
    if not path:
        return False
    norm = os.path.expanduser(path).replace("\\", "/")
    return adr_dir() in norm and os.path.basename(norm).upper().startswith("ADR-")


def has_heading(text, title):
    return re.search(r"(?mi)^\s{0,3}#{2,3}\s+%s\s*$" % re.escape(title), text) is not None


def criteria_count(text):
    """Numbered criteria inside the Acceptance Criteria section only."""
    m = re.search(r"(?mi)^\s{0,3}#{2,3}\s+Acceptance Criteria\s*$", text)
    if not m:
        return 0
    rest = text[m.end():]
    nxt = re.search(r"(?m)^\s{0,3}#{2,3}\s+\S", rest)
    body = rest[:nxt.start()] if nxt else rest
    return len(re.findall(r"(?mi)^\s*[-*]?\s*`?AC-\d+", body))


def refuse(reasons):
    body = "\n\n".join("- %s" % r for r in reasons)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "This ADR is missing part of its required shape. Everything below is "
                "listed at once so one editing pass answers the lot.\n\n" + body +
                "\n\nThese are the sections a reader who did not write the code needs in "
                "order to check the decision landed. See the template in the repo's ADR "
                "folder. This gate proves the sections are there, not "
                "that they are good; that part is still yours."
            ),
        }
    }))


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        tool = data.get("tool_name")
        ti = data.get("tool_input") or {}
        if not isinstance(ti, dict):
            return
        # Judge Write and Edit on file_path and Bash on its command.
        if tool in ("Write", "Edit"):
            if not is_adr(ti.get("file_path") or ""):
                return
        elif tool == "Bash":
            # A command names the wiki clone as ~/..., so read it with ~ expanded.
            ti = dict(ti, command=(ti.get("command") or "").replace("~/", os.path.expanduser("~") + "/"))
            if adr_dir() not in ti["command"]:
                return
        else:
            return

        reasons = []

        if tool == "Write":
            content = ti.get("content") or ""
            if not content.strip():
                return
            # Grandfather an ADR already in git history; only a new ADR needs the sections.
            if _tracked_in_git(ti.get("file_path") or ""):
                return
            for title, want in REQUIRED:
                if not has_heading(content, title):
                    reasons.append("`## %s` is absent. Add it: %s." % (title, want))
            if has_heading(content, "Acceptance Criteria"):
                n = criteria_count(content)
                if n < MIN_CRITERIA:
                    reasons.append(
                        "`## Acceptance Criteria` carries %d numbered criteria and needs at "
                        "least %d. Number them AC-1, AC-2, one assertion each. A decision "
                        "worth an ADR changes more than one observable thing, and the "
                        "failure paths are criteria too." % (n, MIN_CRITERIA))

        elif tool == "Bash":
            # Refuse a new ADR created through the shell, since its sections cannot be read there.
            cmd = ti.get("command") or ""
            for m in re.finditer(r"(?:>>?\s*|\btee\s+(?:-a\s+)?|\bcp\s+\S+\s+|\bmv\s+\S+\s+)"
                                 r"(\S*" + re.escape(adr_dir()) + r"(?:[^\s/;|&'\"]+/)*ADR-[^\s;|&'\"]+\.md)", cmd):
                target = m.group(1)
                if not _tracked_in_git(target):
                    reasons.append(
                        "This creates a new ADR (%s) through the shell, where its "
                        "sections cannot be read. Write it with the Write tool "
                        "instead, which is checked. Editing an ADR the repository "
                        "already carries is unaffected." % target)
                    break

        elif tool == "Edit":
            old = ti.get("old_string") or ""
            new = ti.get("new_string") or ""
            for title, want in REQUIRED:
                if has_heading(old, title) and not has_heading(new, title):
                    reasons.append(
                        "This edit removes the `## %s` heading. If the section is being "
                        "rewritten, keep the heading in the replacement. If the decision "
                        "genuinely no longer needs it, that is the user's call, not an edit's."
                        % title)

        if reasons:
            refuse(reasons)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
