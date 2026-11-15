#!/usr/bin/env python3
"""Split a codebase into review batches for /masthead:setup's architecture review, and keep track
of which batches were reviewed, so a sweep too big for one session stops and says what it left.

parts [--budget N]
        print each part of the codebase, one a line: its Glob pattern, its files and its lines of
        code. A folder with more than N lines (default 6000) is split into its subfolders, and its
        own files become one part, "<folder>/*". Exit 3 when the repository holds no code.
plan --ledger L [--budget N] [--fresh] [PART ...]
        pack the named parts (every part when none is named) into batches of at most N lines and
        write them to the ledger L, each one "todo", as run 1. A part is named by a folder or a
        file, and takes the code under it. Refuses (exit 4) when L already holds a batch not
        reviewed, unless --fresh.
resume --ledger L
        start the next run of a review left part done, in a new session.
next --ledger L
        print the first batch not reviewed, as JSON. Exit 5 when every batch is reviewed, and
        exit 6 when this run has reviewed MAX_BATCHES_PER_SESSION batches already.
done --ledger L ID [FINDINGS ...]
        mark batch ID reviewed in this run, with the findings files its reviewers wrote.
left --ledger L
        print each part not reviewed yet, one a line; "nothing left" when every batch is done.
rules DOC
        print the doc's seven rules, one a line, as "<lens>: <the rule>".
builds DOC
        print each build the doc names under "What each build ships", one a line.

Exit 2 is a usage error.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

DEFAULT_BUDGET = 6000
# One session sends three reviewers per batch and one judge per run. Past this many batches its
# room goes to reports instead of judging, so the rest waits for the next run, a new session.
MAX_BATCHES_PER_SESSION = 6
CODE_EXT = {
    ".py", ".rb", ".ex", ".exs", ".erl", ".hrl", ".heex", ".eex", ".leex", ".go", ".rs", ".js",
    ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte", ".java", ".kt", ".kts", ".scala",
    ".swift", ".m", ".mm", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".fs", ".php", ".sh",
    ".bash", ".zsh", ".sql", ".tf", ".lua", ".dart", ".clj", ".cljs", ".hs", ".ml", ".r",
    ".pl", ".toml", ".yml", ".yaml", ".gradle", ".proto", ".graphql",
}
CODE_NAMES = {"Makefile", "Dockerfile", "Rakefile", "Gemfile", "Justfile"}
SKIP = {"node_modules", "vendor", "deps", "_build", "target", "dist", "build", ".git", "docs", "doc"}
HERE = os.path.dirname(os.path.abspath(__file__))


def doc_module():
    spec = importlib.util.spec_from_file_location("architecture_doc", os.path.join(HERE, "architecture-doc.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def top():
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("architecture-sweep: not inside a git repository")
    return out.stdout.strip()


def head(root):
    out = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or None


def is_code(path):
    parts = path.split("/")
    if any(p in SKIP for p in parts[:-1]):
        return False
    name = parts[-1]
    return name in CODE_NAMES or os.path.splitext(name)[1].lower() in CODE_EXT


def code_files(root):
    """{repo-relative path: lines} for each tracked code file."""
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, text=True)
    files = {}
    for path in out.stdout.split("\0"):
        full = os.path.join(root, path)
        if not path or not is_code(path) or os.path.islink(full) or not os.path.isfile(full):
            continue
        with open(full, "rb") as handle:
            files[path] = handle.read().count(b"\n") or 1
    return files


def split(files, folder, budget):
    """[(pattern, files, lines)] for the code under `folder` ("" is the top), split until each fits."""
    prefix = folder + "/" if folder else ""
    under = {p: n for p, n in files.items() if p.startswith(prefix)}
    total = sum(under.values())
    if not under:
        return []
    if folder and total <= budget:
        return [(prefix + "**", len(under), total)]
    own = {p: n for p, n in under.items() if "/" not in p[len(prefix):]}
    subs = sorted({p[len(prefix):].split("/")[0] for p in under if p not in own})
    parts = []
    if own:
        if sum(own.values()) <= budget:
            parts.append((prefix + "*", len(own), sum(own.values())))
        else:  # the folder's own files alone are too big: each stands as its own part
            parts += [(p, 1, n) for p, n in sorted(own.items())]
    for sub in subs:
        parts += split(files, prefix + sub, budget)
    return parts


def picked(files, names):
    """({path: lines} under the folders and files `names` give, [names with no code under them])."""
    if not names:
        return dict(files), []
    out, unknown = {}, []
    for name in names:
        bare = re.sub(r"(^\./)|(/\*\*?$)|(/$)", "", name.strip())
        if bare in ("", ".", "*", "**"):
            hits = dict(files)
        else:
            hits = {p: n for p, n in files.items() if p == bare or p.startswith(bare + "/")}
        if not hits:
            unknown.append(name)
        out.update(hits)
    return out, unknown


def batches(parts, budget):
    out, current, lines = [], [], 0
    for pattern, _files, n in parts:
        if current and lines + n > budget:
            out.append((current, lines))
            current, lines = [], 0
        current.append(pattern)
        lines += n
    if current:
        out.append((current, lines))
    return out


def load(ledger):
    with open(ledger) as handle:
        return json.load(handle)


def save(ledger, data):
    os.makedirs(os.path.dirname(os.path.abspath(ledger)), exist_ok=True)
    tmp = ledger + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, ledger)


def option(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            raise SystemExit(usage())
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return default


def usage():
    print(__doc__.strip(), file=sys.stderr)
    return 2


def main(argv):
    if not argv:
        return usage()
    command, argv = argv[0], list(argv[1:])
    try:
        budget = int(option(argv, "--budget", DEFAULT_BUDGET))
    except ValueError:
        return usage()
    ledger = option(argv, "--ledger")
    fresh = "--fresh" in argv
    argv = [a for a in argv if a != "--fresh"]

    if command == "parts" and not argv:
        parts = split(code_files(top()), "", budget)
        if not parts:
            print("this repository holds no code")
            return 3
        for pattern, files, lines in parts:
            print("{}\t{} files\t{} lines".format(pattern, files, lines))
        return 0

    if command == "plan" and ledger:
        if os.path.exists(ledger) and not fresh:
            if any(b["status"] != "done" for b in load(ledger)["batches"]):
                print("a review is part done in {}: run `left` to see what it has not reviewed, "
                      "`next` to go on, or plan again with --fresh to start over".format(ledger))
                return 4
        root = top()
        files = code_files(root)
        if not files:
            print("this repository holds no code")
            return 3
        files, unknown = picked(files, argv)
        if unknown:
            print("no code under: {}".format(", ".join(unknown)))
            return 2
        data = {"head": head(root), "budget": budget, "scope": argv or ["everything"], "run": 1,
                "batches": [{"id": i + 1, "parts": ps, "lines": n, "status": "todo"}
                            for i, (ps, n) in enumerate(batches(split(files, "", budget), budget))]}
        save(ledger, data)
        count = len(data["batches"])
        print("{} batches, {} lines, at head {}".format(count, sum(b["lines"] for b in data["batches"]), data["head"]))
        if count > MAX_BATCHES_PER_SESSION:
            print("one session reviews {} batches; the other {} wait for the next run".format(
                MAX_BATCHES_PER_SESSION, count - MAX_BATCHES_PER_SESSION))
        return 0

    if command == "next" and ledger and not argv:
        data = load(ledger)
        todo = [b for b in data["batches"] if b["status"] != "done"]
        if not todo:
            print("every batch is reviewed")
            return 5
        mine = [b for b in data["batches"] if b.get("run") == data["run"]]
        if len(mine) >= MAX_BATCHES_PER_SESSION:
            print("this run has reviewed {} batches, one session's share; {} are left for the next run".format(
                len(mine), len(todo)))
            return 6
        print(json.dumps(todo[0]))
        return 0

    if command == "done" and ledger and argv:
        data = load(ledger)
        try:
            wanted = int(argv[0])
        except ValueError:
            return usage()
        for batch in data["batches"]:
            if batch["id"] == wanted:
                batch.update(status="done", run=data["run"], findings=argv[1:])
                save(ledger, data)
                return 0
        print("no batch {} in {}".format(wanted, ledger))
        return 2

    if command == "resume" and ledger and not argv:
        data = load(ledger)
        data["run"] = data.get("run", 1) + 1
        save(ledger, data)
        todo = [b for b in data["batches"] if b["status"] != "done"]
        print("run {}: {} of {} batches left, planned at head {}".format(
            data["run"], len(todo), len(data["batches"]), data["head"]))
        return 0

    if command == "left" and ledger and not argv:
        data = load(ledger)
        left = [p for b in data["batches"] if b["status"] != "done" for p in b["parts"]]
        for pattern in left:
            print(pattern)
        if not left:
            print("nothing left")
        return 0

    if command in ("rules", "builds") and len(argv) == 1:
        doc = doc_module()
        try:
            with open(argv[0]) as handle:
                lines = handle.read().splitlines()
        except OSError as err:
            print("architecture-sweep: cannot read {}".format(err.filename), file=sys.stderr)
            return 2
        if command == "rules":
            for lens in doc.LENSES:
                rule, _problem = doc.lens_rule(lines, lens)
                print("{}: {}".format(lens, rule or "not stated"))
            return 0
        found = section_lines(lines, "What each build ships")
        for line in found:
            print(line)
        return 0 if found else 1

    return usage()


def section_lines(lines, name):
    """The bullet lines (or, with none, the text lines) under the heading `name`."""
    for i, line in enumerate(lines):
        if re.match(r"^#+\s*" + re.escape(name) + r"\s*$", line.strip(), re.IGNORECASE):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith("#"):
                    break
                if nxt.strip():
                    body.append(nxt.strip())
            bullets = [re.sub(r"^[-*]\s+", "", b) for b in body if re.match(r"^[-*]\s", b)]
            return bullets or body
    return []


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
