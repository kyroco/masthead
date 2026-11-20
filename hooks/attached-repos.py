#!/usr/bin/env python3
"""attached-repos.py: in a cloud session, record each repository the session attached, so its hooks read that
repository's facts (MAST-48).

A cloud session, a Project thread among them, starts in a folder that holds its clones (/home/user), not in a
repository, so CLAUDE_PROJECT_DIR names no checkout and project_fact.trusted() refused them all: the push gate
printed "not this session's repository" and ran no check. This hook adds each attached repository's checkout to
the list trusted() reads (project_fact.cloud_repos_file), at two moments:

- SessionStart from startup: the checkouts in the session's folder before the session has run anything, which
  the cloud put there (the repositories the session started with, and what the environment's setup cloned).
- PostToolUse of register_repo_root: the clone of a repository the session attached with add_repo. The cloud
  answers it only for a repository in the session's sources, and the folder is recorded only when it is the top
  of a checkout whose origin is that GitHub repository.

A clone the session made itself, and a checkout found on resume, compact or clear, is never recorded: a fact
names a file to source or a script to run (Korium c394a752, rule 2). Outside a cloud session it does nothing.
Always exits 0 and prints nothing.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_fact  # noqa: E402


def is_checkout_top(path):
    """Whether `path` is the top folder of a git checkout."""
    return os.path.isdir(path) and os.path.exists(os.path.join(path, ".git")) and \
        project_fact.checkout_top(path) == os.path.realpath(path)


def origin_names(top, owner, repo):
    """Whether the origin of the checkout at `top` is github.com/<owner>/<repo>, read from its config file
    without running anything the repository could set."""
    config = os.path.join(project_fact.main_checkout(top) or top, ".git", "config")
    try:
        url = subprocess.run(["git", "config", "--file", config, "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return False
    found = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$",
                     url, re.IGNORECASE)
    return bool(found) and found.group(1).lower() == owner.lower() and found.group(2).lower() == repo.lower()


def at_start():
    """The checkouts in the session's folder: the folder itself when it is one, and each folder in it that is."""
    session = os.environ.get("CLAUDE_PROJECT_DIR") or ""
    if not os.path.isdir(session):
        return []
    found = [session] if is_checkout_top(session) else []
    for name in sorted(os.listdir(session)):
        path = os.path.join(session, name)
        if not os.path.islink(path) and is_checkout_top(path):
            found.append(path)
    return found


def registered(payload):
    """The folder a successful register_repo_root named, when it is the clone of the repository it names."""
    if not re.match(r"^mcp__.+__register_repo_root$", str(payload.get("tool_name") or "")):
        return []
    args = payload.get("tool_input") or {}
    owner, repo, directory = (str(args.get(key) or "") for key in ("owner", "repo", "directory"))
    if not (owner and repo and os.path.isabs(directory)) or os.path.islink(directory):
        return []
    if not is_checkout_top(directory) or not origin_names(directory, owner, repo):
        return []
    return [directory]


def main():
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    event = payload.get("hook_event_name")
    if event == "SessionStart":
        found = at_start() if payload.get("source") == "startup" else []
    elif event == "PostToolUse":
        found = registered(payload)
    else:
        found = []
    path = project_fact.cloud_repos_file()
    try:
        with open(path) as handle:
            known = {os.path.realpath(line.strip()) for line in handle if line.strip()}
    except OSError:
        known = set()
    new = [p for p in dict.fromkeys(os.path.realpath(p) for p in found) if p not in known]
    if not new:
        return 0
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as handle:
            handle.write("".join(p + "\n" for p in new))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
