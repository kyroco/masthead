#!/usr/bin/env python3
"""Read one fact about the repo a session is working in, from the env block of its .claude/settings.json."""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile


def state_root():
    """The user's private folder for hook state, or None when it cannot be trusted.

    $CLAUDE_PLUGIN_DATA/state when that is set, else $TMPDIR/masthead-<uid>. Made with
    mode 0700; refused when it is a symlink or owned by someone else. Callers fail open.
    """
    try:
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        if data:
            root = os.path.join(data, "state")
        else:
            tmp = os.environ.get("TMPDIR") or tempfile.gettempdir()
            root = os.path.join(tmp, "masthead-{}".format(os.getuid()))
        try:
            os.makedirs(root, mode=0o700)
        except FileExistsError:
            pass
        info = os.lstat(root)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            return None
        if info.st_mode & 0o077:
            os.chmod(root, 0o700)
        return root
    except Exception:
        return None


def safe_session(value):
    """A session id reduced to [A-Za-z0-9_-], for use in a path."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or "")) or "nosession"


def private_dir(*parts):
    """A 0700 folder under the state root, or None. Never follows a symlink out of the root."""
    root = state_root()
    if not root:
        return None
    path = root
    try:
        for part in parts:
            path = os.path.join(path, part)
            try:
                os.mkdir(path, 0o700)
            except FileExistsError:
                pass
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                return None
            if info.st_mode & 0o077:
                os.chmod(path, 0o700)
        return path
    except Exception:
        return None


def private_open(path, append=False):
    """Open `path` for text writing with mode 0600, never following a symlink at the path."""
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | (os.O_APPEND if append else os.O_TRUNC)
    return os.fdopen(os.open(path, flags, 0o600), "a" if append else "w", encoding="utf-8")


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
        # git's worktree.useRelativePaths writes this link relative to the record.
        if not os.path.isabs(back):
            back = os.path.join(record, back)
        if os.path.realpath(back) != os.path.realpath(marker) or \
                os.path.realpath(os.path.dirname(back)) != os.path.realpath(root):
            return None
        main = os.path.dirname(common)
    except OSError:
        return None
    return None if os.path.realpath(main) == os.path.realpath(root) else main


# The order Claude Code itself applies a project's two settings files in: the
# personal settings.local.json over the shared settings.json (Claude Code's
# settings docs, "Settings precedence"). Every fact is read in this order.
SETTINGS_LEAVES = ("settings.local.json", "settings.json")


def settings_env(path):
    """The env block of one settings file as a dict, or {} when it has none or cannot be read."""
    try:
        with open(path) as handle:
            env = (json.load(handle) or {}).get("env") or {}
    except Exception:
        return {}
    return env if isinstance(env, dict) else {}


def settings_fact(root, name):
    """NAME from the env blocks of `root`'s settings files, the personal file first."""
    for leaf in SETTINGS_LEAVES:
        value = settings_env(os.path.join(root, ".claude", leaf)).get(name)
        if value:
            return str(value)
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
    # A subfolder reads the settings at the top of its checkout.
    top = checkout_top(root)
    value = settings_fact(main_checkout(top) or top, name)
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


def state_path(root=None):
    """The full path of that folder in the checkout `root` is in, from its top
    folder, so a subfolder and the top of a checkout name one folder."""
    root = root or project_root()
    return os.path.join(checkout_top(root), state_dir(root))


# The env keys that switch a Masthead gate or option off, which a repository's
# own files may not set (run.sh unsets them).
SWITCH_PREFIXES = ("MASTHEAD_", "CLAUDE_PLUGIN_OPTION_")
SWITCH_SUFFIXES = ("_GATE",)


ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def is_switch(key):
    """A gate or option switch. Only a real environment variable name counts: a key no
    shell could hold is never in a hook's environment, and is never printed (round 0, A4)."""
    return isinstance(key, str) and ENV_NAME.fullmatch(key) is not None and \
        (key.startswith(SWITCH_PREFIXES) or key.endswith(SWITCH_SUFFIXES))


def tracked(folder, relative):
    """Whether git tracks `relative` in the repository at `folder`. When git
    cannot answer inside a repository, the file counts as tracked, so a file git
    cannot vouch for is treated as the repository's."""
    try:
        r = subprocess.run(["git", "-C", folder, "ls-files", "--error-unmatch", "--", relative],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return True
    if r.returncode == 0:
        return True
    # A folder that is no repository was not cloned, so its file is the person's own.
    if not os.path.exists(os.path.join(checkout_top(folder), ".git")):
        return False
    # Inside a repository, 1 with git's own "did not match" is "not tracked"; anything else is git failing.
    return not (r.returncode == 1 and "did not match" in r.stderr)


def repo_switch_keys(root=None):
    """The gate and option switches a repository's own settings files set, for
    run.sh to unset: every one in the shared settings.json, and every one in a
    settings.local.json that git tracks, which a clone brings with it (MAST-38,
    from MAST-37's SEC-1). A settings.local.json git does not track is the
    person's own and keeps its switches. Claude Code reads the shared file from
    the session's folder and the personal file from the top of the repository
    (the main checkout's, in a worktree), so each of those places is read."""
    root = root or project_root()
    top = checkout_top(root)
    main = main_checkout(top) or top
    keys, own = set(), set()
    for folder in dict.fromkeys((root, top, main)):
        keys.update(k for k in settings_env(os.path.join(folder, ".claude", "settings.json")) if is_switch(k))
        local = os.path.join(folder, ".claude", "settings.local.json")
        if not os.path.exists(local):
            continue
        found = {k for k in settings_env(local) if is_switch(k)}
        if tracked(folder, os.path.join(".claude", "settings.local.json")):
            keys.update(found)
        else:
            own.update(found)
    # A switch the person's own file sets is the value Claude Code applies, over the
    # shared file's, so it stays (round 0, A3).
    return sorted(keys - own)


def git_state_path(root, name):
    """A file in the checkout's own git folder (a worktree's own, not the main
    checkout's), which no clone can commit or plant: where the push gate keeps its
    pass record and the Stop hook its index lock. None outside a repository."""
    leaf = re.sub(r"[^A-Za-z0-9._-]", "", os.path.basename(name or ""))
    if leaf in ("", ".", ".."):
        return None
    try:
        r = subprocess.run(["git", "-C", root or project_root(), "rev-parse", "--absolute-git-dir"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    folder = r.stdout.strip()
    if r.returncode != 0 or not folder:
        return None
    return os.path.join(folder, leaf)


TRACKER_FACT = "ISSUE_TRACKER"
TRACKERS = ("github", "linear")
LINEAR_TEAM_FACT = "LINEAR_TEAM_KEY"


def personal_first_fact(name, root=None):
    """fact() with no default; kept for its callers. Every fact reads the
    personal settings.local.json over the shared settings.json."""
    return fact(name, None, root)


def tracker(root=None):
    """Where the repository's issues live: "linear" when its settings say so, else "github"."""
    value = (personal_first_fact(TRACKER_FACT, root) or "").strip().lower()
    return value if value in TRACKERS else "github"


def linear_team(root=None):
    """The repository's Linear team key in upper case, or None when none is set."""
    value = (personal_first_fact(LINEAR_TEAM_FACT, root) or "").strip().upper()
    return value if re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", value) else None


ARCHITECTURE_DOC_FACT = "ARCHITECTURE_DOC"


def architecture_doc(root=None):
    """The full path of the project's architecture doc, or None.

    The repo-relative path comes from ARCHITECTURE_DOC, read like the tracker
    (the personal file wins); it resolves in the checkout `root` is in, so a
    worktree reads its own branch's copy. A path that leaves the repository,
    or names no file, gives None.
    """
    root = root or project_root()
    value = (personal_first_fact(ARCHITECTURE_DOC_FACT, root) or "").strip()
    if not value or os.path.isabs(os.path.expanduser(value)):
        return None
    top = checkout_top(root)
    path = os.path.realpath(os.path.join(top, value))
    if os.path.commonpath([path, top]) != top or not os.path.isfile(path):
        return None
    return path


ARCHITECTURE_TRIAL_FACT = "ARCHITECTURE_TRIAL"
TRIAL_OFF_WORDS = ("off", "false", "no", "0")


def architecture_trial(root=None):
    """"on" or "off": whether every architecture finding goes to the person (MAST-35).

    On until the person turns it off, so a new install is on the trial. Read
    like the tracker (the personal file wins). Only an off word turns it off:
    a typo keeps the person in the loop.
    """
    value = (personal_first_fact(ARCHITECTURE_TRIAL_FACT, root) or "").strip().lower()
    return "off" if value in TRIAL_OFF_WORDS else "on"


def main(argv):
    # --trusted CHECKOUT: exit 0 when the checkout is the session's repository, 1 when not.
    if len(argv) == 2 and argv[0] == "--trusted":
        return 0 if trusted(argv[1]) else 1
    root = None
    if len(argv) >= 2 and argv[0] == "--root":
        root, argv = argv[1], argv[2:]
    # --tracker prints github or linear; --linear-team prints the team key or nothing;
    # --architecture-doc prints the architecture doc's full path or nothing;
    # --architecture-trial prints on or off.
    # Skills run these through the Bash tool, where Claude Code sets no
    # CLAUDE_PROJECT_DIR (it sets it for hooks only), so there the repository
    # the shell is in is the session's. trusted() still guards --root.
    if argv in (["--tracker"], ["--linear-team"], ["--architecture-doc"], ["--architecture-trial"], ["--state-path"]) and root is None \
            and not os.environ.get("CLAUDE_PROJECT_DIR"):
        os.environ["CLAUDE_PROJECT_DIR"] = checkout_top(os.getcwd())
    # --state-path prints the full path of the checkout's state folder; the
    # dispatch log is dispatches.tsv in it.
    if argv == ["--state-path"]:
        print(state_path(root))
        return 0
    # --private-dir PART...: the 0700 folder under the user's private state root,
    # made when missing. Exit 1 and print nothing when it cannot be trusted.
    if argv and argv[0] == "--private-dir":
        path = private_dir(*[safe_session(part) for part in argv[1:]]) if len(argv) > 1 else None
        if not path:
            return 1
        print(path)
        return 0
    # --git-state NAME: the full path of NAME in the checkout's own git folder; exit 1 outside a repository.
    if len(argv) == 2 and argv[0] == "--git-state":
        path = git_state_path(root, argv[1])
        if not path:
            return 1
        print(path)
        return 0
    # --repo-switch-keys: the switches run.sh unsets, one per line.
    if argv == ["--repo-switch-keys"]:
        for key in repo_switch_keys(root):
            print(key)
        return 0
    if argv == ["--tracker"]:
        print(tracker(root))
        return 0
    if argv == ["--linear-team"]:
        print(linear_team(root) or "")
        return 0
    if argv == ["--architecture-doc"]:
        print(architecture_doc(root) or "")
        return 0
    if argv == ["--architecture-trial"]:
        print(architecture_trial(root))
        return 0
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
