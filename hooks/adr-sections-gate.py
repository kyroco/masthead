#!/usr/bin/env python3
"""PreToolUse gate: in a repository that opted in with ADR_DIR, refuse a new ADR short of the shape in adr_shape.py, or an Edit that removes one of its sections.

Where the project also recorded an architecture doc, it refuses opening a pull request whose
ADR diverges from the doc while the pull request leaves the doc unchanged (MAST-31).
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adr_shape  # noqa: E402


SHAPE_INTRO = ("This ADR is missing part of its required shape. Everything below is "
               "listed at once so one editing pass answers the lot.")
SHAPE_OUTRO = ("This repository asked Masthead to hold its decision records to this "
               "shape (the ADR_DIR setting). This gate proves the sections are there, not "
               "that they are good; that part is still yours.")
PR_INTRO = "This pull request carries an ADR that diverges from the architecture doc, and leaves the doc as it was."
PR_OUTRO = ("A divergence changes the target shape, so the same pull request edits the "
            "architecture doc to state the new shape. Or, if the ADR should not diverge, change "
            "its Architecture Alignment entry to conforms and its design to match.")

PR_CREATE = re.compile(r"\bgh\s+pr\s+create\b")
ADR_NUMBER = re.compile(r"(?i)\bADR[-_ ]?0*(\d{1,5})\b")


def refuse(reasons, intro=SHAPE_INTRO, outro=SHAPE_OUTRO):
    body = "\n\n".join("- %s" % r for r in reasons)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": intro + "\n\n" + body + "\n\n" + outro,
        }
    }))


def git(top, *args):
    """git's output in `top`, or None when the command fails."""
    try:
        r = subprocess.run(["git", "-C", top] + list(args), capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def base_commit(top, base):
    """Where the branch left its base: the named base, else the remote's default branch."""
    names = ["origin/" + base, base] if base else []
    head = (git(top, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD") or "").strip()
    names += [n for n in (head, "origin/main", "main", "origin/master", "master") if n]
    for name in names:
        mb = (git(top, "merge-base", name, "HEAD") or "").strip()
        if mb:
            return mb
    return None


def pr_base(cmd):
    m = re.search(r"(?:--base|-B)(?:\s+|=)(\"[^\"]+\"|'[^']+'|\S+)", cmd)
    return m.group(1).strip("'\"") if m else ""


def body_file(cmd, cwd):
    """The text of a --body-file / -F the command names, or ''."""
    m = re.search(r"(?:--body-file|-F)(?:\s+|=)(\"[^\"]+\"|'[^']+'|\S+)", cmd)
    if not m:
        return ""
    path = os.path.join(cwd, os.path.expanduser(m.group(1).strip("'\"")))
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def find_by_number(where, number):
    """The record in the folder `where` (or a folder below it) whose name carries `number`."""
    for d, subs, files in os.walk(where):
        subs[:] = [x for x in subs if not x.startswith(".")]
        for name in sorted(files):
            m = re.match(r"(?i)^(?:adr[-_]?)?0*(\d+)[-_]", name)
            if m and int(m.group(1)) == number and adr_shape.NAME.match(name):
                return os.path.join(d, name)
    return None


def pr_divergences(cwd, base, pr_text, where):
    """The reasons opening this pull request is refused: a divergent ADR with the doc unchanged."""
    doc = adr_shape.architecture_doc()
    top = (git(cwd or ".", "rev-parse", "--show-toplevel") or "").strip()
    if not doc or not top:
        return []
    mb = base_commit(top, base)
    if not mb:
        return []
    changed = [l for l in (git(top, "diff", "--name-only", mb, "HEAD") or "").splitlines() if l]
    doc_rel = os.path.relpath(os.path.realpath(doc[0]), os.path.realpath(top))
    if doc_rel in changed:
        return []
    parts = adr_shape.doc_parts(adr_shape.read_doc(doc))
    reasons = []
    # An ADR that travels in the pull request: hold the divergences its base did not have.
    for rel in changed:
        if not (adr_shape.is_adr(rel, where) or adr_shape.is_adr(os.path.join(top, rel), where)):
            continue
        now = git(top, "show", "HEAD:" + rel)
        if now is None:
            continue
        new = sorted(set(adr_shape.diverging(now, parts))
                     - set(adr_shape.diverging(git(top, "show", "%s:%s" % (mb, rel)) or "", parts)))
        if new:
            reasons.append("`%s` diverges from %s of the architecture doc (%s), which this pull "
                           "request does not change." % (rel, ", ".join("`%s`" % p for p in new), doc_rel))
    # An ADR folder outside the repository (a wiki clone): the ADRs the pull request names by number.
    outside = where.startswith("/") and not (os.path.realpath(where) + "/").startswith(os.path.realpath(top) + "/")
    if outside and os.path.isdir(where):
        named = {}
        for source, text in [("the pull request's title or body", pr_text)] + [
                ("commit %s" % c[:12], git(top, "log", "-1", "--format=%B", c) or "")
                for c in (git(top, "rev-list", "%s..HEAD" % mb) or "").split()]:
            for m in ADR_NUMBER.finditer(text or ""):
                named.setdefault(int(m.group(1)), (m.group(0), source))
        cited = set(int(m.group(1)) for m in ADR_NUMBER.finditer(git(top, "show", "%s:%s" % (mb, doc_rel)) or ""))
        for number, (label, source) in sorted(named.items()):
            path = find_by_number(where, number)
            if not path or number in cited:
                continue
            try:
                with open(path) as handle:
                    text = handle.read()
            except OSError:
                continue
            apart = adr_shape.diverging(text, parts)
            if apart:
                reasons.append("%s, named in %s and found at %s, diverges from %s of the "
                               "architecture doc (%s), which this pull request does not change."
                               % (label, source, path, ", ".join("`%s`" % p for p in apart), doc_rel))
    return reasons


def main():
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        where = adr_shape.folder()
        # Not opted in: no folder named, so no record is held to this shape.
        if not where:
            return
        tool = str(data.get("tool_name") or "")
        ti = data.get("tool_input") or {}
        if not isinstance(ti, dict):
            return
        reasons = []
        cwd = data.get("cwd") or os.getcwd()

        # Opening a pull request: an ADR it carries or names may not diverge from an unchanged doc.
        if re.match(r"^mcp__.+__create_pull_request$", tool):
            text = "%s\n%s" % (ti.get("title") or "", ti.get("body") or "")
            reasons = pr_divergences(cwd, ti.get("base") or "", text, where)
            if reasons:
                refuse(reasons, PR_INTRO, PR_OUTRO)
            return
        if tool == "Bash" and PR_CREATE.search(ti.get("command") or ""):
            cmd = ti.get("command") or ""
            reasons = pr_divergences(cwd, pr_base(cmd), cmd + "\n" + body_file(cmd, cwd), where)
            if reasons:
                refuse(reasons, PR_INTRO, PR_OUTRO)
            return

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
            # A target is one shell word: quoted, or unquoted with backslash-escaped spaces, so a spaced name stays whole.
            word = r"(?:\"[^\"]*\"|'[^']*'|(?:\\.|[^\s;|&<>'\"])+)"
            for m in re.finditer(r"(?:>>?\s*|\btee\s+(?:-a\s+)?|\b(?:cp|mv)\s+" + word + r"\s+)(" + word + r")",
                                 cmd):
                target = m.group(1)
                if target[:1] in ("'", '"'):
                    target = target[1:-1]
                else:
                    target = re.sub(r"\\(.)", r"\1", target)
                if where not in target or not target.endswith(".md"):
                    continue
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
