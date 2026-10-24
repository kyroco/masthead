#!/usr/bin/env python3
"""Judge whether the code index holds the name a Grep, Glob or shell search is after, printing SEARCHABLE, NOT_SEARCHABLE or UNKNOWN (gate-discovery refuses on UNKNOWN); always exits 0."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

LOOKUP_TIMEOUT_S = 10
STATUS_TIMEOUT_S = 8
STATUS_TRUSTED_S = 600
MAX_NAMES = 3
MIN_LENGTH = 3

# File types the indexer does not read.
NOT_INDEXED = {".md", ".markdown", ".txt", ".log", ".jsonl", ".csv", ".tsv",
               ".html", ".htm", ".heex", ".tfvars", ".conf", ".svg"}

DEFINITION = re.compile(
    r"\b(?:def|defp|defmacro|defmacrop|defmodule|defguard|defdelegate|defprotocol|defimpl"
    r"|func|function|fn|class|struct|enum|interface|trait|impl|type|module|protocol"
    r"|resource|data|variable|output"
    r"|TABLE|FUNCTION|VIEW|INDEX|TRIGGER|PROCEDURE)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"\"?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*[?!]?)", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


class LookupFailed(Exception):
    pass


def korium_cli():
    found = shutil.which("korium-cli")
    if found:
        return found
    for path in ("/usr/local/bin/korium-cli", "/opt/homebrew/bin/korium-cli",
                 os.path.expanduser("~/.local/bin/korium-cli")):
        if os.access(path, os.X_OK):
            return path
    return None


def plain(pattern):
    """The pattern with regex escapes taken out, so its words can be read."""
    text = re.sub(r"\\([.\-_/:\"'])", r"\1", pattern)
    text = re.sub(r"\\[A-Za-z]", " ", text)
    return text.replace("\\", " ")


def code_shaped(word):
    core = word.strip("_")
    return ("_" in core or "." in word or re.search(r"[a-z][A-Z]", word) is not None)


def names(pattern):
    """The words of a Grep pattern worth asking the index about, best first."""
    text = plain(pattern)
    chosen = []
    for match in DEFINITION.finditer(text):
        chosen.append(match.group(1))
    shaped = sorted((w for w in WORD.findall(text) if code_shaped(w)), key=len, reverse=True)
    out = []
    for word in chosen + shaped:
        if len(word.rstrip("?!")) >= MIN_LENGTH and word not in out:
            out.append(word)
    return out[:MAX_NAMES]


def file_name(pattern):
    """The plain file name a Glob asks for, or None when its last part has a wildcard."""
    last = pattern.rstrip("/").split("/")[-1]
    if not last or any(c in last for c in "*?[{"):
        return None
    return last


def search_root(path, cwd):
    """The git repository the search runs in, or None when outside one or reading only a file the index does not hold."""
    base = cwd or os.getcwd()
    if path:
        target = os.path.expanduser(path)
        if not os.path.isabs(target):
            target = os.path.join(base, target)
        if os.path.isfile(target):
            if os.path.splitext(target)[1].lower() in NOT_INDEXED:
                return None
            target = os.path.dirname(target)
        while target and target != "/" and not os.path.isdir(target):
            target = os.path.dirname(target)
        base = target or base
    try:
        r = subprocess.run(["git", "-C", base, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def status_mark():
    return os.path.join(os.environ.get("TMPDIR") or "/tmp", "claude-engram", "korium-cli-signed-in")


def signed_in(cli):
    mark = status_mark()
    try:
        if time.time() - os.path.getmtime(mark) < STATUS_TRUSTED_S:
            return True
    except OSError:
        pass
    try:
        r = subprocess.run([cli, "status"], capture_output=True, text=True,
                           timeout=STATUS_TIMEOUT_S, stdin=subprocess.DEVNULL,
                           cwd=tempfile.gettempdir())
    except Exception:
        return False
    if r.returncode != 0:
        return False
    try:
        os.makedirs(os.path.dirname(mark), exist_ok=True)
        with open(mark, "w"):
            pass
    except OSError:
        pass
    return True


def forget_status():
    try:
        os.remove(status_mark())
    except OSError:
        pass


def lookup(cli, root, query):
    try:
        r = subprocess.run([cli, "search", "--json", "--limit", "10", "--repo-root", root, query],
                           capture_output=True, text=True, timeout=LOOKUP_TIMEOUT_S,
                           stdin=subprocess.DEVNULL)
    except Exception as error:
        raise LookupFailed(str(error))
    if r.returncode != 0:
        raise LookupFailed(r.stderr.strip() or r.stdout.strip())
    try:
        payload = json.loads(r.stdout)
    except ValueError as error:
        raise LookupFailed(str(error))
    if not isinstance(payload, dict):
        raise LookupFailed("not a JSON object")
    return payload.get("results") or []


def bare(name):
    return name.rstrip("?!")


def holds_name(rows, word):
    word = bare(word)
    for row in rows:
        fq = bare(str(row.get("fq_name") or ""))
        if "." in word:
            if fq == word or fq.endswith("." + word):
                return True
        elif word in (bare(part) for part in fq.split(".")):
            return True
    return False


def holds_file(rows, name):
    for row in rows:
        rel = str(row.get("rel_path") or "")
        if rel == name or rel.endswith("/" + name):
            return True
    return False


def judge(tool, pattern, path, cwd):
    """Return SEARCHABLE, NOT_SEARCHABLE or UNKNOWN. Never raises."""
    pattern = (pattern or "").strip()[:500]
    if not pattern:
        return "NOT_SEARCHABLE"
    if tool == "Glob":
        wanted = file_name(pattern)
        asks = [(os.path.splitext(wanted)[0], wanted)] if wanted else []
    else:
        asks = [(word, None) for word in names(pattern)]
    if not asks:
        return "NOT_SEARCHABLE"
    root = search_root(path, cwd)
    if not root:
        return "NOT_SEARCHABLE"
    cli = korium_cli()
    if not cli:
        return "NOT_SEARCHABLE"
    if not signed_in(cli):
        return "UNKNOWN"

    def one(ask):
        query, wanted_file = ask
        rows = lookup(cli, root, query)
        return holds_file(rows, wanted_file) if wanted_file else holds_name(rows, query)

    failed = False
    with ThreadPoolExecutor(max_workers=len(asks)) as pool:
        for future in [pool.submit(one, ask) for ask in asks]:
            try:
                if future.result():
                    return "SEARCHABLE"
            except Exception:
                failed = True
    if failed:
        forget_status()
        return "UNKNOWN"
    return "NOT_SEARCHABLE"


def main():
    try:
        data = json.load(sys.stdin)
        verdict = judge(data.get("tool"), data.get("pattern"), data.get("path"), data.get("cwd"))
    except Exception:
        verdict = "UNKNOWN"
    print(verdict)
    sys.exit(0)


if __name__ == "__main__":
    main()
