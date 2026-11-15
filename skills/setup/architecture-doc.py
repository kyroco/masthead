#!/usr/bin/env python3
"""Find or check a project's architecture doc, for /masthead:setup.

find            print each architecture doc at a common path, repo-relative, one a line
check DOC [P]   pass the doc only when it states each of the seven lenses as a rule for
                this project (or says why one does not apply), and, when P (the file
                holding the project's principles, usually CLAUDE.md) numbers them P1, P2
                and on, cites them by those numbers and copies none of their text.
check --draft DOC [P]
                the same, and the doc fills each section of the setup template with no
                placeholder left anywhere: for a draft setup wrote from the template.
                Exit 0 passes; 1 prints what is missing, one line each; 2 is a usage error.
"""
import os
import re
import sys

LENSES = (
    "Direction",
    "One way in and out",
    "Call shape",
    "Seams",
    "What each build carries",
    "Leftovers",
    "Tests and checks",
)
# A rule shorter than this says nothing a reviewer can hold code to.
MIN_RULE_WORDS = 4
MIN_REASON_WORDS = 3
# This many words in a row taken from a principle is a copy, not a citation.
COPY_RUN = 8
# The template's sections, which a draft made from it fills.
SECTIONS = (
    "The parts",
    "One way in and out for each body of data",
    "Core and extensions",
    "What each build ships",
)
PLACEHOLDER = re.compile(r"<[^<>=\n]*\s[^<>=\n]*>")
DOC_FOLDERS = ("docs", "doc")
SKIP = {"node_modules", "vendor", "deps", "_build", "target", "dist", "build", ".git"}


def repo_top():
    """The folder holding .git at or above the current one, or the current one."""
    here = os.getcwd()
    d = here
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return here
        d = parent


def is_doc(path):
    return os.path.isfile(path) and not os.path.islink(path)


def named(folder, *names):
    """The entries of `folder` whose name matches one of `names`, any case."""
    try:
        entries = os.listdir(folder)
    except OSError:
        return []
    wanted = {n.lower() for n in names}
    return [os.path.join(folder, e) for e in entries if e.lower() in wanted]


def find(top):
    found = [p for p in named(top, "architecture.md") if is_doc(p)]
    for docs in named(top, *DOC_FOLDERS):
        if not os.path.isdir(docs) or os.path.islink(docs):
            continue
        found += [p for p in named(docs, "architecture.md") if is_doc(p)]
        for sub in sorted(os.listdir(docs)):
            folder = os.path.join(docs, sub)
            if sub in SKIP or os.path.islink(folder) or not os.path.isdir(folder):
                continue
            if sub.lower() == "architecture":
                found += [p for p in named(folder, "README.md", "index.md", "architecture.md") if is_doc(p)]
            else:
                found += [p for p in named(folder, "architecture.md") if is_doc(p)]
    return sorted({os.path.relpath(p, top) for p in found}, key=lambda p: (p.count(os.sep), p.lower()))


def words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def principles(path):
    """{number: text} for each principle written as a line starting P<n>."""
    found = {}
    current = None
    with open(path) as handle:
        for line in handle:
            start = re.match(r"^\s*(?:[-*]|\d+\.)?\s*(?:\*\*)?P(\d+)(?:\*\*)?\s*[.:)]\s*(.*)$", line)
            if start:
                current = start.group(1)
                found[current] = start.group(2)
            elif current and line.strip() and line[:1].isspace() and not re.match(r"^\s*[-*]\s", line):
                found[current] += " " + line.strip()
            else:
                current = None
    return found


def label_rest(line, lens):
    """The text after `lens` when the line is labelled with it, else None."""
    bare = re.sub(r"\*\*|__", "", line).strip()
    bare = re.sub(r"^(?:#+|[-*]|\d+\.|\|)\s*", "", bare)
    if not bare.lower().startswith(lens.lower()):
        return None
    rest = bare[len(lens):]
    # A label ends the line (a heading) or is followed by a separator: a period,
    # colon, dash or table bar. "Seams are where..." or a heading "One way in
    # and out for each body of data" only starts with the lens's words.
    if rest.strip() and not re.match(r"^\s*[^\w\s<]", rest):
        return None
    # Drop the separator after the label (a period, colon, dash or table bar), keep a placeholder's "<".
    rest = re.sub(r"\s*\|\s*", " ", rest)
    return re.sub(r"^[^\w<]+", "", rest).rstrip(" .:\t")


def lens_rule(lines, lens):
    """(the rule the doc states for `lens`, None) or (None, why it states none)."""
    best = None
    for i, line in enumerate(lines):
        rest = label_rest(line, lens)
        if rest is None:
            continue
        if not rest and line.lstrip().startswith("#"):  # a heading: its rule is the next line of text
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    rest = "" if re.match(r"^\s*(#|[-*]\s)", nxt) else nxt.strip()
                    break
        if re.search(r"<[^<>=]+>", rest):
            best = best or "{}: the rule is still a placeholder".format(lens)
            continue
        if rest.lower().startswith("does not apply"):
            reason = rest[len("does not apply"):]
            if len(words(reason)) >= MIN_REASON_WORDS:
                return rest, None
            best = "{}: says it does not apply but not why".format(lens)
            continue
        if len(words(rest)) >= MIN_RULE_WORDS:
            return rest, None
        best = best or "{}: names the lens but states no rule for this project".format(lens)
    return None, best or "{}: not stated; write it as a rule for this project, or say why it does not apply".format(lens)


def section_body(lines, name):
    """The text under the heading `name`, or None when the doc has no such heading."""
    for i, line in enumerate(lines):
        if re.match(r"^#+\s*" + re.escape(name) + r"\s*$", line.strip(), re.IGNORECASE):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith("#"):
                    break
                body.append(nxt)
            return " ".join(body)
    return None


def section_problem(lines, name):
    """Why a draft does not fill the template section `name`, or None when it does."""
    body = section_body(lines, name)
    if body is None:
        return "{}: the section is missing".format(name)
    if PLACEHOLDER.search(body):
        return "{}: the section is still a placeholder".format(name)
    if len(words(body)) < MIN_RULE_WORDS:
        return "{}: the section is empty".format(name)
    return None


def check(doc, principles_file=None, draft=False):
    with open(doc) as handle:
        text = handle.read()
    lines = text.splitlines()
    problems = []
    if draft:
        problems += [p for p in (section_problem(lines, name) for name in SECTIONS) if p]
    rules = [lens_rule(lines, lens) for lens in LENSES]
    problems += [problem for _, problem in rules if problem]
    # A citation is a P-number in a rule or in one of the template's sections,
    # never in the intro that says how the doc cites.
    cites_in = " ".join([rule for rule, _ in rules if rule] +
                        [body for body in (section_body(lines, name) for name in SECTIONS) if body])
    if draft:
        for line in lines:
            if PLACEHOLDER.search(line):
                problems.append("a placeholder is left in: {}".format(line.strip()))
    if principles_file:
        known = principles(principles_file)
        if known:
            cited = set(re.findall(r"\bP(\d+)\b", cites_in))
            if not cited:
                problems.append("cites none of the project's principles by number ({})".format(
                    ", ".join("P" + n for n in sorted(known, key=int))))
            for n in sorted(cited - set(known), key=int):
                problems.append("cites P{}, which {} does not have".format(n, os.path.basename(principles_file)))
            flat = " " + " ".join(words(text)) + " "
            for n in sorted(known, key=int):
                own = words(known[n])
                for i in range(len(own) - COPY_RUN + 1):
                    if " " + " ".join(own[i:i + COPY_RUN]) + " " in flat:
                        problems.append("copies the text of P{}; cite it by number instead".format(n))
                        break
    return problems


def main(argv):
    if argv == ["find"]:
        for path in find(repo_top()):
            print(path)
        return 0
    draft = argv[1:2] == ["--draft"]
    if draft:
        argv = argv[:1] + argv[2:]
    if len(argv) in (2, 3) and argv[0] == "check":
        try:
            problems = check(argv[1], argv[2] if len(argv) == 3 else None, draft)
        except OSError as err:
            print("architecture-doc: cannot read {}".format(err.filename), file=sys.stderr)
            return 2
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
