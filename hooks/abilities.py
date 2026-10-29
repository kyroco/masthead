#!/usr/bin/env python3
"""The abilities file: one copy of every can and can't for one decision record.

  abilities.py check [--base REV] PATH...   refuse a bad file, naming the line
  abilities.py page FILE -o OUT             write the abilities page from FILE
  abilities.py verify-page PAGE             refuse a page that differs from a fresh build

PATH is a file or a folder of .yaml and .yml files. Each problem prints as
"path:line: what is wrong"; exit 1 when there is one, 2 when nothing could be read.
"""
import datetime
import html
import os
import re
import subprocess
import sys

try:
    import yaml
except ImportError:  # the gate blocks on exit 2
    yaml = None

TOP_KEYS = ("record", "roles", "plans", "examples", "lines")
LINE_KEYS = ("id", "role", "plans", "kind", "action", "words", "states", "why", "screen", "rule", "retired")
REQUIRED = ("id", "role", "kind", "action", "states", "why")
KINDS = ("can", "cant")
ID_SHAPE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
HOLE = re.compile(r"\{([^{}]*)\}")
HOLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
RETIRED_SHAPE = re.compile(r"^(\d{4}-\d{2}-\d{2})[,;:]?\s+(\S.*)$")
STAMP = "masthead-abilities"


def need_yaml():
    if yaml is None:
        print("abilities: PyYAML is not installed, so no abilities file could be read. Run 'python3 -m pip install pyyaml'.",
              file=sys.stderr)
        sys.exit(2)


def files_in(path):
    if os.path.isdir(path):
        return sorted(os.path.join(path, n) for n in os.listdir(path)
                      if n.endswith((".yaml", ".yml")) and os.path.isfile(os.path.join(path, n)))
    return [path]


def line_of(node):
    return node.start_mark.line + 1


def scalar(node):
    """The text of a scalar node, or None for a list, a map or an empty value."""
    if isinstance(node, yaml.ScalarNode) and node.value != "":
        return node.value
    return None


def pairs(node, where, problems):
    """The (key, key node, value node) of a map, refusing a key written twice."""
    out, seen = [], {}
    for k, v in node.value:
        key = k.value if isinstance(k, yaml.ScalarNode) else None
        if key in seen:
            problems.append((line_of(k), "'{}' is written twice in {} (first at line {})".format(key, where, seen[key])))
            continue
        seen[key] = line_of(k)
        out.append((key, k, v))
    return out


def read(text, problems):
    """Parse the file's text into its parts, adding each problem with its line."""
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        problems.append((mark.line + 1 if mark else 1, "this is not valid YAML: {}".format(getattr(err, "problem", err))))
        return None
    if not isinstance(root, yaml.MappingNode):
        problems.append((1, "the file must be a map with record, roles, plans, examples and lines"))
        return None
    doc = {"roles": {}, "plans": [], "examples": {}, "lines": [], "record": None}
    top = {}
    for key, knode, v in pairs(root, "the file", problems):
        if key not in TOP_KEYS:
            hint = " The file keeps no log: git holds the history and the record's dated line the why." \
                if key in ("log", "history", "versions", "changes", "changelog") else ""
            problems.append((line_of(knode), "'{}' is not a part of the file; it holds only {}.{}".format(
                key, ", ".join(TOP_KEYS), hint)))
            continue
        top[key] = (knode, v)
    for key in ("record", "roles", "lines"):
        if key not in top:
            problems.append((1, "the file has no '{}'".format(key)))
    if "record" in top:
        doc["record"] = scalar(top["record"][1])
        if not doc["record"]:
            problems.append((line_of(top["record"][0]), "'record' names no decision record"))
    for key in ("roles", "examples"):
        if key in top:
            node = top[key][1]
            if not isinstance(node, yaml.MappingNode):
                problems.append((line_of(node), "'{}' must be a map of id to words".format(key)))
                continue
            for name, knode, v in pairs(node, "'{}'".format(key), problems):
                if scalar(v) is None:
                    problems.append((line_of(knode), "{} '{}' has no words".format(key[:-1], name)))
                doc[key][name] = scalar(v) or ""
    if "plans" in top:
        node = top["plans"][1]
        if not isinstance(node, yaml.SequenceNode):
            problems.append((line_of(node), "'plans' must be a list"))
        else:
            doc["plans"] = [n.value for n in node.value if isinstance(n, yaml.ScalarNode)]
    if "lines" in top:
        node = top["lines"][1]
        if not isinstance(node, yaml.SequenceNode):
            problems.append((line_of(node), "'lines' must be a list"))
        else:
            for item in node.value:
                doc["lines"].append(read_line(item, doc, problems))
    return doc


def read_line(node, doc, problems):
    at = line_of(node)
    line = {"_line": at, "states": []}
    if not isinstance(node, yaml.MappingNode):
        problems.append((at, "a line must be a map with id, role, kind, action, states and why"))
        return line
    nodes = {}
    for key, knode, v in pairs(node, "this line", problems):
        if key not in LINE_KEYS:
            problems.append((line_of(knode), "'{}' is not a field of a line; a line holds only {}".format(
                key, ", ".join(LINE_KEYS))))
            continue
        nodes[key] = (knode, v)
    ident = scalar(nodes["id"][1]) if "id" in nodes else None
    label = "line {}".format(ident) if ident else "this line"
    for key in REQUIRED:
        if key not in nodes:
            problems.append((at, "{} has no '{}'".format(label, key)))
    for key, (knode, v) in nodes.items():
        if key == "states":
            if not isinstance(v, yaml.MappingNode) or not v.value:
                problems.append((line_of(knode), "{} has no states: name each state it must hold in, and what is true there".format(label)))
                continue
            for name, sk, sv in pairs(v, "the states of " + label, problems):
                if scalar(sv) is None:
                    problems.append((line_of(sk), "state '{}' of {} does not say what is true there".format(name, label)))
                line["states"].append((name, scalar(sv) or ""))
        elif key == "plans":
            if not isinstance(v, yaml.SequenceNode) or not v.value:
                problems.append((line_of(knode), "{} names no plans".format(label)))
                continue
            line["plans"] = []
            for p in v.value:
                if not isinstance(p, yaml.ScalarNode) or p.value not in doc["plans"]:
                    problems.append((line_of(p), "plan '{}' of {} is not in the plans list".format(
                        getattr(p, "value", "?"), label)))
                else:
                    line["plans"].append(p.value)
        else:
            text = scalar(v)
            if text is None and key != "words":
                problems.append((line_of(knode), "'{}' of {} is empty".format(key, label)))
            line[key] = text
            line["_" + key] = line_of(v)
    if ident and not ID_SHAPE.match(ident):
        problems.append((line["_id"], "id '{}' is not a record prefix and a number, like OM-153".format(ident)))
    role = line.get("role")
    if role and role not in doc["roles"]:
        problems.append((line["_role"], "role '{}' of {} is not in the roles list".format(role, label)))
    kind = line.get("kind")
    if kind and kind not in KINDS:
        problems.append((line["_kind"], "kind '{}' of {} must be can or cant".format(kind, label)))
    if kind == "cant" and not line.get("words"):
        problems.append((line.get("_words", at), "{} is a can't with no words: give the exact sentence it shows".format(label)))
    words = line.get("words")
    if words:
        for hole in HOLE.findall(words):
            if not HOLE_NAME.match(hole):
                problems.append((line["_words"], "'{{{}}}' in the words of {} is not a hole name".format(hole, label)))
            elif hole not in doc["examples"]:
                problems.append((line["_words"], "hole '{{{}}}' in the words of {} has no example in 'examples'".format(hole, label)))
    retired = line.get("retired")
    if retired:
        m = RETIRED_SHAPE.match(retired)
        ok = False
        if m:
            try:
                datetime.date.fromisoformat(m.group(1))
                ok = True
            except ValueError:
                pass
        if not ok:
            problems.append((line["_retired"], "'retired' of {} must be the date and the decision line that retired it, like '2026-11-02, ADR-0170 D6'".format(label)))
    return line


def git_show(rev, path):
    """The text of PATH at REV, or None when it was not there."""
    try:
        top = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(path)), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(top))
        out = subprocess.run(["git", "-C", top, "show", "{}:{}".format(rev, rel)], capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout if out.returncode == 0 else None


def check(paths, base=None):
    """Every problem in the files under PATHS, as (path, line, words)."""
    found, owner = [], {}
    for root in paths:
        for path in files_in(root):
            try:
                with open(path) as handle:
                    text = handle.read()
            except OSError as err:
                found.append((path, 1, "cannot be read: {}".format(err)))
                continue
            problems = []
            doc = read(text, problems)
            found.extend((path, n, words) for n, words in problems)
            if not doc:
                continue
            ids = set()
            for line in doc["lines"]:
                ident = line.get("id")
                if not ident:
                    continue
                ids.add(ident)
                if ident in owner:
                    first = owner[ident]
                    found.append((path, line["_id"], "id {} is reused; it is already at {}:{}. An id is never reused, even once retired".format(
                        ident, first[0], first[1])))
                else:
                    owner[ident] = (path, line["_id"])
            if base:
                found.extend(dropped(path, base, ids))
    return found


def dropped(path, base, ids):
    """Ids that were in PATH at BASE and are gone now: a line is retired, never deleted."""
    text = git_show(base, path)
    if text is None:
        return []
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return []
    out = []
    for key, v in (root.value if isinstance(root, yaml.MappingNode) else []):
        if getattr(key, "value", None) != "lines" or not isinstance(v, yaml.SequenceNode):
            continue
        for item in v.value:
            if not isinstance(item, yaml.MappingNode):
                continue
            for k, iv in item.value:
                if getattr(k, "value", None) == "id" and isinstance(iv, yaml.ScalarNode) and iv.value not in ids:
                    out.append((path, 1, "id {} (line {} before this branch) is gone. A line that stops being true is retired, never deleted: put it back with 'retired: <date>, <decision line>'".format(
                        iv.value, line_of(iv))))
    return out


def fill(words, examples):
    return HOLE.sub(lambda m: examples.get(m.group(1), m.group(0)), words)


def render(doc, source):
    """The abilities page for DOC. Every sentence on it comes from the file."""
    e = html.escape
    record = doc["record"] or ""
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="{}" content="{}">'.format(STAMP, e(source)),
        "<title>{} abilities</title>".format(e(record)),
        "<style>",
        ":root{--bg:#fff;--fg:#1a2230;--muted:#5b6878;--line:#c8d1dc}",
        "@media (prefers-color-scheme:dark){:root{--bg:#0f151c;--fg:#e7ecf2;--muted:#9aa7b6;--line:#2c3845}}",
        "body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}",
        "main{max-width:880px;margin:0 auto}",
        "section{border-top:1px solid var(--line);padding-top:8px;margin-top:24px}",
        "li{margin:10px 0}.id{font-family:ui-monospace,monospace;color:var(--muted)}",
        ".words{font-style:italic}.meta{color:var(--muted);font-size:13px}",
        ".retired .action{text-decoration:line-through}",
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        "<h1>{}</h1>".format(e(record)),
    ]
    lines = doc["lines"]
    for role, name in doc["roles"].items():
        mine = [ln for ln in lines if ln.get("role") == role]
        if not mine:
            continue
        out.append('<section id="{}">'.format(e(role)))
        out.append("<h2>{}</h2>".format(e(name)))
        for kind, heading in (("can", "Can"), ("cant", "Can't"), (None, "Retired")):
            group = [ln for ln in mine if (ln.get("retired") is None) == (kind is not None)
                     and (kind is None or ln.get("kind") == kind)]
            if not group:
                continue
            out.append("<h3>{}</h3>".format(heading))
            out.append('<ul{}>'.format(' class="retired"' if kind is None else ""))
            for ln in group:
                out.append(item(ln, doc["examples"]))
            out.append("</ul>")
        out.append("</section>")
    out += ["</main>", "</body>", "</html>", ""]
    return "\n".join(out)


def item(ln, examples):
    e = html.escape
    parts = ['<li id="{}"><span class="id">{}</span> <span class="action">{}</span>'.format(
        e(ln.get("id") or ""), e(ln.get("id") or ""), e(ln.get("action") or ""))]
    if ln.get("words"):
        parts.append('<div class="words">{}</div>'.format(e(fill(ln["words"], examples))))
    if ln.get("states"):
        parts.append("<ul>" + "".join("<li>{}: {}</li>".format(e(s), e(t)) for s, t in ln["states"]) + "</ul>")
    meta = []
    if ln.get("plans"):
        meta.append(", ".join(ln["plans"]))
    for key in ("why", "screen", "rule", "retired"):
        if ln.get(key):
            meta.append(ln[key])
    if meta:
        parts.append('<div class="meta">{}</div>'.format(e(" · ".join(meta))))
    parts.append("</li>")
    return "".join(parts)


def build(source_path, page_path):
    """The page text for SOURCE_PATH as it would sit at PAGE_PATH, or (None, problems)."""
    with open(source_path) as handle:
        text = handle.read()
    problems = []
    doc = read(text, problems)
    if problems or not doc:
        return None, problems
    rel = os.path.relpath(os.path.abspath(source_path), os.path.dirname(os.path.abspath(page_path)))
    return render(doc, rel.replace(os.sep, "/")), []


def stamp_of(page_text):
    m = re.search(r'<meta name="{}" content="([^"]*)">'.format(STAMP), page_text)
    return html.unescape(m.group(1)) if m else None


def main(argv):
    if not argv or argv[0] not in ("check", "page", "verify-page"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    need_yaml()
    cmd, args = argv[0], argv[1:]
    if cmd == "check":
        base = None
        if args[:1] == ["--base"]:
            base, args = args[1], args[2:]
        if not args:
            print("abilities check: name a file or folder", file=sys.stderr)
            return 2
        found = check(args, base)
        for path, n, words in found:
            print("{}:{}: {}".format(path, n, words))
        return 1 if found else 0
    if cmd == "page":
        if len(args) != 3 or args[1] != "-o":
            print("abilities page: FILE -o OUT", file=sys.stderr)
            return 2
        page, problems = build(args[0], args[2])
        if page is None:
            for n, words in problems:
                print("{}:{}: {}".format(args[0], n, words))
            return 1
        with open(args[2], "w") as handle:
            handle.write(page)
        return 0
    # verify-page
    if len(args) != 1:
        print("abilities verify-page: PAGE", file=sys.stderr)
        return 2
    path = args[0]
    with open(path) as handle:
        text = handle.read()
    source = stamp_of(text)
    if source is None:
        print("{}:1: this page carries no abilities stamp".format(path))
        return 1
    source_path = os.path.join(os.path.dirname(os.path.abspath(path)), source)
    if not os.path.isfile(source_path):
        print("{}:1: the abilities file it was built from, {}, is gone".format(path, source))
        return 1
    fresh, problems = build(source_path, path)
    if fresh is None:
        print("{}:1: its abilities file {} has problems, so the page cannot be rebuilt".format(path, source))
        return 1
    if fresh != text:
        old, new = text.splitlines(), fresh.splitlines()
        n = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
        print("{}:{}: this page differs from a fresh build of {}. It is never edited by hand: change the file, then run 'abilities.py page {} -o {}'".format(
            path, n + 1, source, source, os.path.basename(path)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
