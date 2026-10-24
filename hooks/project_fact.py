#!/usr/bin/env python3
"""Read one fact about the repo a session is working in, from the env block of its .claude/settings.json."""
import json
import os
import sys


def project_root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def main_checkout(root):
    """The main checkout of the repository `root` is a worktree of, or None."""
    marker = os.path.join(root, ".git")
    # Skip a symlinked .git or one that is not a plain file: not a worktree.
    if os.path.islink(marker) or not os.path.isfile(marker):
        return None
    try:
        with open(marker) as handle:
            line = handle.read().strip()
        if not line.startswith("gitdir:"):
            return None
        gitdir = line.split(":", 1)[1].strip()
        if not os.path.isabs(gitdir):
            gitdir = os.path.join(root, gitdir)
        with open(os.path.join(gitdir, "commondir")) as handle:
            common = handle.read().strip()
        if not os.path.isabs(common):
            common = os.path.join(gitdir, common)
        common = os.path.realpath(common)
        # Check the back-link: the worktree record must point back at this .git, so a planted .git file cannot claim a repository.
        record = os.path.realpath(gitdir)
        if os.path.dirname(record) != os.path.join(common, "worktrees"):
            return None
        with open(os.path.join(record, "gitdir")) as handle:
            back = handle.read().strip()
        if os.path.realpath(back) != os.path.realpath(marker) or \
                os.path.realpath(os.path.dirname(back)) != os.path.realpath(root):
            return None
        main = os.path.dirname(common)
    except OSError:
        return None
    return None if os.path.realpath(main) == os.path.realpath(root) else main


def settings_fact(root, name):
    for leaf in ("settings.json", "settings.local.json"):
        try:
            with open(os.path.join(root, ".claude", leaf)) as handle:
                env = (json.load(handle) or {}).get("env") or {}
        except Exception:
            continue
        if env.get(name):
            return str(env[name])
    return None


def checkout_top(path):
    """The folder holding .git at or above `path`, or `path` itself."""
    d = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.realpath(path)
        d = parent


def repo_key(path):
    """One name for a repository whichever of its checkouts `path` is."""
    top = checkout_top(path)
    return os.path.realpath(main_checkout(top) or top)


def trusted(root):
    """Whether facts may be read from the checkout at `root`: only the session's own repository."""
    if not root:
        return False
    session = os.environ.get("CLAUDE_PROJECT_DIR")
    if session and repo_key(root) == repo_key(session):
        return True
    return cloud_cloned(root)


def cloud_cloned(root):
    """Whether `root` is in a repo the cloud session cloned at its start."""
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return False
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    try:
        with open(os.path.join(config, "cloud-session-repos")) as handle:
            cloned = {os.path.realpath(line.strip()) for line in handle if line.strip()}
    except OSError:
        return False
    return repo_key(root) in cloned


def fact(name, default=None, root=None):
    """The main checkout's fact for the repository `root` is in, else DEFAULT."""
    root = root or project_root()
    if not trusted(root):
        return default
    # A worktree's working tree is branch content, so only the main checkout's
    # settings supply a fact; a relative value still resolves in the worktree.
    value = settings_fact(main_checkout(root) or root, name)
    return value if value is not None else default


def fact_path(name, default=None, root=None):
    root = root or project_root()
    value = fact(name, default, root)
    if not value:
        return None
    path = os.path.expanduser(value)
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    return path if os.path.exists(path) else None


def plugin_root():
    """The Masthead install folder: CLAUDE_PLUGIN_ROOT as a plugin, else the folder above hooks/."""
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


STATE_DIR_FACT = "PROJECT_STATE_DIR"
STATE_DIR_DEFAULT = ".claude/state"


def state_dir(root=None):
    """The repo-relative folder the workflow keeps its per-checkout state in."""
    value = (fact(STATE_DIR_FACT, STATE_DIR_DEFAULT, root) or "").strip().strip("/")
    return value or STATE_DIR_DEFAULT


def main(argv):
    # --trusted CHECKOUT: exit 0 when the checkout is the session's repository, 1 when not.
    if len(argv) == 2 and argv[0] == "--trusted":
        return 0 if trusted(argv[1]) else 1
    root = None
    if len(argv) >= 2 and argv[0] == "--root":
        root, argv = argv[1], argv[2:]
    as_path = bool(argv) and argv[0] == "--path"
    if as_path:
        argv = argv[1:]
    if not argv:
        return 0
    name, default = argv[0], (argv[1] if len(argv) > 1 else None)
    value = fact_path(name, default, root) if as_path else fact(name, default, root)
    if value:
        print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
