#!/usr/bin/env python3
"""Split a codebase into review batches for /masthead:setup's architecture review, and keep track
of which batches were reviewed and judged, so a review too big for one session stops and says
what it left.

parts [--budget N]
        print each part of the codebase, one a line: its name, its files and its lines of code. A
        folder with more than N lines (default 6000) is split into its subfolders, and its own files
        become one part, "<folder>/*". Exit 3 when the repository holds no code.
plan --ledger L [--budget N] [--fresh] [PART ...]
        pack the code under the named folders or files (all of it when none is named; "<folder>/*"
        is that folder's own files) into batches of at most N lines, and write them to the ledger L
        as run 1. A file over N lines is read in ranges of N lines. Refuses (exit 4) when L already
        holds a batch not reviewed, unless --fresh.
resume --ledger L
        start the next run of a review left part done, in a new session.
next --ledger L
        write the first batch not reviewed to a list file, one entry a line ("<path>", or
        "<path>#L<a>-<b>" for a range of lines), and print the batch as JSON with the list's path.
        Exit 5 when every batch is reviewed, and exit 6 when this run has reviewed
        MAX_BATCHES_PER_SESSION batches already.
done --ledger L ID [FINDINGS ...]
        mark batch ID reviewed in this run, with the findings files its reviewers wrote.
findings --ledger L
        print the findings files of every batch reviewed and not yet judged, from any run.
judged --ledger L
        mark every reviewed batch judged.
left --ledger L
        print each part not reviewed yet, one a line; "nothing left" when every batch is done or
        no review was planned.
rules DOC
        print the doc's seven rules, one a line, as "<lens>: <the rule>".
builds DOC
        print each build the doc names under "What each build ships", one a line; exit 1 when it
        names none.

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
# Everything tracked counts as code except what is plainly not: docs, media, archives, binaries,
# licences, the lock files package managers write, and the dependencies a repository keeps. A
# folder named build, target or doc inside the code is code: only tracked files are read, and
# generated output is rarely tracked.
NOT_CODE_EXT = {
    ".md", ".markdown", ".txt", ".rst", ".adoc", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".webp", ".bmp", ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".zip", ".gz", ".tgz",
    ".tar", ".jar", ".mp3", ".mp4", ".mov", ".wav", ".lock", ".sum",
}
LOCK_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "npm-shrinkwrap.json", "go.sum"}
NOT_CODE_STEMS = {"license", "licence", "notice", "copying", "changelog", "authors"}
SKIP = {"node_modules", "vendor", ".git"}
# A .txt file is prose, except these, which hold builds and dependencies.
TXT_CODE = re.compile(r"^(cmakelists|requirements.*|constraints.*)\.txt$")
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


def is_code(path, data):
    parts = path.split("/")
    if any(p in SKIP for p in parts[:-1]):
        return False
    name = parts[-1]
    stem, ext = os.path.splitext(name.lower())
    if TXT_CODE.match(name.lower()):
        return b"\0" not in data[:8192]
    if name in LOCK_NAMES or ext in NOT_CODE_EXT or stem in NOT_CODE_STEMS:
        return False
    return b"\0" not in data[:8192]


def code_files(root):
    """{repo-relative path: lines} for each tracked code file."""
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, text=True)
    files = {}
    for path in out.stdout.split("\0"):
        full = os.path.join(root, path)
        if not path or os.path.islink(full) or not os.path.isfile(full):
            continue
        with open(full, "rb") as handle:
            data = handle.read()
        if is_code(path, data):
            files[path] = data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1) or 1
    return files


def entries(path, lines, budget):
    """The reviewer's entries for one file: the file, or ranges of `budget` lines when it is longer."""
    if lines <= budget:
        return [(path, lines)]
    return [("{}#L{}-{}".format(path, start, min(start + budget - 1, lines)), min(budget, lines - start + 1))
            for start in range(1, lines + 1, budget)]


def split(picked, every, folder, budget):
    """[(name, [entries], lines)] for the picked code under `folder` ("" is the top), split until
    each part fits. A part is named for a whole folder only when every code file in it was picked."""
    prefix = folder + "/" if folder else ""
    under = {p: n for p, n in picked.items() if p.startswith(prefix)}
    if not under:
        return []
    whole = len(under) == len([p for p in every if p.startswith(prefix)])
    total = sum(under.values())
    if folder and whole and total <= budget:
        return [(prefix + "**", sorted(under), total)]
    own = {p: n for p, n in under.items() if "/" not in p[len(prefix):]}
    subs = sorted({p[len(prefix):].split("/")[0] for p in under if p not in own})
    own_whole = len(own) == len([p for p in every if p.startswith(prefix) and "/" not in p[len(prefix):]])
    parts = []
    if own and own_whole and sum(own.values()) <= budget:
        parts.append((prefix + "*", sorted(own), sum(own.values())))
    else:
        for path, n in sorted(own.items()):
            parts += [(path, [entry], size) for entry, size in entries(path, n, budget)]
    for sub in subs:
        parts += split(picked, every, prefix + sub, budget)
    return parts


def picked(files, names):
    """({path: lines} under the folders and files `names` give, [names with no code under them]).
    "<folder>/*" is that folder's own files; "<folder>" and "<folder>/**" are all of it."""
    if not names:
        return dict(files), []
    out, unknown = {}, []
    for name in names:
        bare = re.sub(r"^\./", "", name.strip())
        if bare in ("", ".", "*", "**", "/"):
            hits = dict(files)
        elif bare.endswith("/*") and not bare.endswith("/**"):
            folder = bare[:-1]
            hits = {p: n for p, n in files.items() if p.startswith(folder) and "/" not in p[len(folder):]}
        else:
            bare = re.sub(r"(/\*\*)?/?$", "", bare)
            hits = {p: n for p, n in files.items() if p == bare or p.startswith(bare + "/")}
        if not hits:
            unknown.append(name)
        out.update(hits)
    return out, unknown


def batches(parts, budget):
    out, names, files, lines = [], [], [], 0
    for name, entry_list, n in parts:
        if names and lines + n > budget:
            out.append((names, files, lines))
            names, files, lines = [], [], 0
        names.append(name)
        files += entry_list
        lines += n
    if names:
        out.append((names, files, lines))
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


def collapse(parts):
    """The parts table: a file read in ranges is one row."""
    rows = []
    for name, entry_list, n in parts:
        if rows and rows[-1][0] == name:
            rows[-1] = (name, rows[-1][1], rows[-1][2] + n)
        else:
            rows.append((name, len({e.split("#L")[0] for e in entry_list}), n))
    return rows


def main(argv):
    if not argv:
        return usage()
    command, argv = argv[0], list(argv[1:])
    try:
        budget = int(option(argv, "--budget", DEFAULT_BUDGET))
    except ValueError:
        return usage()
    if budget < 1:
        return usage()
    ledger = option(argv, "--ledger")
    fresh = "--fresh" in argv
    argv = [a for a in argv if a != "--fresh"]

    if command == "parts" and not argv:
        files = code_files(top())
        if not files:
            print("this repository holds no code")
            return 3
        for name, count, lines in collapse(split(files, files, "", budget)):
            print("{}\t{} files\t{} lines".format(name, count, lines))
        return 0

    if command == "plan" and ledger:
        if os.path.exists(ledger) and not fresh:
            old = load(ledger)["batches"]
            if any(b["status"] != "done" for b in old):
                print("a review is part done in {}: run `left` to see what it has not reviewed, "
                      "`next` to go on, or plan again with --fresh to start over".format(ledger))
                return 4
            if any(not b.get("judged", True) for b in old):
                print("a review in {} was reviewed and not judged: judge what `findings` prints, "
                      "or plan again with --fresh to start over".format(ledger))
                return 4
        root = top()
        every = code_files(root)
        if not every:
            print("this repository holds no code")
            return 3
        chosen, unknown = picked(every, argv)
        if unknown:
            print("no code under: {}".format(", ".join(unknown)))
            return 2
        data = {"head": head(root), "budget": budget, "scope": argv or ["everything"], "run": 1,
                "batches": [{"id": i + 1, "parts": names, "files": files, "lines": n, "status": "todo"}
                            for i, (names, files, n) in enumerate(batches(split(chosen, every, "", budget), budget))]}
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
        batch = dict(todo[0])
        listing = os.path.abspath("{}-batch-{}.txt".format(os.path.splitext(ledger)[0], batch["id"]))
        with open(listing, "w") as handle:
            handle.write("".join(entry + "\n" for entry in batch["files"]))
        batch["list"] = listing
        print(json.dumps(batch))
        return 0

    if command == "done" and ledger and argv:
        data = load(ledger)
        try:
            wanted = int(argv[0])
        except ValueError:
            return usage()
        for batch in data["batches"]:
            if batch["id"] == wanted:
                batch.update(status="done", run=data["run"], findings=argv[1:], judged=False)
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

    if command == "findings" and ledger and not argv:
        for batch in load(ledger)["batches"]:
            if batch["status"] == "done" and not batch.get("judged"):
                for path in batch.get("findings", []):
                    print(path)
        return 0

    if command == "judged" and ledger and not argv:
        data = load(ledger)
        for batch in data["batches"]:
            if batch["status"] == "done":
                batch["judged"] = True
        save(ledger, data)
        return 0

    if command == "left" and ledger and not argv:
        if not os.path.exists(ledger):
            print("nothing left")
            return 0
        data = load(ledger)
        left = [p for b in data["batches"] if b["status"] != "done" for p in b["parts"]]
        for name in left:
            print(name)
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
        found = builds(lines, "What each build ships")
        for line in found:
            print(line)
        return 0 if found else 1

    return usage()


BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")


def builds(lines, name):
    """Each build under the heading `name`: a table's rows; each list item, with its wrapped lines
    and its sub-items; or each line, a line that starts in lower case after one that ends with no
    stop continuing it."""
    body = None
    for i, line in enumerate(lines):
        if re.match(r"^#+\s*" + re.escape(name) + r"\s*$", line.strip(), re.IGNORECASE):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith("#"):
                    break
                body.append(nxt)
            break
    if body is None:
        return []
    rows = [b.strip() for b in body if b.strip().startswith("|")]
    if rows:
        cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
        data = [c for c in cells[1:] if not all(re.match(r"^:?-+:?$", x) for x in c if x)]
        return ["{}: {}".format(c[0], ", ".join(x for x in c[1:] if x)) if len(c) > 1 else c[0] for c in data]
    items = [BULLET.match(b) for b in body]
    if any(items):
        top = min(len(m.group(1)) for m in items if m)
        found, subs = [], []
        for line, m in zip(body, items):
            if m and len(m.group(1)) == top:
                if found and subs:
                    found[-1] = found[-1].rstrip(" :") + ": " + ", ".join(subs)
                found.append(m.group(2).strip())
                subs = []
            elif m and found:
                subs.append(m.group(2).strip())
            elif line.strip() and found and line[:1].isspace():
                if subs:
                    subs[-1] += " " + line.strip()
                else:
                    found[-1] += " " + line.strip()
        if found and subs:
            found[-1] = found[-1].rstrip(" :") + ": " + ", ".join(subs)
        return found
    found = []
    for line in body:
        text = line.strip()
        if not text:
            continue
        if found and found[-1] is not None and text[:1].islower() and not re.search(r"[.;:!?]$", found[-1]):
            found[-1] += " " + text
        else:
            found.append(text)
    return found


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
