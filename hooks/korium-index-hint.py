#!/usr/bin/env python3
"""PreToolUse helper for gate-discovery: print one line naming what the code index holds for the plain words of a search it let through; never refuses."""
import importlib.util
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

_spec = importlib.util.spec_from_file_location(
    "korium_index_judge", os.path.join(os.path.dirname(os.path.abspath(__file__)), "korium-index-judge.py"))
judge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(judge)

# Wait at most four seconds for the index lookup.
judge.LOOKUP_TIMEOUT_S = 4
MIN_LENGTH = 4
MAX_WORDS = 3
MAX_HITS = 3


def plain_words(pattern):
    out = []
    for word in sorted(judge.WORD.findall(judge.plain(pattern)), key=len, reverse=True):
        if len(word) >= MIN_LENGTH and word not in out:
            out.append(word)
    return out


def asked_file(state):
    return os.path.join(state, "index-hinted") if state else None


def already_asked(state):
    try:
        with open(asked_file(state)) as handle:
            return {line.strip() for line in handle}
    except (OSError, TypeError):
        return set()


def remember(state, words):
    if not state or not words:
        return
    try:
        with open(asked_file(state), "a") as handle:
            handle.write("".join(word + "\n" for word in words))
    except OSError:
        pass


VENDORED = ("/vendor/", "/deps/", "/node_modules/", "/_build/")
TEST_PATH = re.compile(r"(^|/)(test|tests|spec|fixtures)/|_test\.|\.test\.|_spec\.")


def usefulness(row):
    """Rank a hit for sorting: modules first, other code next, test files after, other kinds last."""
    rel = "/" + str(row.get("rel_path") or "")
    tested = TEST_PATH.search(rel) is not None
    if row.get("kind") == "other":
        return 3
    return 2 if tested else (0 if row.get("kind") == "module" else 1)


def names_word(row, word):
    fq = judge.bare(str(row.get("fq_name") or ""))
    return word.lower() in (judge.bare(part).lower() for part in fq.split("."))


def where(row):
    start, end = row.get("start_line"), row.get("end_line")
    lines = ""
    if start:
        lines = ":%s-%s" % (start, end) if end and end != start else ":%s" % start
    return ("%s (%s) at %s%s" % (row.get("fq_name"), row.get("kind") or "symbol",
                                 row.get("rel_path"), lines))[:200]


def hint(pattern, path, cwd, state):
    """Return the context line, or "". Never raises."""
    pattern = (pattern or "").strip()[:500]
    if not pattern or judge.names(pattern):
        return ""
    asked = already_asked(state)
    words = [word for word in plain_words(pattern) if word not in asked][:MAX_WORDS]
    if not words:
        return ""
    root = judge.search_root(path, cwd)
    if not root:
        return ""
    cli = judge.korium_cli()
    if not cli or not judge.signed_in(cli):
        return ""

    with ThreadPoolExecutor(max_workers=len(words)) as pool:
        asks = [(word, pool.submit(judge.lookup, cli, root, word)) for word in words]
    hits, answered, failed = [], [], False
    for word, future in asks:
        try:
            rows = future.result()
        except Exception:
            failed = True
            continue
        answered.append(word)
        for row in rows:
            key = (row.get("rel_path"), row.get("start_line"))
            if any(part in "/" + str(row.get("rel_path") or "") for part in VENDORED):
                continue
            if names_word(row, word) and key not in [(h.get("rel_path"), h.get("start_line")) for h in hits]:
                hits.append(row)
    if failed:
        judge.forget_status()
    remember(state, answered)
    if not hits:
        return ""
    hits.sort(key=usefulness)
    shown = "; ".join(where(row) for row in hits[:MAX_HITS])
    more = " (and %d more)" % (len(hits) - MAX_HITS) if len(hits) > MAX_HITS else ""
    return ("The code index holds names this search mentions: %s%s. If one is what you are "
            "after, read that span with offset and limit; for the code around it, ask "
            "code_locate with a query phrased toward the name." % (shown, more))


def main():
    try:
        data = json.load(sys.stdin)
        text = hint(data.get("pattern"), data.get("path"), data.get("cwd"), data.get("state"))
    except Exception:
        text = ""
    if text:
        print(text)
    sys.exit(0)


if __name__ == "__main__":
    main()
