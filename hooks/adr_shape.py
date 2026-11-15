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

Where the project recorded an architecture doc (ARCHITECTURE_DOC), a new record also carries
an Architecture Alignment section: each part of the doc it touches, with conforms or diverges
and why, and a Builds line naming every build its work must work in.
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

# Asked of a new record only where the project recorded an architecture doc (ARCHITECTURE_DOC).
ALIGNMENT = "Architecture Alignment"
ALIGNMENT_WANT = (
    "one list item or heading for each part of the architecture doc (%s) this decision touches, "
    "named as the doc titles it, saying it conforms, or diverges and why; then a `Builds:` line listing every "
    "build this decision's work must work in. Leave out the parts it does not touch")
# Words of reason a divergence needs after the word that declares it.
MIN_WHY_WORDS = 3
VERDICT = re.compile(r"(?i)\b(?:conform|diverg)\w*")
DIVERGES = re.compile(r"(?i)\bdiverg\w*")
BUILDS = re.compile(r"(?i)^\s*(?:[-*]\s+)?(?:\*\*|__)?\s*builds?\s*(?::\s*(?:\*\*|__)?|(?:\*\*|__)\s*:?)(.*)$")

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


def architecture_doc():
    """(full path, repo-relative path) of the project's recorded architecture doc, or None."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import project_fact
        path = project_fact.architecture_doc()
        if not path:
            return None
        top = project_fact.checkout_top(project_fact.project_root())
        return path, os.path.relpath(path, top)
    except Exception:
        return None


def sections(doc=None):
    """The required (title, what to write) pairs: the alignment section too when a doc is recorded."""
    if not doc:
        return list(SECTIONS)
    return list(SECTIONS) + [(ALIGNMENT, ALIGNMENT_WANT % doc[1])]


def _plain(text):
    """A heading or label reduced to its words: no markup, no closing punctuation."""
    text = re.sub(r"[`*_]", "", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".:").strip()


def doc_parts(doc_text):
    """The parts an ADR can name: each heading below the title, and each bold label opening a list item."""
    parts = []
    for line in doc_text.splitlines():
        m = re.match(r"^\s{0,3}#{2,6}\s+(.+?)\s*#*\s*$", line) \
            or re.match(r"^\s*[-*]\s+(?:\*\*|__)(.+?)(?:\*\*|__)", line)
        if m:
            name = _plain(m.group(1))
            if name and name.lower() not in [p.lower() for p in parts]:
                parts.append(name)
    return parts


def section_body(text, title):
    """The lines under the section's heading, up to the next heading of the same or a higher level."""
    t = re.escape(title)
    m = re.search(r"(?mi)^\s{0,3}(#{1,6})\s+%s\s*:?\s*$" % t, text)
    if m:
        rest = text[m.end():]
        nxt = re.search(r"(?m)^\s{0,3}#{1,%d}\s+\S" % len(m.group(1)), rest)
        return rest[:nxt.start()] if nxt else rest
    m = re.search(r"(?mi)^\s*(?:[-*]\s+)?\*\*\s*%s\s*:?\s*\*\*:?(.*)$" % t, text)
    if m:
        rest = text[m.end():]
        nxt = re.search(r"(?m)^\s{0,3}#{1,6}\s+\S", rest)
        return m.group(1) + (rest[:nxt.start()] if nxt else rest)
    return ""


def _names(line, parts):
    """The longest part of the doc this line names, when it is a list item or a heading; else None."""
    if not re.match(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s)", line):
        return None
    low = " ".join(re.sub(r"[`*_]", "", line).lower().split())
    hits = [p for p in parts if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(p.lower()), low)]
    return max(hits, key=len) if hits else None


def alignment(text, parts):
    """Read the alignment section: ({part: the entry's text}, [each build listed], whether a Builds line was found)."""
    entries, builds, found, current, listing = {}, [], False, None, False
    for line in section_body(text, ALIGNMENT).splitlines():
        b = BUILDS.match(line)
        if b:
            found, current = True, None
            rest = b.group(1).strip()
            builds += [x.strip() for x in re.split(r"[,;]", rest) if x.strip()]
            listing = not rest
            continue
        if listing:
            item = re.match(r"^\s*[-*]\s+(.+)$", line)
            if item:
                builds.append(item.group(1).strip())
                continue
            if line.strip():
                listing = False
        part = _names(line, parts)
        if part:
            current = part
            entries[part] = entries.get(part, "") + " " + line
        elif current:
            entries[current] += " " + line
    return entries, builds, found


def diverging(text, parts):
    """The parts of the doc a record's alignment section says it diverges from."""
    entries, _, _ = alignment(text, parts)
    return sorted(p for p, said in entries.items() if DIVERGES.search(said))


def read_doc(doc):
    try:
        with open(doc[0]) as handle:
            return handle.read()
    except (OSError, TypeError):
        return ""


def alignment_gaps(text, doc):
    """The reasons a new record's alignment section falls short of what the issue asks, one per gap."""
    if not has_section(text, ALIGNMENT):
        return []
    parts = doc_parts(read_doc(doc))
    listed = "; ".join("`%s`" % p for p in parts) or "(the doc has no headings yet)"
    entries, builds, found = alignment(text, parts)
    reasons = []
    if not entries:
        reasons.append(
            "`## %s` names no part of the architecture doc (%s). Name each part this decision "
            "touches as the doc titles it, and only those. Its parts: %s." % (ALIGNMENT, doc[1], listed))
    for part, said in entries.items():
        if not VERDICT.search(said):
            reasons.append("`## %s` names `%s` with no verdict. Say it conforms, or that it "
                           "diverges and why." % (ALIGNMENT, part))
            continue
        m = DIVERGES.search(said)
        if m and len(re.findall(r"[A-Za-z0-9']+", said[m.end():])) < MIN_WHY_WORDS:
            reasons.append("`## %s` says it diverges from `%s` but not why. Say what this "
                           "decision does instead and why." % (ALIGNMENT, part))
    if not found or not builds:
        reasons.append(
            "`## %s` lists no builds. Add a `Builds:` line naming every build this decision's "
            "work must work in, as the doc's parts name them." % ALIGNMENT)
    return reasons


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


def missing(text, doc=False):
    """The reasons a new record is short of the shape, one per gap; empty when it has it all.

    `doc` is the recorded architecture doc as architecture_doc() gives it; left out, it is looked up.
    """
    doc = architecture_doc() if doc is False else doc
    reasons = ["`## %s` is absent. Add it: %s." % (title, want)
               for title, want in sections(doc) if not has_section(text, title)]
    if doc:
        reasons += alignment_gaps(text, doc)
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
            for title, _ in sections(architecture_doc())
            if has_section(old, title) and not has_section(new, title)]


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
