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
    "named as the doc titles it and followed by its verdict: conforms, or diverges and why; then a `Builds:` line listing every "
    "build this decision's work must work in. Leave out the parts it does not touch")
# Words of reason a divergence needs after the word that declares it.
MIN_WHY_WORDS = 3
# The verdict opens what the entry says about its part: "conforms", "diverges", or one of them
# turned around by a "not" ("does not conform" diverges). A verdict word anywhere else is not read.
OPENING_VERDICT = re.compile(r"(?i)^\W*(?:(does\s+not|doesn't|do\s+not|don't|not)\s+)?(conform|diverg)[a-z]*\b")
# Words that only point back at the doc or the part, so they give no reason for a divergence.
NOT_A_REASON = {"from", "the", "this", "that", "doc", "docs", "doc's", "document", "architecture", "part",
                "section", "it", "its", "of", "to", "a", "an", "here", "in", "on", "at", "as", "by", "per",
                "see", "with", "rule", "rules"}
# Where a Builds line divides one build from the next.
BUILD_SPLIT = re.compile(r"[,;&]|\s+and\s+")
# What a Builds line may not stand on instead of a build.
NO_BUILD = {"none", "n/a", "na", "tbd", "tba", "todo", "-", "?", "unknown", "nothing"}
# A line that can open an entry: a heading, or a list item at the left margin (not a sub-bullet).
ENTRY_LINE = re.compile(r"^(?:\s{0,3}#{1,6}\s|\s?(?:[-*+]|\d+[.)])\s)")
BUILDS = re.compile(r"(?i)^\s*(?:[-*]\s+)?(?:\*\*|__)?\s*builds?\s*(?::\s*(?:\*\*|__)?|(?:\*\*|__)\s*:?)(.*)$")

# File names a record may carry inside the folder: ADR-NNNN-x.md, adr-N-x.md, NNNN-x.md, NNNN_x.md.
NAME = re.compile(r"(?i)^(adr-.+|\d{4}[-_].+)\.md$")


def repo_of(path=None, cwd=None):
    """The checkout a record belongs to (project_fact.repo_root: the file's, else the shell's), or None."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import project_fact
        return project_fact.repo_root(path, cwd)
    except Exception:
        return None


def named_folder(root=None):
    """ADR_DIR as the checkout at `root` names it, with ~ expanded, or ""."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    value = os.environ.get("ADR_DIR") or ""
    try:
        from project_fact import fact
        value = fact("ADR_DIR", value, root) or ""
    except Exception:
        pass
    return os.path.expanduser(value.strip()).replace("\\", "/")


def outside(value, root=None):
    """Whether the folder `value`, absolute or relative to the checkout at `root`, lies outside that checkout."""
    try:
        import project_fact
        top = os.path.realpath(project_fact.checkout_top(root or project_fact.project_root()))
    except Exception:
        return value.startswith("/")
    return not (os.path.realpath(os.path.join(top, value)) + "/").startswith(top.rstrip("/") + "/")


def folder(root=None):
    """The opted-in ADR folder of the checkout at `root`, absolute or repo-relative, ending in a slash; None
    when not opted in. Decision records live in the repository (MAST-48), so a folder outside it is None."""
    value = named_folder(root)
    if not value.strip("/") or outside(value, root):
        return None
    if value.startswith("/"):
        return value.rstrip("/") + "/"
    return value.strip("/") + "/"


def outside_line(root=None):
    """The one line that says the checkout at `root` names an ADR folder outside it, which no gate checks;
    None when it does not."""
    value = named_folder(root)
    if not value.strip("/") or not outside(value, root):
        return None
    return ("Masthead: ADR_DIR names {}, outside the repository, so no decision record there is checked. "
            "Decision records must live in the repository.".format(value))


def architecture_doc(root=None):
    """(full path, repo-relative path) of the architecture doc the checkout at `root` records, or None."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import project_fact
        root = root or project_fact.project_root()
        path = project_fact.architecture_doc(root)
        if not path:
            return None
        top = project_fact.checkout_top(root)
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
    """The parts an ADR can name: each heading, at any level, and each bold label opening a list item.

    Any level, because setup's own check accepts a doc whose parts are top-level headings.
    """
    parts = []
    for line in doc_text.splitlines():
        m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line) \
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
    """The longest part of the doc this line names, when it is a heading or a top-level list item; else None."""
    if not ENTRY_LINE.match(line):
        return None
    low = " ".join(re.sub(r"[`*_]", "", line).lower().split())
    hits = [p for p in parts if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(p.lower()), low)]
    return max(hits, key=len) if hits else None


def alignment(text, parts, known=()):
    """Read the alignment section: ({part: the entry's text}, [each build listed], whether a Builds line was found).

    An entry is a heading or a top-level list item naming a part. A list item runs to the next
    blank line, taking its indented lines; a heading runs to the next heading or list item.
    Under a bare Builds line, a list item is a build unless it names a part that is not a build
    (`known` holds the doc's build lines).
    """
    entries, builds, found = {}, [], False
    current, kind, listing = None, None, False
    for line in section_body(text, ALIGNMENT).splitlines():
        b = BUILDS.match(line)
        if b:
            found, current = True, None
            rest = b.group(1).strip()
            builds += [x.strip() for x in BUILD_SPLIT.split(re.sub(r"\([^)]*\)", "", rest)) if x.strip()]
            listing = not rest
            continue
        part = _names(line, parts)
        if listing:
            item = re.match(r"^\s*[-*+]\s+(.+)$", line)
            if item and not (part and not is_build(part, known)):
                builds.append(item.group(1).strip())
                continue
            if line.strip():
                listing = False
        if part:
            current, kind = part, ("heading" if line.lstrip().startswith("#") else "item")
            entries[part] = entries.get(part, "") + " " + line
            continue
        if current is None:
            continue
        if not line.strip():
            if kind == "item":
                kind = "item-gap"
            continue
        if ENTRY_LINE.match(line) or (kind == "item-gap" and not line.startswith("  ")):
            current = None
            continue
        entries[current] += " " + line
    return entries, builds, found


def verdict(said, part):
    """("conforms" or "diverges", what follows it) as the entry states it; (None, "") when it states none.

    The verdict is read where the entry puts it: first after the part's name ("`Seams`: diverges,
    because ..."), or first before it ("Diverges from `Seams` ..."). A verdict word inside the
    part's own name, or later in the entry, is not one.
    """
    text = re.sub(r"[`*_]", "", said)
    text = re.sub(r"^\s*(?:#{1,6}|[-*+]|\d+[.)])\s+", "", text)
    at = text.lower().find(part.lower())
    after, before = (text[at + len(part):], text[:at]) if at >= 0 else (text, "")
    for opening, rest in ((after, ""), (before, after)):
        m = OPENING_VERDICT.match(opening)
        if m:
            said_word = m.group(2).lower()
            if m.group(1):
                said_word = "diverg" if said_word == "conform" else "conform"
            return ("conforms" if said_word == "conform" else "diverges"), opening[m.end():] + " " + rest
    return None, ""


def reason_words(rest):
    """The words that give a reason: not a path, not a word that only names the doc or a part."""
    words = []
    for token in rest.split():
        if "/" in token or re.search(r"(?i)\.md\b", token):
            continue
        words += [w for w in re.findall(r"[a-z0-9']+", token.lower()) if w not in NOT_A_REASON]
    return words


def diverging(text, parts):
    """The parts of the doc a record's alignment section says it diverges from."""
    entries, _, _ = alignment(text, parts)
    return sorted(p for p, said in entries.items() if verdict(said, p)[0] == "diverges")


def build_name(item):
    """A build as a Builds line lists it: its name, without what follows a colon, dash, bracket or comma."""
    return _plain(re.split(r"\s*(?::|\s-\s|\(|,)", re.sub(r"[`*_]", "", item))[0])


def doc_builds(doc_text):
    """The doc's build lines: each line under the heading that lists what each build ships, list marker and markup removed.

    A whole line, because the template asks for "one line each" without saying where the name ends.
    """
    lines, inside = [], False
    for line in doc_text.splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
        if heading:
            # The template's "What each build ships"; not the rule "What each build carries".
            inside = re.search(r"(?i)\bbuilds\b|\bships?\b|\beditions\b", heading.group(1)) is not None
            continue
        if inside and line.strip():
            plain = _plain(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line))
            if plain:
                lines.append(plain)
    return lines


def is_build(name, known):
    """Whether one of the doc's build lines opens with this build's name."""
    name = build_name(name).lower()
    return bool(name) and any(re.match(r"%s(?![a-z0-9-])" % re.escape(name), k.lower()) for k in known)


def build_gaps(builds, known):
    """The reasons the builds listed fall short: none listed, or one the doc does not name."""
    real = [b for b in builds if build_name(b).lower() not in NO_BUILD]
    if not real:
        return ["`## %s` lists no builds. Add a `Builds:` line naming every build this decision's "
                "work must work in, as the doc's parts name them." % ALIGNMENT]
    if not known:
        return []
    unknown = [b for b in real if not is_build(b, known)]
    if not unknown:
        return []
    return ["`## %s` lists %s, which the architecture doc does not name as a build. The doc's "
            "builds: %s. Name each build this decision's work must work in as its line in the "
            "doc opens, or add the new build to the doc." % (
                ALIGNMENT, ", ".join("`%s`" % build_name(b) for b in unknown),
                ", ".join("`%s`" % build_name(k) for k in known))]


def read_doc(doc):
    try:
        with open(doc[0]) as handle:
            return handle.read()
    except (OSError, TypeError):
        return ""


def alignment_gaps(text, doc, verdicts_only=False):
    """The reasons a new record's alignment section falls short of what the issue asks, one per gap.

    `verdicts_only` asks only for a verdict and a why on each entry, and not that its parts and
    builds be the doc's as it reads today: a record git already carries may predate a rename.
    """
    if not has_section(text, ALIGNMENT):
        return []
    doc_text = read_doc(doc)
    parts = doc_parts(doc_text)
    listed = "; ".join("`%s`" % p for p in parts) or "(the doc has no headings yet)"
    known = doc_builds(doc_text)
    entries, builds, found = alignment(text, parts, known)
    reasons = []
    if not entries and not verdicts_only:
        reasons.append(
            "`## %s` names no part of the architecture doc (%s). Name each part this decision "
            "touches as the doc titles it, and only those. Its parts: %s." % (ALIGNMENT, doc[1], listed))
    for part, said in entries.items():
        said_verdict, rest = verdict(said, part)
        if not said_verdict:
            reasons.append("`## %s` names `%s` with no verdict. Say it conforms, or that it "
                           "diverges and why." % (ALIGNMENT, part))
            continue
        why = re.sub(re.escape(part), " ", rest, flags=re.IGNORECASE)
        if said_verdict == "diverges" and len(reason_words(why)) < MIN_WHY_WORDS:
            reasons.append("`## %s` says it diverges from `%s` but not why. Say what this "
                           "decision does instead and why." % (ALIGNMENT, part))
    if not verdicts_only:
        reasons += build_gaps(builds if found else [], known)
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


def missing(text, doc=False, root=None):
    """The reasons a new record is short of the shape, one per gap; empty when it has it all.

    `doc` is the recorded architecture doc as architecture_doc() gives it; left out, it is looked up.
    """
    doc = architecture_doc(root) if doc is False else doc
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


def removed(old, new, root=None):
    """The reasons a change to a record drops a required section it had."""
    return ["This change removes the `## %s` section. If the section is being rewritten, keep "
            "its heading. If the decision genuinely no longer needs it, that is the user's "
            "call, not an edit's." % title
            for title, _ in sections(architecture_doc(root))
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
        for old in [rel] + earlier_names(d, rel):
            r = subprocess.run(["git", "-C", d, "show", "HEAD:" + old],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return r.stdout
        return None
    except Exception:
        return None


def earlier_names(d, rel):
    """The names HEAD may carry this record under: a staged rename's old name, then a committed
    file with the same name in another folder (a record moved from Proposed to Current)."""
    names = []
    r = subprocess.run(["git", "-C", d, "diff", "--cached", "-M", "--name-status", "HEAD"],
                       capture_output=True, text=True, timeout=5)
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        fields = line.split("\t")
        if len(fields) == 3 and fields[0].startswith("R") and fields[2] == rel:
            names.append(fields[1])
    r = subprocess.run(["git", "-C", d, "ls-tree", "-r", "--full-tree", "--name-only", "HEAD"],
                       capture_output=True, text=True, timeout=5)
    base = os.path.basename(rel)
    names += [n for n in (r.stdout.splitlines() if r.returncode == 0 else [])
              if os.path.basename(n) == base and n != rel]
    return names


def check(path, text):
    """A new record must carry the whole shape; one HEAD already carries must keep the sections it had.

    A record HEAD carries is not asked for the alignment section, but where it has one, each
    entry it is left with still needs a verdict and a why.
    """
    before = committed(path)
    root = repo_of(path)
    return missing(text, root=root) if before is None else \
        removed(before, text, root) + kept_alignment_gaps(text, root)


def kept_alignment_gaps(text, root=None):
    """The entries of a carried record's alignment section left with no verdict or no why.

    Only those: its part and build names are not held to the doc as it reads today, so a
    later rename in the doc never blocks an edit to an old record.
    """
    doc = architecture_doc(root)
    return alignment_gaps(text, doc, verdicts_only=True) if doc else []


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
