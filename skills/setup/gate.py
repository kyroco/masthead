#!/usr/bin/env python3
"""Work out how a repository's Gate is run, and store the answer after one yes (INFRA-268).

The Gate is the GitHub Actions workflow that runs a repository's checks. The
batch run and the search for a bad commit both start it on a commit of their
choosing, so it must be startable on its own: by `workflow_call` (another
workflow uses it) or by `workflow_dispatch` (started by hand or by `gh`).

    gate.py look  [--root DIR]            what setup should say, as JSON; writes nothing
    gate.py store WORKFLOW [--root DIR]   write .claude/gate.json, after the person's yes

A workflow named Gate is the Gate; failing that, a workflow that runs on a
pull request or the merge queue, or a reusable workflow one of those runs.

`look` reads a stored answer first and never works the Gate out again while one
is stored (scenarios 2 and 4). Its "status" is one of:

    stored  the answer already stored; ask nothing
    found   one workflow is the Gate and can be started; ask for one yes
    choose  several workflows could be the Gate; ask which, the choice is the yes
    none    no Gate that can be started; the repository ships the old way

Nothing here changes how a repository ships unless `store` runs (scenario 5).
The stored file's shape is read by project_fact.py --gate and described in
references/gate-fact.md, for the batch run and the search to read.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "hooks"))
import project_fact  # noqa: E402

STARTS = project_fact.GATE_STARTS
GATE_WORDS = ("pull_request", "pull_request_target", "merge_group")
# A job that runs a reusable workflow of the same repository: `uses: ./.github/workflows/checks.yml`.
# Matched against one line at a time, its line end and comment already gone, the
# same cleaned line the trigger reader reads (SEC-R1-1, V3-S1-1, V3-S1-J1).
CALLS = re.compile(r"""^[ \t]*(?:-[ \t]+)?uses[ \t]*:[ \t]*['"]?\./(\.github/workflows/[A-Za-z0-9._-]+\.ya?ml)['"]?[ \t]*$""")


def calls(text):
    """The workflows of this repository that `text` runs with `uses: ./...`."""
    found = set()
    for line in text.splitlines():
        m = CALLS.match(strip_comment(line))
        if m:
            found.add(m.group(1))
    return found
OLD_WAY = "Masthead could not work out how this repository's Gate is run, so it keeps shipping the way it does today."


def unquote(word):
    word = word.strip()
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "'\"":
        word = word[1:-1]
    return word.strip()


def strip_comment(line):
    """A YAML line with a trailing comment removed, quotes respected."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def triggers(text):
    """The event names in a workflow's top-level `on:` key, as a set.

    Reads the forms GitHub documents: `on: push`, `on: [push, pull_request]`,
    and a block of keys or a block list under `on:`. YAML 1.1 reads a bare
    `on` key as true, so `true:` and quoted `"on":` count too.
    """
    # A byte order mark is not part of the first key (V-S1-2).
    lines = [strip_comment(l) for l in text.lstrip("\ufeff").splitlines()]
    for i, line in enumerate(lines):
        m = re.match(r"""^(on|'on'|"on"|true)\s*:\s*(.*)$""", line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest.startswith("["):
            return {unquote(w) for w in rest.strip("[]").split(",") if unquote(w)}
        if rest.startswith("{"):
            return {unquote(w.split(":")[0]) for w in rest.strip("{}").split(",") if unquote(w.split(":")[0])}
        if rest:
            return {unquote(rest)}
        found, indent = set(), None
        for child in lines[i + 1:]:
            if not child.strip():
                continue
            depth = len(child) - len(child.lstrip())
            body = child.strip()
            # YAML lets a list sit flush with its key: `on:` then `- push` (V-S1-2).
            if depth == 0 and not (indent in (None, 0) and body.startswith("- ")):
                break
            if indent is None:
                indent = depth
            if depth != indent:
                continue
            if body.startswith("- "):
                found.add(unquote(body[2:]))
            else:
                found.add(unquote(body.split(":")[0]))
        return found
    return set()


def workflow_name(text):
    for line in text.splitlines():
        m = re.match(r"^name\s*:\s*(.+)$", strip_comment(line))
        if m:
            return unquote(m.group(1))
    return ""


def workflows(top):
    """Each workflow file: its repo-relative path, name and triggers."""
    folder = os.path.join(top, ".github", "workflows")
    # A symlinked .github or workflows folder is not the repository's own, so nothing in it counts.
    for part in (os.path.join(top, ".github"), folder):
        if os.path.islink(part) or not os.path.isdir(part):
            return []
    try:
        leaves = sorted(os.listdir(folder))
    except OSError:
        return []
    found = []
    for leaf in leaves:
        rel = ".github/workflows/" + leaf
        if not project_fact.GATE_PATH.fullmatch(rel):
            continue
        text = project_fact.read_repo_file(top, rel, limit=1024 * 1024)
        if text is None:
            continue
        # A byte order mark is not part of the first key, whichever key it is (V-S1-2, V2-S1-1).
        text = text.lstrip("\ufeff")
        found.append({"workflow": rel, "name": workflow_name(text), "triggers": triggers(text),
                      "calls": calls(text)})
    return found


def is_gate_named(flow):
    stem = os.path.splitext(os.path.basename(flow["workflow"]))[0]
    return stem.lower() == "gate" or flow["name"].strip().lower() == "gate"


def answer(flow):
    return {"workflow": flow["workflow"], "name": flow["name"],
            "starts": sorted(flow["triggers"] & set(STARTS))}


def look(top):
    stored = project_fact.gate(top)
    if stored:
        return dict(stored, status="stored")
    flows = workflows(top)
    # A workflow named Gate is the Gate; failing that, what runs on a pull request or the merge queue.
    named = [f for f in flows if is_gate_named(f)]
    on_pull = [f for f in flows if f["triggers"] & set(GATE_WORDS)]
    # A pull-request workflow often hands its checks to a reusable one, which
    # workflow_call can start on its own (V-S1-J1).
    called = {c for f in on_pull for c in f["calls"]}
    candidates = named or on_pull + [f for f in flows if f["workflow"] in called and f not in on_pull]
    startable = [f for f in candidates if f["triggers"] & set(STARTS)]
    if not startable:
        if candidates:
            why = "{} cannot be started on its own: it has neither workflow_call nor workflow_dispatch.".format(
                ", ".join(f["workflow"] for f in candidates))
        else:
            why = "No workflow is named Gate, runs on a pull request or the merge queue, or is run by one."
        return {"status": "none", "why": why, "say": OLD_WAY}
    if len(startable) == 1:
        return dict(answer(startable[0]), status="found")
    return {"status": "choose", "choices": [answer(f) for f in startable]}


def store(top, workflow):
    flows = {f["workflow"]: f for f in workflows(top)}
    flow = flows.get(workflow)
    if not flow:
        return None, "{} is not a workflow file in .github/workflows.".format(workflow)
    record = answer(flow)
    if not record["starts"]:
        return None, "{} cannot be started on its own, so nothing was stored. {}".format(workflow, OLD_WAY)
    # Never write through a symlink a cloned repository committed (SEC-1): the
    # .claude folder must be a real folder, and gate.json a plain file or absent.
    folder = os.path.join(top, ".claude")
    if os.path.islink(folder) or (os.path.lexists(folder) and not os.path.isdir(folder)):
        return None, ".claude is not a plain folder in this repository, so nothing was stored. " + OLD_WAY
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(top, project_fact.GATE_FILE)
    refused = "{} is not a plain file, so nothing was stored. {}".format(project_fact.GATE_FILE, OLD_WAY)
    if os.path.lexists(path) and not project_fact.repo_file(top, project_fact.GATE_FILE):
        return None, refused
    body = json.dumps({"workflow": record["workflow"], "starts": record["starts"]}, indent=2) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except OSError:
        return None, refused
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    return record, None


def main(argv):
    root = os.getcwd()
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 >= len(argv):
            print("--root needs a folder", file=sys.stderr)
            return 2
        root = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    top = project_fact.checkout_top(root)
    # Setup runs this on the repository it was asked to set up, so that one is the session's.
    os.environ["CLAUDE_PROJECT_DIR"] = top
    if argv == ["look"]:
        print(json.dumps(look(top), indent=2))
        return 0
    if len(argv) == 2 and argv[0] == "store":
        record, error = store(top, argv[1])
        if error:
            print(error, file=sys.stderr)
            return 1
        print(json.dumps(record, indent=2))
        return 0
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: gate.py look | gate.py store WORKFLOW  [--root DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
