#!/usr/bin/env python3
"""PreToolUse and PostToolUse hook on the edit tools and Bash: while a scope file exists, refuse edits outside it and restore protected files a call changed."""
import base64
import json
import os
import re
import sys
import tempfile
import time

# The repo's state folder, from project_fact.py, with a default when it is absent.
try:
    from project_fact import state_dir as _state_dir
    STATE_DIR = _state_dir()
except Exception:
    STATE_DIR = ".claude/state"
SCOPE_REL = STATE_DIR + "/scope.json"
# Where reviewer and security-reviewer write their findings, whatever the task's scope.
REVIEW_STATE_RELS = (STATE_DIR + "/review",)
SELF_PROTECTED = (".claude/hooks/scope-gate.py", ".claude/settings.json", ".claude/settings.local.json")
PROTECTED = (SCOPE_REL,) + SELF_PROTECTED
TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"}
EDIT_TOOLS = TOOLS - {"Bash"}
SNAP_DIR = os.path.join(tempfile.gettempdir(), "claude-scope-gate")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def fold(s):
    return s.casefold()


def scope_root(path):
    """The checkout above `path` whose scope governs it, or None."""
    d = os.path.abspath(path if os.path.isdir(path) else os.path.dirname(path))
    while True:
        git = os.path.join(d, ".git")
        if os.path.exists(git):
            if os.path.isfile(os.path.join(d, SCOPE_REL)):
                return d
            if os.path.isfile(git):
                return None  # a worktree is its own checkout
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def checkout_of(path):
    """The nearest directory above `path` that holds .git, or None."""
    d = os.path.abspath(path if os.path.isdir(path) else os.path.dirname(path))
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def repository_checkouts(cwd):
    """The main checkout and every worktree of the repository holding `cwd`."""
    top = checkout_of(cwd)
    if not top:
        return set()
    git = os.path.join(top, ".git")
    common = git
    if os.path.isfile(git):
        try:
            gitdir = open(git).read().split("gitdir:", 1)[1].strip()
        except (OSError, IndexError):
            return {top}
        gitdir = os.path.normpath(os.path.join(top, gitdir))
        common = os.path.dirname(os.path.dirname(gitdir)) if os.path.basename(os.path.dirname(gitdir)) == "worktrees" else gitdir
    found = {top}
    if os.path.basename(common) == ".git":
        found.add(os.path.dirname(common))
    wt = os.path.join(common, "worktrees")
    if os.path.isdir(wt):
        for name in os.listdir(wt):
            try:
                path = open(os.path.join(wt, name, "gitdir")).read().strip()
                found.add(os.path.dirname(os.path.normpath(path)))
            except OSError:
                pass
    return {os.path.realpath(p) for p in found}


def glob_to_regex(pattern):
    pattern = fold(pattern.strip())
    if pattern.endswith("/"):
        pattern += "**"
    pattern = pattern.strip("/")
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif pattern.startswith("**", i):
            out.append(".*"); i += 2
        elif c == "*":
            out.append("[^/]*"); i += 1
        elif c == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(c)); i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(rel, patterns):
    return any(glob_to_regex(p).match(fold(rel)) for p in patterns if p.strip())


def load_scope(root):
    path = os.path.join(root, SCOPE_REL)
    try:
        scope = json.load(open(path))
        allowed = scope.get("allowed_paths")
        forbidden = scope.get("forbidden_paths", [])
        for name, value in (("allowed_paths", allowed), ("forbidden_paths", forbidden)):
            if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
                raise ValueError(f"{name} must be a list of paths")
        return scope, path
    except Exception as e:
        deny(f"The scope file {path} does not parse ({e}), so every edit in this checkout is "
             "refused until it is fixed. Tell the user; only the user changes that file.")


def rel_under(path, root):
    rel = os.path.relpath(path, root)
    return None if rel == ".." or rel.startswith("../") else rel


def literal_allowed(scope):
    return {fold(p.strip().strip("/")) for p in scope["allowed_paths"]}


def user_protected():
    """The gate, its runner and the user settings that wire it, as absolute paths."""
    here = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return (os.path.join(here, "scope-gate.py"), os.path.join(here, "run.sh"),
            os.path.join(here, "hooks.json"),
            os.path.realpath(os.path.join(config, "settings.json")),
            os.path.realpath(os.path.join(config, "settings.local.json")))


def check_user_files(target, cwd):
    """While a scope file exists, refuse an edit-tool change to this gate, its runner or the user settings."""
    if not target:
        return
    real = os.path.realpath(target)
    guarded = {os.path.realpath(p) for p in user_protected()}
    if real not in guarded:
        return
    roots = protected_roots(cwd, None)
    if roots:
        deny(f"{target} enforces or wires the scope set in {os.path.join(roots[0], SCOPE_REL)}, "
             "so it is protected while that file exists. Say in one sentence why it needs "
             "changing and wait for the user.")


def check_edit(target, cwd):
    if not target:
        return
    if not os.path.isabs(target):
        target = os.path.join(cwd or os.getcwd(), target)
    logical = os.path.normpath(target)
    real = os.path.realpath(logical)
    for root in {r for r in (scope_root(logical), scope_root(real)) if r}:
        scope, scope_path = load_scope(root)
        rels = [r for r in (rel_under(real, os.path.realpath(root)), rel_under(logical, root)) if r]
        if not rels:
            continue
        primary = rels[0]
        folded = [fold(r) for r in rels]
        task = scope.get("task") or "this task"
        # Allow a write to the review folder when every spelling of the path, resolved ones included, lies inside it.
        real_rel = rel_under(real, os.path.realpath(root))
        if real_rel is not None and any(all(r.startswith(fold(state) + "/") for r in folded) for state in REVIEW_STATE_RELS):
            continue
        if fold(SCOPE_REL) in folded:
            deny(f"{scope_path} sets this task's scope and already exists, so only the user changes it. "
                 "If the scope is wrong, say so in one sentence and wait for the user.")
        for r in folded:
            if r in SELF_PROTECTED and r not in literal_allowed(scope):
                deny(f"{r} enforces or wires the scope for {task}, so it is protected while "
                     f"{scope_path} exists. The user can name it in allowed_paths if it must change.")
        if any(matches(r, scope.get("forbidden_paths") or []) for r in rels):
            deny(f"{primary} is forbidden by the scope for {task} ({scope_path}). Do not work around "
                 "this: report in one sentence why it needs changing and wait for the user.")
        if not matches(primary, scope["allowed_paths"]):
            deny(f"{primary} is outside the scope for {task} ({scope_path}), which allows: "
                 f"{', '.join(scope['allowed_paths'])}. Report in one sentence why it needs changing and "
                 "wait for the user; only the user widens the scope.")


def protected_roots(cwd, target):
    # Find the scoped checkouts for the call's folder and the session's own, so a call from elsewhere cannot skip the guard.
    roots = set()
    for start in {cwd or os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR") or ""}:
        if start:
            roots |= {c for c in repository_checkouts(start)
                      if os.path.isfile(os.path.join(c, SCOPE_REL))}
    for p in (target,):
        if p:
            r = scope_root(os.path.realpath(p))
            if r:
                roots.add(os.path.realpath(r))
    return sorted(roots)


def read_state(path):
    """(kind, payload): a regular file's bytes, a symlink's target, or absent."""
    if os.path.islink(path):
        return ["link", os.readlink(path)]
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return ["file", base64.b64encode(f.read()).decode()]
    return ["absent", None]


def snap_path(payload):
    key = f"{payload.get('session_id', 'nosession')}-{payload.get('tool_use_id', 'nocall')}"
    return os.path.join(SNAP_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")


def exempt_files(root):
    """Protected files the user named literally in allowed_paths; none when the scope file does not parse."""
    try:
        allowed = json.load(open(os.path.join(root, SCOPE_REL))).get("allowed_paths") or []
        named = {fold(p.strip().strip("/")) for p in allowed if isinstance(p, str)}
    except (OSError, ValueError, AttributeError):
        named = set()
    return sorted(named & set(SELF_PROTECTED))


def sweep():
    """Drop snapshot copies older than a day."""
    try:
        for name in os.listdir(SNAP_DIR):
            p = os.path.join(SNAP_DIR, name)
            if os.path.getmtime(p) < time.time() - 86400:
                os.unlink(p)
    except OSError:
        pass


def snapshot(payload, roots):
    state = {}
    for root in roots:
        # Snapshot each protected file, the user files by absolute path, for post() to restore.
        entries = {rel: read_state(os.path.join(root, rel))
                   for rel in PROTECTED + user_protected()}
        state[root] = {"exempt": exempt_files(root), "files": entries}
    if not state:
        return
    os.makedirs(SNAP_DIR, exist_ok=True)
    sweep()
    tmp = snap_path(payload) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, snap_path(payload))


def restore(path, saved):
    kind, data = saved
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        return False  # a folder now sits where the file was; leave it for a human
    if kind == "absent":
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if kind == "link":
        os.symlink(data, path)
    else:
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
    return True


def post(payload):
    path = snap_path(payload)
    try:
        state = json.load(open(path))
    except (OSError, ValueError):
        return
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    restored, stuck = [], []
    for root, entry in state.items():
        for rel, saved in entry["files"].items():
            if rel in entry["exempt"]:
                continue
            full = os.path.join(root, rel)
            if read_state(full) == saved:
                continue
            (restored if restore(full, saved) else stuck).append(full)
    if not restored and not stuck:
        return
    msg = ("That call changed files that hold this task's scope or the gate that enforces it, "
           "and only the user changes those while a scope file exists.")
    if restored:
        msg += " Put back as they were before the call: " + ", ".join(restored) + "."
    if stuck:
        msg += " Could not put back (a folder now sits there), tell the user: " + ", ".join(stuck) + "."
    msg += " Do not try again another way; say in one sentence what you needed and wait for the user."
    print(json.dumps({"decision": "block", "reason": msg}))


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    tool = payload.get("tool_name")
    if tool not in TOOLS:
        return
    if len(sys.argv) > 1 and sys.argv[1] == "post":
        post(payload)
        return
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd")
    target = ti.get("file_path") or ti.get("notebook_path")
    if target and not os.path.isabs(target):
        target = os.path.join(cwd or os.getcwd(), target)
    if tool in EDIT_TOOLS:
        check_user_files(target, cwd)
        check_edit(target, cwd)
    snapshot(payload, protected_roots(cwd, target))


if __name__ == "__main__":
    main()
