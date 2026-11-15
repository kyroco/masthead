#!/usr/bin/env python3
"""Linear issue MAST-35, scenarios 8 to 10: the architecture reviewer's trial period.

Robert, November 14, 2026: "for the architect role we need to pass its
findings to me right now until I determine how it's performing and how it's
scoring things I care about".

Scenario 10: a new install, with no fact recorded, is on the trial.
Scenario 9: the person turns it off with ARCHITECTURE_TRIAL set to "off" in
the env block of .claude/settings.json (the personal file wins, as for the
tracker), and only an off word turns it off.

Run from anywhere: python3 hooks/tests/architecture-trial-test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
FACT = os.path.join(PLUGIN, "hooks", "project_fact.py")

passed = 0
failed = 0


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


def repo():
    root = os.path.realpath(tempfile.mkdtemp(prefix="arch-trial-"))
    os.mkdir(os.path.join(root, ".git"))
    os.mkdir(os.path.join(root, ".claude"))
    return root


def settings(root, env, leaf="settings.json"):
    with open(os.path.join(root, ".claude", leaf), "w") as handle:
        json.dump({"env": env}, handle)


def trial(root, cwd=None, project=True, extra=()):
    """project=False is a skill's Bash call, where Claude Code sets no CLAUDE_PROJECT_DIR."""
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("CLAUDE_CODE_REMOTE", None)
    if project:
        env["CLAUDE_PROJECT_DIR"] = root
    out = subprocess.run([sys.executable, FACT] + list(extra) + ["--architecture-trial"],
                         cwd=cwd or root, env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


# Scenario 10: a new install is on the trial.
root = repo()
expect("no settings file at all", trial(root), "on")
settings(root, {"ISSUE_TRACKER": "linear"})
expect("settings with no trial fact", trial(root), "on")
expect("a skill's shell, no CLAUDE_PROJECT_DIR", trial(root, project=False), "on")

# Scenario 9: the person turns it off.
settings(root, {"ARCHITECTURE_TRIAL": "off"})
expect("off in settings.json", trial(root), "off")
expect("off, read from a skill's shell", trial(root, project=False), "off")
os.mkdir(os.path.join(root, "lib"))
expect("off, from a folder inside", trial(root, cwd=os.path.join(root, "lib"), project=False), "off")
for word in ("OFF", "Off", " off ", "false", "no", "0"):
    settings(root, {"ARCHITECTURE_TRIAL": word})
    expect("the off word {!r}".format(word), trial(root), "off")
# Only an off word turns it off: a typo keeps the person in the loop.
for word in ("on", "yes", "of", "disabled-ish", ""):
    settings(root, {"ARCHITECTURE_TRIAL": word})
    expect("the word {!r} keeps it on".format(word), trial(root), "on")

# The personal file wins over the shared one, both ways.
root = repo()
settings(root, {"ARCHITECTURE_TRIAL": "off"})
settings(root, {"ARCHITECTURE_TRIAL": "on"}, "settings.local.json")
expect("personal on over shared off", trial(root), "on")
root = repo()
settings(root, {"ARCHITECTURE_TRIAL": "on"})
settings(root, {"ARCHITECTURE_TRIAL": "off"}, "settings.local.json")
expect("personal off over shared on", trial(root), "off")

# --root names another checkout: an untrusted one gives no fact, so the trial stays on.
mine = repo()
other = repo()
settings(other, {"ARCHITECTURE_TRIAL": "off"})
expect("an untrusted --root keeps it on", trial(mine, extra=["--root", other]), "on")
expect("a trusted --root reads its fact", trial(other, extra=["--root", other]), "off")

# In a real worktree, the main checkout's settings decide.
main = os.path.realpath(tempfile.mkdtemp(prefix="arch-trial-main-"))
subprocess.run(["git", "init", "-q", main], check=True)
with open(os.path.join(main, "README.md"), "w") as handle:
    handle.write("x\n")
subprocess.run(["git", "-C", main, "add", "."], check=True)
subprocess.run(["git", "-C", main, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-q", "-m", "init"], check=True)
os.mkdir(os.path.join(main, ".claude"))
settings(main, {"ARCHITECTURE_TRIAL": "off"})
tree = os.path.join(os.path.realpath(tempfile.mkdtemp(prefix="arch-trial-tree-")), "wt")
subprocess.run(["git", "-C", main, "worktree", "add", "-q", tree], check=True)
expect("a worker's shell in a worktree", trial(tree, project=False), "off")

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
