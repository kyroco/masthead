#!/usr/bin/env python3
"""Work out how a repository's Gate is run, and store the answer after one yes (INFRA-268).

The Gate is the GitHub Actions workflow that runs a repository's checks. The
batch run and the search for a bad commit both start it on a commit of their
choosing, so it must be startable on its own: by `workflow_call` (another
workflow uses it) or by `workflow_dispatch` (started by hand or by `gh`).

    gate.py look  [--root DIR]            what setup should say, as JSON; writes nothing
    gate.py store WORKFLOW [--root DIR]   write .claude/gate.json, after the person's yes
    gate.py starter [--root DIR]          print the batch run's starter file for the stored Gate (INFRA-270)
    gate.py snags [--root DIR]            the stored Gate's lines a batch run would miss, as JSON; writes nothing (INFRA-283)
    gate.py documents [--root DIR]        the stored document paths, or what to ask, as JSON; writes nothing (INFRA-287)
    gate.py documents --store PATTERN... | --none [--root DIR]
                                          store which paths hold only documents, after the person's yes (INFRA-287)

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
import fnmatch
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
        return dict(stored, status="stored", documents=stored_documents(top))
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


STARTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch-starter.yml")
# The scopes `read-all` covers, for merging it with a job that asks for one write.
SCOPES = ("actions", "attestations", "checks", "contents", "deployments", "discussions", "issues",
          "packages", "pages", "pull-requests", "security-events", "statuses")
LEVELS = {"none": 0, "read": 1, "write": 2}
# A Gate job that names no permissions takes its caller's: give it GitHub's
# restricted default, so a grant that names other scopes does not take its checkout away.
UNDECLARED = {"contents": "read", "packages": "read"}


def children(lines, i):
    """The indices of the lines nested under line i."""
    indent = len(lines[i]) - len(lines[i].lstrip())
    found = []
    for j in range(i + 1, len(lines)):
        if not lines[j].strip():
            continue
        if len(lines[j]) - len(lines[j].lstrip()) <= indent:
            break
        found.append(j)
    return found


def keys(lines, idx):
    """The (index, key, rest) of each key at the first level of the nested lines `idx`."""
    if not idx:
        return []
    depth = min(len(lines[j]) - len(lines[j].lstrip()) for j in idx)
    found = []
    for j in idx:
        line = lines[j]
        if len(line) - len(line.lstrip()) == depth and ":" in line:
            key, rest = line.strip().split(":", 1)
            found.append((j, unquote(key), rest.strip()))
    return found


def permission(lines, i, rest):
    """A `permissions:` value: "read-all", "write-all", or {scope: level}."""
    if rest.startswith("{"):
        pairs = [p.split(":", 1) for p in rest.strip().strip("{}").split(",") if ":" in p]
        return {unquote(k): unquote(v) for k, v in pairs}
    if rest:
        return unquote(rest)
    return {key: unquote(value) for _, key, value in keys(lines, children(lines, i))}


def asked_permissions(text, read=None, seen=frozenset()):
    """What each job of a workflow asks of the token: one entry per job, its own or the workflow's.

    A job that names none and runs a workflow of the same repository passes its
    caller's grant down, so what that workflow's jobs ask counts instead, read
    with `read(path)` and followed to any depth, each file once (arch-1, round 1).
    """
    lines = [strip_comment(l) for l in text.lstrip("﻿").splitlines()]
    top, jobs = None, None
    for i, line in enumerate(lines):
        m = re.match(r"^(permissions|jobs)\s*:\s*(.*)$", line)
        if m and m.group(1) == "permissions":
            top = permission(lines, i, m.group(2).strip())
        elif m:
            jobs = i
    asks = []
    if jobs is not None:
        for j, _, _ in keys(lines, children(lines, jobs)):
            body = keys(lines, children(lines, j))
            own = [permission(lines, k, rest) for k, key, rest in body if key == "permissions"]
            if own or top is not None:
                asks.append(own[0] if own else top)
                continue
            called = [unquote(rest)[2:] for _, key, rest in body
                      if key == "uses" and unquote(rest).startswith("./.github/workflows/")]
            inner = read(called[0]) if called and read and called[0] not in seen else None
            if inner is None:
                asks.append(None)
            else:
                asks.extend(asked_permissions(inner, read, seen | {called[0]}))
    if not asks:
        asks.append(top)
    return [UNDECLARED if ask is None else ask for ask in asks]


def grant(text, read=None):
    """The permissions the starter's Gate job grants: the strongest level each Gate job asks for.

    A called workflow may ask for no more than its caller job grants, or GitHub
    refuses the whole run before any job starts (arch-1). Written as one line.
    """
    asks = asked_permissions(text, read)
    if "write-all" in asks:
        return "write-all"
    merged = {}
    for ask in asks:
        if ask == "read-all":
            ask = {scope: "read" for scope in SCOPES}
        if not isinstance(ask, dict):
            continue
        for scope, level in ask.items():
            if LEVELS.get(level, 0) > LEVELS.get(merged.get(scope, "none"), 0):
                merged[scope] = level
    if not merged:
        return "{}"
    return "{ " + ", ".join("{}: {}".format(s, merged[s]) for s in sorted(merged)) + " }"


def starter(top):
    """The batch run's starter file for this repository, from its stored Gate, or (None, why)."""
    stored = project_fact.gate(top)
    if not stored:
        return None, "No Gate is stored in .claude/gate.json, so there is no batch run to start. " + OLD_WAY
    if "workflow_call" not in stored["starts"]:
        return None, "{} cannot be started with workflow_call, which is how the batch run starts it. {}".format(
            stored["workflow"], OLD_WAY)
    text = project_fact.read_repo_file(top, stored["workflow"], limit=1024 * 1024)
    if text is None:
        return None, "{} is not a plain file in this repository. {}".format(stored["workflow"], OLD_WAY)
    with open(STARTER, encoding="utf-8") as handle:
        template = handle.read()
    def read(path):
        return project_fact.read_repo_file(top, path, limit=1024 * 1024)

    permissions = grant(text, read)
    return template.replace("__GATE_PERMISSIONS__", permissions).replace("__GATE__", stored["workflow"]), None


# What a batch run looks like from inside the Gate (INFRA-283, Korium 601448c5):
# Kyroco's first batch run showed three things a Gate that routes by event misses.
# Since INFRA-285 a batch run starts on a go, as a workflow_dispatch run on
# landing, never on a push, so a batch arm keyed on a push is never true.
# Since INFRA-286 a hotfix has its own pile, so a batch run is on landing or on
# hotfix, and a batch arm that names landing alone misses a hotfix's run.
# Each rule reads what a line does (a test, a lookup of a name), never a line that
# only declares a trigger or names a job, and a line with the fix beside it is
# taken as fixed, the way its message says to fix it.
BATCH_MATCH = ("(github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/landing' && "
               "endsWith(github.workflow_ref, '/.github/workflows/masthead-batch.yml@refs/heads/landing')) || "
               "(github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/hotfix' && "
               "endsWith(github.workflow_ref, '/.github/workflows/masthead-batch.yml@refs/heads/hotfix'))")
MISSES = {
    "event": ("In a batch run github.workflow_ref names masthead-batch.yml, the starter that calls the Gate, not "
              "the Gate, so this test is false for a batch run. Add a batch arm beside it: " + BATCH_MATCH + "."),
    "push": ("A batch run no longer starts on a push to landing: it starts when the person says go, as a "
             "workflow_dispatch run on landing, so this arm is never true. Replace it with: " + BATCH_MATCH + "."),
    "base": ("A batch run starts on a go, not a push, so github.event.before is empty and a diff from it does not "
             "see the batch. Diff a batch run against main instead, as a run started by hand does."),
    "job": ("Under the starter this check is named \"gate / {name}\": the starter's job gate calls the Gate's "
            "job {name}. A lookup of \"{name}\" alone does not see a batch run. Match both names."),
    "run": ("A batch run is named \"Masthead batch\", not \"{name}\", so a test for that name does not see a "
            "batch run. Match both names."),
    "helper": ("A batch run is named \"Masthead batch\", not by the Gate's own name, so this workflow_run helper "
               "never starts after a batch. List \"Masthead batch\" beside the Gate's name."),
    "hotfix": ("A hotfix has its own pile, and its batch run is on refs/heads/hotfix, with a workflow_ref "
               "ending masthead-batch.yml@refs/heads/hotfix, so a batch arm that matches landing alone misses "
               "it. Match both piles: " + BATCH_MATCH + "."),
    "landing-push": ("This workflow starts on every push to landing, so each change a worker lands runs it and "
                     "uses minutes, outside the batch run, which starts only on a go. To keep it off landing, add "
                     "branches-ignore: [landing] under its push trigger, or list only the branches it should run on."),
    "main-push": ("This workflow starts on every push to main, so when the batch run moves main it runs again on "
                  "the commit the batch run just proved, or on a pile of only documents. If it tests, keep it off main "
                  "with branches-ignore: [main] under its push trigger; if it deploys or releases, leave it."),
}
SNAG_EVENT = re.compile(r"\bgithub\.workflow_ref\b")
# A test for a push: the batch arm INFRA-283 advised, when it sits by a test for landing or the starter.
SNAG_PUSH = re.compile(r"""event_name\s*==\s*['"]push['"]""")
PUSH_ARM = ("refs/heads/landing", "masthead-batch")
SNAG_BASE = re.compile(r"github\.event\.before\b")
# A batch arm written before a hotfix had its own pile: it names the starter on landing alone (INFRA-286).
SNAG_HOTFIX = re.compile(r"masthead-batch\.yml@refs/heads/landing")
# A lookup of a check or run by name: check_name=test, check-name: test, context: test, .name == "test".
SNAG_LOOKUP = re.compile(r"""\b(?:check_name|check-name|context)\s*[=:]\s*['"]?([^\s&"'),]+)|\bname\s*==\s*(['"])(.*?)\2""",
                         re.I)
# What, this many lines away or nearer, shows a line already has its fix beside it.
NEAR = 4
FIXED = {"event": ("masthead-batch.yml",), "base": ("masthead-batch.yml",)}

def trigger_lines(lines):
    """The indices of the top-level `on:` key and every line under it: they declare, they test nothing."""
    for i, line in enumerate(lines):
        if re.match(r"""^(on|'on'|"on"|true)\s*:""", line):
            return {i, *children(lines, i)}
    return set()


def job_names(text):
    """Each job's key and display name in a workflow, lowercased: what its checks are named for."""
    lines = [strip_comment(l) for l in text.splitlines()]
    found = set()
    for i, line in enumerate(lines):
        if re.match(r"^jobs\s*:\s*$", line):
            for j, key, _ in keys(lines, children(lines, i)):
                found.add(key.lower())
                found.update(unquote(rest).lower() for _, k, rest in keys(lines, children(lines, j))
                             if k == "name" and unquote(rest))
    return found


def workflow_run_lists(text):
    """(line number, names) of each `workflows:` list in a workflow_run trigger."""
    lines = [strip_comment(l) for l in text.lstrip("﻿").splitlines()]
    found = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s*workflows\s*:\s*(.*)$", line)
        if not m:
            continue
        rest = m.group(1).strip()
        if rest.startswith("["):
            names = [unquote(w) for w in rest.strip("[]").split(",") if unquote(w)]
        elif rest:
            names = [unquote(rest)]
        else:
            names = [unquote(lines[j].strip()[2:]) for j in children(lines, i) if lines[j].strip().startswith("- ")]
        found.append((i + 1, names))
    return found


def items(lines, i):
    """The indices of a block list's items under the key on line i. YAML lets the list sit deeper than
    its key or flush with it (`branches:` then `- main` at the same indent); both are read (s1-C2)."""
    indent = len(lines[i]) - len(lines[i].lstrip())
    found = []
    for j in range(i + 1, len(lines)):
        body = lines[j].strip()
        if not body:
            continue
        depth = len(lines[j]) - len(lines[j].lstrip())
        if depth < indent or (depth == indent and not body.startswith("- ")):
            break
        if body.startswith("- "):
            found.append(j)
    return found


def pattern_list(lines, i, rest):
    """The values of a `branches:`-like key: a flow list, one value, or a block list under it."""
    if rest.startswith("["):
        return [unquote(w) for w in rest.strip("[]").split(",") if unquote(w)]
    if rest:
        return [unquote(rest)]
    return [unquote(lines[j].strip()[2:]) for j in items(lines, i)]


def matches(branch, patterns):
    """Whether GitHub's branch filter `patterns` takes `branch`: later patterns win, and ! takes one away."""
    taken = False
    for p in patterns:
        if p.startswith("!"):
            if fnmatch.fnmatchcase(branch, p[1:]):
                taken = False
        elif fnmatch.fnmatchcase(branch, p):
            taken = True
    return taken


def push_to(text, branch):
    """The line number of a workflow's push trigger when it starts on a push to `branch`, or None."""
    lines = [strip_comment(l) for l in text.lstrip("\ufeff").splitlines()]
    for i, line in enumerate(lines):
        m = re.match(r"""^(on|'on'|"on"|true)\s*:\s*(.*)$""", line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest:
            # `on: push` or `on: [push, ...]`: every push, every branch. A flow map is read the same way.
            words = {unquote(w.split(":")[0]) for w in rest.strip("[]{}").split(",")}
            return i + 1 if "push" in words else None
        under = children(lines, i)
        for j in items(lines, i):
            if lines[j].strip() in ("- push", "- 'push'", '- "push"'):
                return j + 1  # a block list of events: every push, every branch
        for j, key, value in keys(lines, under):
            if key != "push":
                continue
            if value and not value.startswith("{"):
                return j + 1
            filters = {k: pattern_list(lines, n, v) for n, k, v in keys(lines, children(lines, j))}
            if "branches" in filters:
                return j + 1 if matches(branch, filters["branches"]) else None
            if "branches-ignore" in filters:
                return None if any(fnmatch.fnmatchcase(branch, p) for p in filters["branches-ignore"]) else j + 1
            if "tags" in filters or "tags-ignore" in filters:
                return None  # a push filtered by tags alone never starts on a branch
            return j + 1
        return None
    return None


def snags(top):
    """The lines of the stored Gate, what it calls, and its workflow_run helpers that a batch run would miss,
    and each workflow of the repository that starts on every push to landing (INFRA-285 s1-C2)."""
    stored = project_fact.gate(top)
    if not stored:
        return {"status": "none", "snags": [], "read": [],
                "say": "No Gate is stored in .claude/gate.json, so there is no Gate to read."}

    def read(rel):
        return project_fact.read_repo_file(top, rel, limit=1024 * 1024)

    texts, todo = {}, [stored["workflow"]]
    while todo:
        rel = todo.pop()
        if rel in texts or not project_fact.GATE_PATH.fullmatch(rel):
            continue
        text = read(rel)
        if text is None:
            continue
        texts[rel] = text.lstrip("﻿")
        todo.extend(sorted(calls(texts[rel])))
    gate_text = texts.get(stored["workflow"], "")
    gate_name = workflow_name(gate_text) if gate_text else ""
    names = {n.lower() for n in (gate_name, "Gate") if n}
    jobs = job_names(gate_text)
    helpers = []
    for flow in workflows(top):
        if "workflow_run" not in flow["triggers"] or flow["workflow"] in texts:
            continue
        text = read(flow["workflow"]) or ""
        for line, listed in workflow_run_lists(text):
            lowered = {n.lower() for n in listed}
            if lowered & names:
                texts[flow["workflow"]] = text.lstrip("﻿")
                if "masthead batch" not in lowered:
                    helpers.append((flow["workflow"], line))
    found = []
    for rel in sorted(texts):
        raw = texts[rel].splitlines()
        lines = [strip_comment(l) for l in raw]
        declared = trigger_lines(lines)
        for i, line in enumerate(lines):
            if not line.strip() or i in declared:
                continue
            near = " ".join(lines[max(0, i - NEAR):i + NEAR + 1]).lower()

            def fixed(kind):
                return any(word in near for word in FIXED[kind])

            hits = []
            if SNAG_EVENT.search(line) and not fixed("event"):
                hits.append(("event", MISSES["event"]))
            if SNAG_PUSH.search(line) and any(word in near for word in PUSH_ARM):
                hits.append(("push", MISSES["push"]))
            if SNAG_BASE.search(line) and not fixed("base"):
                hits.append(("base", MISSES["base"]))
            if SNAG_HOTFIX.search(line) and "hotfix" not in near:
                hits.append(("hotfix", MISSES["hotfix"]))
            # A name lookup is fixed only by a lookup of the batch's own name for it
            # nearby, never by the words in a workflows: list (arch-1, round 2).
            for m in SNAG_LOOKUP.finditer(line):
                name = (m.group(1) or m.group(3) or "").strip()
                run_test = m.group(3) is not None and line[:m.start()].lower().endswith("workflow_run.")
                if run_test or (name.lower() in names and name.lower() not in jobs):
                    if name.lower() in names and not re.search(r"==\s*['\"]masthead batch['\"]", near):
                        hits.append(("check", MISSES["run"].format(name=name)))
                elif name.lower() in jobs and "gate / " + name.lower() not in near:
                    hits.append(("check", MISSES["job"].format(name=name)))
            for kind, misses in hits:
                found.append({"workflow": rel, "line": i + 1, "kind": kind, "text": raw[i].strip(),
                              "misses": misses})
    for rel, line in helpers:
        found.append({"workflow": rel, "line": line, "kind": "helper",
                      "text": texts[rel].splitlines()[line - 1].strip(), "misses": MISSES["helper"]})
    # A batch run starts only on a go, but any other workflow that runs on a push still runs on each landing.
    for flow in workflows(top):
        if flow["workflow"] == project_fact.STARTER_FILE or "push" not in flow["triggers"]:
            continue
        text = read(flow["workflow"]) or ""
        for branch, kind in (("landing", "landing-push"), ("main", "main-push")):
            line = push_to(text, branch)
            if line:
                found.append({"workflow": flow["workflow"], "line": line, "kind": kind,
                              "text": text.lstrip("\ufeff").splitlines()[line - 1].strip(),
                              "misses": MISSES[kind]})
    found.sort(key=lambda s: (s["workflow"], s["line"], s["kind"]))
    return {"status": "snags" if found else "clear", "snags": found, "read": sorted(texts)}


def store(top, workflow):
    flows = {f["workflow"]: f for f in workflows(top)}
    flow = flows.get(workflow)
    if not flow:
        return None, "{} is not a workflow file in .github/workflows.".format(workflow)
    record = answer(flow)
    if not record["starts"]:
        return None, "{} cannot be started on its own, so nothing was stored. {}".format(workflow, OLD_WAY)
    # Storing the Gate again keeps the document paths the person already gave (INFRA-287 s3).
    written = {"workflow": record["workflow"], "starts": record["starts"]}
    kept = stored_documents(top)
    if kept is not None:
        written["documents"] = kept
    _, error = write_gate_json(top, written)
    if error:
        return None, error
    return record, None


def write_gate_json(top, record):
    """Write .claude/gate.json. Never through a symlink a cloned repository committed (SEC-1): the
    .claude folder must be a real folder, and gate.json a plain file or absent."""
    folder = os.path.join(top, ".claude")
    if os.path.islink(folder) or (os.path.lexists(folder) and not os.path.isdir(folder)):
        return None, ".claude is not a plain folder in this repository, so nothing was stored. " + OLD_WAY
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(top, project_fact.GATE_FILE)
    refused = "{} is not a plain file, so nothing was stored. {}".format(project_fact.GATE_FILE, OLD_WAY)
    if os.path.lexists(path) and not project_fact.repo_file(top, project_fact.GATE_FILE):
        return None, refused
    body = json.dumps(record, indent=2) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except OSError:
        return None, refused
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    return record, None


# ---- Which paths hold only documents (INFRA-287) ------------------------------
# Robert, November 19, 2026: "Why do we run ANYTHING for a document commit? Why?" Setup asks once
# and stores the answer beside the Gate; the batch run reads it from main and runs no Gate for a pile
# that changes only those paths. It is never guessed on a run (the project description, decision 4).

def stored_documents(top):
    """The document patterns stored in .claude/gate.json: a list, empty when the person said none, or None
    when they were never asked (or the stored list cannot be read), so setup asks once."""
    return project_fact.document_patterns(project_fact.read_repo_file(top, project_fact.GATE_FILE))


# What setup offers, for the person to change before the yes: a docs folder and the plain text files at
# the top of the repository, each named on its own, since * reaches into every folder.
TOP_DOCUMENTS = re.compile(r"(?i)^((readme|changelog|changes|history|contributing|code_of_conduct|security|support|"
                           r"authors|notice|license|licence|copying)(\.(md|markdown|txt|rst))?|.+\.(md|markdown|rst))$")
DOC_FOLDERS = ("docs", "doc", "documentation")


def suggest_documents(top):
    found = []
    for folder in DOC_FOLDERS:
        full = os.path.join(top, folder)
        if os.path.isdir(full) and not os.path.islink(full):
            found.append(folder + "/*")
    try:
        leaves = sorted(os.listdir(top))
    except OSError:
        leaves = []
    for leaf in leaves:
        full = os.path.join(top, leaf)
        if os.path.isfile(full) and not os.path.islink(full) and TOP_DOCUMENTS.match(leaf) \
                and project_fact.good_document_pattern(leaf):
            found.append(leaf)
    return found


def documents(top):
    """What setup says about document paths: the stored answer, or what to ask."""
    if not project_fact.gate(top):
        return {"status": "none", "say": "No Gate is stored, so there is no Gate run to skip for documents."}
    stored = stored_documents(top)
    if stored is not None:
        return {"status": "stored", "documents": stored}
    return {"status": "ask", "suggest": suggest_documents(top), "never": list(project_fact.NEVER_DOCUMENTS)}


def store_documents(top, patterns):
    """Write the document patterns into .claude/gate.json beside the stored Gate, after the person's yes.
    An empty list records that no path holds only documents, so setup does not ask again."""
    stored = project_fact.gate(top)
    if not stored:
        return None, "No Gate is stored in .claude/gate.json, so there is nowhere to store document paths. " + OLD_WAY
    bad = [p for p in patterns if not project_fact.good_document_pattern(p)]
    if bad:
        return None, ("{} {} not a path pattern Masthead reads: use letters, digits, . _ - + @ and /, with * for any "
                      "run of characters and ? for one, with a letter or digit, not starting with /. Nothing was "
                      "stored.").format(", ".join(repr(p) for p in bad), "is" if len(bad) == 1 else "are")
    # A pattern that reaches .github/ or gate.json is stored as given: those paths are never documents
    # (project_fact.NEVER_DOCUMENTS), whatever a pattern says.
    unique = []
    for p in patterns:
        if p not in unique:
            unique.append(p)
    return write_gate_json(top, {"workflow": stored["workflow"], "starts": stored["starts"], "documents": unique})


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
    if argv == ["snags"]:
        print(json.dumps(snags(top), indent=2))
        return 0
    if argv == ["documents"]:
        print(json.dumps(documents(top), indent=2))
        return 0
    if argv[:1] == ["documents"] and (argv[1:] == ["--none"] or (len(argv) > 2 and argv[1] == "--store")):
        record, error = store_documents(top, [] if argv[1] == "--none" else argv[2:])
        if error:
            print(error, file=sys.stderr)
            return 1
        print(json.dumps(record, indent=2))
        return 0
    if argv == ["starter"]:
        text, error = starter(top)
        if error:
            print(error, file=sys.stderr)
            return 1
        sys.stdout.write(text)
        return 0
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    print("usage: gate.py look | gate.py store WORKFLOW | gate.py starter | gate.py snags | "
          "gate.py documents [--store PATTERN... | --none]  [--root DIR]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
