#!/usr/bin/env python3
"""Linear issue MAST-1: a repository says where its issues live.

`project_fact.py --tracker` prints `github` or `linear` for the repository, from
ISSUE_TRACKER in the env block of its .claude settings; no setting, or one that
names neither, is GitHub, exactly as before. `--linear-team` prints the team key
from LINEAR_TEAM_KEY, upper case, or nothing. The facts are read fresh on every
call, so a changed answer holds from the next call on.

Run from anywhere: python3 hooks/tests/tracker-fact-test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "project_fact.py")

passed = 0
failed = 0


def repo():
    root = tempfile.mkdtemp(prefix="tracker-fact-")
    os.mkdir(os.path.join(root, ".git"))
    os.mkdir(os.path.join(root, ".claude"))
    return root


def settings(root, env, leaf="settings.json"):
    with open(os.path.join(root, ".claude", leaf), "w") as handle:
        json.dump({"env": env}, handle)


def ask(root, flag, cwd=None, project=True):
    """Run the real script. project=False is a skill's Bash call: Claude Code
    sets CLAUDE_PROJECT_DIR only for hooks, so the shell there has none."""
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("CLAUDE_CODE_REMOTE", None)
    if project:
        env["CLAUDE_PROJECT_DIR"] = root
    out = subprocess.run([sys.executable, SCRIPT, flag], cwd=cwd or root, env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


# Scenario 1: a repository whose settings name no tracker uses GitHub.
root = repo()
expect("no settings file", ask(root, "--tracker"), "github")
settings(root, {"PROJECT_PUSH_CHECK": ".claude/push-check.sh"})
expect("settings without the fact", ask(root, "--tracker"), "github")
settings(root, {"ISSUE_TRACKER": "gitlab"})
expect("a tracker Masthead does not know", ask(root, "--tracker"), "github")
settings(root, {"ISSUE_TRACKER": "github"})
expect("github named", ask(root, "--tracker"), "github")

# Scenario 2: setup writes the answer to either settings file.
root = repo()
settings(root, {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "KOR"})
expect("linear in settings.json", ask(root, "--tracker"), "linear")
expect("team key", ask(root, "--linear-team"), "KOR")
root = repo()
settings(root, {"ISSUE_TRACKER": "Linear ", "LINEAR_TEAM_KEY": "kor"}, "settings.local.json")
expect("linear in settings.local.json, any case", ask(root, "--tracker"), "linear")
expect("team key in upper case", ask(root, "--linear-team"), "KOR")
settings(root, {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "not a key"}, "settings.local.json")
expect("a team key that is not one", ask(root, "--linear-team"), "")
settings(root, {"ISSUE_TRACKER": "linear"}, "settings.local.json")
expect("no team key", ask(root, "--linear-team"), "")

# Scenario 4: a changed answer holds from the next read on.
root = repo()
settings(root, {"ISSUE_TRACKER": "github"})
expect("before the move", ask(root, "--tracker"), "github")
settings(root, {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "KOR"})
expect("after the move", ask(root, "--tracker"), "linear")

# Review fix 1: both settings files carry the fact. The personal file wins,
# as it does in Claude Code itself, so "Just me, Linear" over a committed
# "github" holds.
root = repo()
settings(root, {"ISSUE_TRACKER": "github"})
settings(root, {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "KOR"}, "settings.local.json")
expect("personal file over shared file", ask(root, "--tracker"), "linear")
settings(root, {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "KOR"})
settings(root, {"ISSUE_TRACKER": "github"}, "settings.local.json")
expect("personal github over shared linear", ask(root, "--tracker"), "github")

# Review fix 2: a skill runs the check through the Bash tool, which has no
# CLAUDE_PROJECT_DIR. The repository the shell is in answers.
root = repo()
settings(root, {"ISSUE_TRACKER": "linear", "LINEAR_TEAM_KEY": "KOR"})
expect("skill's shell, repo top", ask(root, "--tracker", project=False), "linear")
sub = os.path.join(root, "lib")
os.mkdir(sub)
expect("skill's shell, a folder inside", ask(root, "--tracker", cwd=sub, project=False), "linear")
expect("skill's shell, team key", ask(root, "--linear-team", project=False), "KOR")

# Review fix 2, with a real git worktree: a worker's shell in a worktree reads
# the main checkout's answer, so every worker of one repository agrees.
main = tempfile.mkdtemp(prefix="tracker-main-")
subprocess.run(["git", "init", "-q", main], check=True)
subprocess.run(["git", "-C", main, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-q", "--allow-empty", "-m", "init"], check=True)
os.mkdir(os.path.join(main, ".claude"))
settings(main, {"ISSUE_TRACKER": "linear"})
tree = os.path.join(tempfile.mkdtemp(prefix="tracker-tree-"), "wt")
subprocess.run(["git", "-C", main, "worktree", "add", "-q", tree], check=True)
expect("worker's shell in a worktree", ask(tree, "--tracker", project=False), "linear")

# Review round 1: a worktree made under git's worktree.useRelativePaths keeps
# relative links; it still reads the main checkout's answer. (A git older
# than 2.48 ignores the setting and makes absolute links, so this passes there.)
rel = os.path.join(os.path.dirname(main), os.path.basename(main) + "-rel")
subprocess.run(["git", "-C", main, "-c", "worktree.useRelativePaths=true",
                "worktree", "add", "-q", rel], check=True)
expect("worker's shell in a relative-link worktree", ask(rel, "--tracker", project=False), "linear")
expect("relative-link worktree, session set", ask(rel, "--tracker"), "linear")

# A checkout that is not the session's repository supplies no facts.
other = repo()
settings(other, {"ISSUE_TRACKER": "linear"})
env = dict(os.environ, CLAUDE_PROJECT_DIR=repo())
out = subprocess.run([sys.executable, SCRIPT, "--root", other, "--tracker"], env=env,
                     capture_output=True, text=True, check=True).stdout.strip()
expect("another repository's settings", out, "github")

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
