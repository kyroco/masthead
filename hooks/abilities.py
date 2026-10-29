#!/usr/bin/env python3
"""The abilities file: one copy of every can and can't for one decision record.

  abilities.py check [--base REV] PATH...      refuse a bad file, naming the line
  abilities.py page FILE -o OUT                write the abilities page from FILE
  abilities.py verify-page PAGE                refuse a page that differs from a fresh build
  abilities.py gate --top TOP --path PATH [--base REV]
                                               what the push gate runs

PATH is a file or a folder of .yaml and .yml files, checked as one set of ids.
Each problem prints as "path:line: what is wrong"; exit 1 when there is one, 2
when nothing could be read.
"""
import datetime
import html
import os
import re
import shlex
import subprocess
import sys

try:
    import yaml
except ImportError:  # the gate blocks on exit 2
    yaml = None

TOP_KEYS = ("record", "roles", "plans", "examples", "lines")
LINE_KEYS = ("id", "role", "plans", "kind", "action", "words", "states", "why", "screen", "rule", "retired")
REQUIRED = ("id", "role", "kind", "action", "states", "why")
LOG_KEYS = ("log", "history", "versions", "changes", "changelog")
LOG_HINT = " The file keeps no log: git holds the history and the record's dated line the why."
KINDS = ("can", "cant")
NULLS = ("", "~", "null", "Null", "NULL")
ID_SHAPE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
HOLE = re.compile(r"\{([^{}]*)\}")
HOLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
RETIRED_SHAPE = re.compile(r"^(\d{4}-\d{2}-\d{2})[,;:]?\s+(\S.*)$")
STAMP = "masthead-abilities"
STAMP_TAG = re.compile(r'<meta name="{}" content="([^"]*)">'.format(STAMP))


def need_yaml():
    if yaml is None:
        print("abilities: PyYAML is not installed, so no abilities file was read and no page was compared. "
              "Run 'python3 -m pip install pyyaml'.", file=sys.stderr)
        sys.exit(2)


def clean(text):
    """TEXT on one line: any character that does not print (a new line, a Unicode line break) is shown, never acted on."""
    return "".join(c if c.isprintable() else ("\\x{:02x}" if ord(c) < 256 else "\\u{:04x}").format(ord(c))
                   for c in str(text))


def files_in(path):
    if os.path.isdir(path):
        return sorted(os.path.join(path, n) for n in os.listdir(path)
                      if n.endswith((".yaml", ".yml")) and os.path.isfile(os.path.join(path, n)))
    return [path] if os.path.lexists(path) else []


def read_text(path):
    """The text of PATH, or (None, (line, words)) when it cannot be read or is not UTF-8."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as err:
        return None, (1, "cannot be read: {}".format(err))
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError as err:
        return None, (data[:err.start].count(b"\n") + 1, "this file is not UTF-8 text")


def line_of(node):
    return node.start_mark.line + 1


def scalar(node):
    """The text of a scalar node, or None for a list, a map, a null or a blank value."""
    if not isinstance(node, yaml.ScalarNode):
        return None
    if node.style is None and node.value in NULLS:
        return None
    return node.value if node.value.strip() else None


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


def aliases(text):
    """Each alias in TEXT as (line, name). An alias makes one value stand in two places."""
    out = []
    try:
        for event in yaml.parse(text):
            if isinstance(event, yaml.AliasEvent):
                out.append((event.start_mark.line + 1, event.anchor))
    except yaml.YAMLError:
        pass
    return out


def read(text, problems, allow_alias=False):
    """Parse the file's text into its parts, adding each problem with its line.

    ALLOW_ALIAS reads a file that holds an alias anyway, for a base copy whose ids still count."""
    found = [] if allow_alias else aliases(text)
    for n, name in found:
        problems.append((n, "'*{}' is an alias; write the value out, so each line holds its own words".format(name)))
    if found:
        return None
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
            hint = LOG_HINT if str(key).lower() in LOG_KEYS else ""
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
            hint = LOG_HINT if str(key).lower() in LOG_KEYS else ""
            problems.append((line_of(knode), "'{}' is not a field of a line; a line holds only {}.{}".format(
                key, ", ".join(LINE_KEYS), hint)))
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
            line["_" + key] = line_of(v)
            if not isinstance(v, yaml.ScalarNode):
                problems.append((line_of(knode), "'{}' of {} must be text".format(key, label)))
            elif text is None and key != "words":
                problems.append((line_of(knode), "'{}' of {} is empty".format(key, label)))
            line[key] = text
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
    if "retired" in nodes and not retired_ok(line.get("retired")):
        problems.append((line["_retired"], "'retired' of {} must be the date and the decision line that retired it, like '2026-11-02, ADR-0170 D6'".format(label)))
    return line


def retired_ok(value):
    """A real calendar date, then a decision line that names something: letters and a number."""
    m = RETIRED_SHAPE.match(value or "")
    if not m:
        return False
    try:
        datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return False
    rest = m.group(2)
    return bool(re.search(r"[A-Za-z]", rest) and re.search(r"[0-9]", rest))


def git(top, *args):
    """The output of a git command in TOP, or None when it failed."""
    try:
        out = subprocess.run(["git", "-C", top] + list(args), capture_output=True, text=True)
    except OSError:
        return None
    return out.stdout if out.returncode == 0 else None


def git_top(path):
    d = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    out = git(d, "rev-parse", "--show-toplevel")
    return os.path.realpath(out.strip()) if out else None


def head_lines(paths, found):
    """Every line in the files under PATHS, refusing an id written twice anywhere among them."""
    lines, owner = {}, {}
    for root in paths:
        for path in files_in(root):
            text, bad = read_text(path)
            if bad:
                found.append((path,) + bad)
                continue
            problems = []
            doc = read(text, problems)
            found.extend((path, n, words) for n, words in problems)
            if not doc:
                continue
            for line in doc["lines"]:
                ident = line.get("id")
                if not ident:
                    continue
                if ident in owner:
                    first = owner[ident]
                    found.append((path, line["_id"], "id {} is reused; it is already at {}:{}. An id is never reused, even once retired".format(
                        ident, first[0], first[1])))
                else:
                    owner[ident] = (path, line["_id"])
                    lines[ident] = (path, line)
    return lines


def base_lines(paths, base, top=None):
    """Every line in the files under PATHS as they were at BASE, by id. A path gone from the checkout still counts."""
    lines = {}
    for root in paths:
        here = top or git_top(root) or git_top(os.path.dirname(os.path.abspath(root)))
        if not here:
            continue
        rel = os.path.relpath(os.path.realpath(root), here)
        listed = git(here, "ls-tree", "-r", "-z", "--name-only", base, "--", rel) or ""
        for name in listed.split("\0"):
            if not name.endswith((".yaml", ".yml")) or (name != rel and os.path.dirname(name) != rel):
                continue
            text = git(here, "show", "{}:{}".format(base, name))
            if text is None:
                continue
            doc = read(text, [], allow_alias=True)
            for line in (doc or {}).get("lines", []):
                if line.get("id") and line["id"] not in lines:
                    lines[line["id"]] = (os.path.join(here, name), line)
    return lines


def check(paths, base=None, top=None):
    """Every problem in the files under PATHS, as (path, line, words)."""
    found = []
    now = head_lines(paths, found)
    if base:
        for ident, (path, old) in sorted(base_lines(paths, base, top).items()):
            if ident not in now:
                found.append((path, old["_line"], "id {}, on this line before this branch, is gone. A line that stops being true is retired, never deleted: put it back with 'retired: <date>, <decision line>'".format(ident)))
                continue
            new_path, new = now[ident]
            if old.get("retired") and (not new.get("retired") or any(
                    old.get(k) != new.get(k) for k in ("action", "role", "kind"))):
                found.append((new_path, new["_id"], "id {} was retired before this branch ({}); a retired id is never reused or brought back: give the new line a new id".format(
                    ident, old.get("retired"))))
    return found


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
    """The page text for SOURCE_PATH as it would sit at PAGE_PATH, or (None, problems).

    The file must pass the same check the push gate runs on it, so no page is built from a file it refuses."""
    problems = [(n, words) for _, n, words in check([source_path])]
    if problems:
        return None, problems
    with open(source_path) as handle:
        doc = read(handle.read(), [])
    rel = os.path.relpath(os.path.realpath(source_path), os.path.dirname(os.path.realpath(page_path)))
    return render(doc, rel.replace(os.sep, "/")), []


def stamp_of(page_text):
    m = STAMP_TAG.search(page_text)
    return html.unescape(m.group(1)) if m else None


def stamp_source(page, stamp):
    """The file a page's stamp names, or None when the stamp is not a plain path beside the page, inside its repo."""
    if not stamp or any(not c.isprintable() for c in stamp) or os.path.isabs(stamp):
        return None
    source = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(page)), stamp))
    top = git_top(page) or os.path.realpath(os.path.dirname(os.path.abspath(page)))
    if os.path.commonpath([source, top]) != top:
        return None
    return source


def verify_page(page, allowed=None):
    """Each problem with the built page PAGE, as (line, words). ALLOWED, when given, is the files it may come from."""
    text, bad = read_text(page)
    if bad:
        return [bad]
    stamp = stamp_of(text)
    if stamp is None:
        return [(1, "this page was built from an abilities file and its stamp is gone. Build it again; a built page is never edited by hand")]
    source = stamp_source(page, stamp)
    if source is None:
        return [(1, "its stamp names '{}', which is not a file beside this page in this repo".format(clean(stamp)))]
    if not os.path.isfile(source):
        return [(1, "the abilities file it was built from, {}, is gone".format(clean(stamp)))]
    if allowed is not None and source not in allowed:
        return [(1, "it was built from {}, which PROJECT_ABILITIES does not name. Build it from a file the setting names".format(clean(stamp)))]
    fresh, problems = build(source, page)
    if fresh is None:
        return [(1, "its abilities file {} has problems, so the page cannot be rebuilt".format(clean(stamp)))]
    if fresh != text:
        old, new = text.splitlines(), fresh.splitlines()
        n = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
        command = " ".join(shlex.quote(w) for w in (
            "python3", os.path.abspath(__file__), "page", os.path.relpath(source), "-o", os.path.relpath(page)))
        return [(n + 1, "this page differs from a fresh build of {}. It is never edited by hand: change the file, then run: {}".format(
            clean(stamp), clean(command)))]
    return []


def find_base(top):
    """The commit this branch left from: origin/main first, as the push gate takes it, then origin/master, then origin's default."""
    for ref in ("origin/main", "origin/master", "origin/HEAD"):
        out = git(top, "merge-base", "HEAD", ref)
        if out and out.strip():
            return out.strip()
    return None


def gate(top, path, base):
    """What the push gate checks: every problem as (path, line, words), [] when the push touches no abilities file,
    or None when it touches one and PyYAML is missing."""
    top = os.path.realpath(top)
    path = os.path.realpath(path)
    files = {os.path.realpath(f) for f in files_in(path)}
    base = base or find_base(top)

    def listed(*args):
        out = (git(top, *args) or "").split("\0")
        return [os.path.realpath(os.path.join(top, n.strip("\n"))) for n in out if n.strip("\n")]

    # --no-renames lists a moved or renamed file under its old name too, so its ids are compared.
    changed = set(listed("diff", "--no-renames", "--name-only", "-z", "HEAD")) | \
        set(listed("ls-files", "--others", "--exclude-standard", "-z"))
    stamp = 'name="{}"'.format(STAMP)
    pages = set(listed("grep", "-l", "-z", "--fixed-strings", "-e", stamp, "--", "*.html"))
    if base:
        changed |= set(listed("diff", "--no-renames", "--name-only", "-z", base, "HEAD"))
        before = (git(top, "grep", "-l", "-z", "--fixed-strings", "-e", stamp, base, "--", "*.html") or "").split("\0")
        pages |= {os.path.realpath(os.path.join(top, n.split(":", 1)[1])) for n in before if ":" in n}
        # A page that carried a stamp at any commit on this branch is still a built page.
        pages |= set(listed("log", "-z", "--no-renames", "--format=", "--name-only", "-G", re.escape(stamp),
                            "{}..HEAD".format(base), "--", "*.html"))
    pages = {p for p in pages if os.path.isfile(p)}

    def ability(p):
        return p == path or (os.path.dirname(p) == path and p.endswith((".yaml", ".yml")))

    if not any(ability(p) or p in pages for p in changed):
        return []
    if yaml is None:
        return None
    found = check([path], base, top)
    if not base:
        found.append((path, 1, "no base branch was found (origin/main, origin/master or origin/HEAD), so deleted and reused ids could not be checked. Run 'git fetch origin' and push again"))
    for page in sorted(pages):
        found.extend((page, n, w) for n, w in verify_page(page, files))
    return found


def show(found, top=None):
    for path, n, words in found:
        name = os.path.relpath(path, top) if top else path
        print("{}:{}: {}".format(clean(name), n, clean(words)))


def main(argv):
    if not argv or argv[0] not in ("check", "page", "verify-page", "gate"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "gate":
        # The gate decides first whether the push touches an abilities file, so a push that does not needs no PyYAML.
        opts = dict(zip(args[::2], args[1::2]))
        if "--top" not in opts or "--path" not in opts:
            print("abilities gate: --top TOP --path PATH [--base REV]", file=sys.stderr)
            return 2
        found = gate(opts["--top"], opts["--path"], opts.get("--base"))
        if found is None:
            need_yaml()
        show(found, os.path.realpath(opts["--top"]))
        return 1 if found else 0
    need_yaml()
    if cmd == "check":
        base = None
        if args[:1] == ["--base"]:
            base, args = args[1], args[2:]
        if not args:
            print("abilities check: name a file or folder", file=sys.stderr)
            return 2
        found = [(p, 1, "does not exist") for p in args if not os.path.lexists(p)] + check(args, base)
        show(found)
        return 1 if found else 0
    if cmd == "page":
        if len(args) != 3 or args[1] != "-o":
            print("abilities page: FILE -o OUT", file=sys.stderr)
            return 2
        page, problems = build(args[0], args[2])
        if page is None:
            show((args[0], n, words) for n, words in problems)
            return 1
        with open(args[2], "w") as handle:
            handle.write(page)
        return 0
    if len(args) != 1:
        print("abilities verify-page: PAGE", file=sys.stderr)
        return 2
    problems = verify_page(args[0])
    show((args[0], n, words) for n, words in problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
