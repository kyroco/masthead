#!/usr/bin/env python3
"""The one shape Masthead holds decision records (ADRs) to, read by both ADR gates.

A repository opts in by naming its ADR folder in the `ADR_DIR` fact, which
`/setup` writes only when the person says yes. With no folder named, `folder()`
is None and both gates stand aside, so a repository that keeps ADRs in another
format (adr-tools, MADR) is never held to this one.

Command line, for the shell gate:
    adr_shape.py folder          prints the opted-in folder, or nothing
    adr_shape.py is-adr PATH     exit 0 when PATH is a record in that folder
    adr_shape.py pick            reads paths on stdin, prints those that are records in that folder
    adr_shape.py check FILE      prints one reason per line that FILE is short of the shape
                                 (a new record: every section; a changed one: no section removed)
"""
import os
import re
import subprocess
import sys

# Each required section, with what to write in it. Both gates ask for exactly these.
SECTIONS = [
    ("Status", "one word a reader can act on: Proposed, Accepted or Superseded"),
    ("Principle Alignment",
     "each project principle the decision touches, with a conforms / diverges / N/A "
     "verdict and one clause of why"),
    ("Context", "what forces the decision, with the files or facts it rests on"),
    ("Options Considered", "the options weighed, the chosen one included"),
    ("Decision", "what was decided, in one or two plain sentences"),
    ("Rationale", "why this option over the others"),
    ("Acceptance Criteria",
     "the checkable half of the ADR: numbered AC-1, AC-2, one assertion each, "
     "observable from outside, with the failure paths and the named boundary values, "
     "written so a reviewer who never saw the code can check every line"),
    ("You Are Done When",
     "the closing checklist: every AC with the evidence that demonstrates it, the "
     "checks that must pass, and what is explicitly not done in this unit"),
    ("Falsifiability", "a concrete \"if this happens, revisit\", not a hedge"),
]

MIN_CRITERIA = 2

# File names a record may carry inside the folder: ADR-NNNN-x.md, adr-N-x.md, NNNN-x.md, NNNN_x.md.
NAME = re.compile(r"(?i)^(adr-.+|\d{4}[-_].+)\.md$")


def folder():
    """The opted-in ADR folder, absolute or repo-relative, ending in a slash; None when not opted in."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    value = os.environ.get("ADR_DIR") or ""
    try:
        from project_fact import fact
        value = fact("ADR_DIR", value) or ""
    except Exception:
        pass
    value = os.path.expanduser(value.strip()).replace("\\", "/")
    if not value.strip("/"):
        return None
    if value.startswith("/"):
        return value.rstrip("/") + "/"
    return value.strip("/") + "/"


def is_adr(path, where=None):
    """Whether `path` is a record file inside the opted-in folder."""
    where = where if where is not None else folder()
    if not where or not path:
        return False
    norm = os.path.expanduser(path).replace("\\", "/")
    if where.startswith("/"):
        inside = norm.startswith(where) or os.path.realpath(norm).startswith(os.path.realpath(where) + "/")
    else:
        inside = norm.startswith(where) or ("/" + where) in norm
    return inside and bool(NAME.match(os.path.basename(norm)))


def has_section(text, title):
    """A markdown heading of any level, or a bold label at the start of a line, naming the section."""
    t = re.escape(title)
    return re.search(r"(?mi)^\s{0,3}#{1,6}\s+%s\s*:?\s*$|^\s*(?:[-*]\s+)?\*\*\s*%s\s*:?\s*\*\*" % (t, t),
                     text) is not None


def criteria_count(text):
    """Numbered criteria inside the Acceptance Criteria section only."""
    m = re.search(r"(?mi)^\s{0,3}#{1,6}\s+Acceptance Criteria\s*:?\s*$", text)
    if not m:
        return 0
    rest = text[m.end():]
    nxt = re.search(r"(?m)^\s{0,3}#{1,6}\s+\S", rest)
    body = rest[:nxt.start()] if nxt else rest
    return len(re.findall(r"(?mi)^\s*[-*]?\s*`?AC-\d+", body))


def missing(text):
    """The reasons a new record is short of the shape, one per gap; empty when it has it all."""
    reasons = ["`## %s` is absent. Add it: %s." % (title, want)
               for title, want in SECTIONS if not has_section(text, title)]
    if has_section(text, "Acceptance Criteria") and criteria_count(text) < MIN_CRITERIA:
        reasons.append(
            "`## Acceptance Criteria` carries %d numbered criteria and needs at least %d. "
            "Number them AC-1, AC-2, one assertion each. A decision worth an ADR changes "
            "more than one observable thing, and the failure paths are criteria too."
            % (criteria_count(text), MIN_CRITERIA))
    return reasons


def removed(old, new):
    """The reasons a change to a record drops a required section it had."""
    return ["This change removes the `## %s` section. If the section is being rewritten, keep "
            "its heading. If the decision genuinely no longer needs it, that is the user's "
            "call, not an edit's." % title
            for title, _ in SECTIONS if has_section(old, title) and not has_section(new, title)]


def committed(path):
    """The record as HEAD carries it, or None when HEAD does not (a new record); any doubt is None."""
    try:
        full = os.path.abspath(os.path.expanduser(path))
        d = os.path.dirname(full) or "."
        top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if top.returncode != 0:
            return None
        rel = os.path.relpath(os.path.realpath(full), os.path.realpath(top.stdout.strip()))
        r = subprocess.run(["git", "-C", d, "show", "HEAD:" + rel],
                           capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def check(path, text):
    """A new record must carry the whole shape; one HEAD already carries must keep the sections it had."""
    before = committed(path)
    return missing(text) if before is None else removed(before, text)


def main(argv):
    if argv == ["folder"]:
        print(folder() or "")
        return 0
    if len(argv) == 2 and argv[0] == "is-adr":
        return 0 if is_adr(argv[1]) else 1
    if argv == ["pick"]:
        where = folder()
        for line in sys.stdin:
            path = line.strip()
            if is_adr(path, where):
                print(path)
        return 0
    if len(argv) == 2 and argv[0] == "check":
        try:
            with open(argv[1]) as handle:
                text = handle.read()
        except OSError:
            return 0
        for reason in check(argv[1], text):
            print(reason)
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
