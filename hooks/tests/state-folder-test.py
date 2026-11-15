#!/usr/bin/env python3
"""MAST-38: every hook finds its state through project_fact.py, and a repository's
own files cannot switch a gate off.

Scenario 1: with PROJECT_STATE_DIR set, the dispatch row lands in that folder at
the top of the checkout, from the top or from a subfolder, and
`project_fact.py --state-path` (what the worker counts from) names that folder.
Scenario 4: no hook works out the user's private state root itself; each one
asks project_fact.py, so each gets its private-folder checks.
Scenario 5: the personal settings.local.json wins over the shared
settings.json, the order Claude Code uses, for every fact.
Scenario 6: a settings.local.json that git tracks (a clone brought it) cannot
switch a gate off through run.sh; an untracked one is the person's own.

Run from anywhere: python3 hooks/tests/state-folder-test.py
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.dirname(HERE)
ROOT = os.path.dirname(HOOKS)
FACT = os.path.join(HOOKS, "project_fact.py")
DISPATCH = os.path.join(HOOKS, "dispatch-record-gate.sh")
RUN = os.path.join(HOOKS, "run.sh")

passed = 0
failed = 0


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull))


def repo(branch="robert/mast-38-test"):
    root = os.path.realpath(tempfile.mkdtemp(prefix="state-folder-"))
    git("init", "-q", "-b", branch, ".", cwd=root)
    os.makedirs(os.path.join(root, ".claude"))
    os.makedirs(os.path.join(root, "app", "lib"))
    return root


def settings(root, env, leaf="settings.json"):
    with open(os.path.join(root, ".claude", leaf), "w") as handle:
        json.dump({"env": env}, handle)


def clean_env(**extra):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("MASTHEAD_", "CLAUDE_PLUGIN_OPTION_")) or key in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_DATA", "CLAUDE_CODE_REMOTE"):
            env.pop(key)
    env.update(extra)
    return env


def dispatch(root, cwd, prompt="Verify the diff.", subagent="general-purpose", env=None):
    payload = json.dumps({"session_id": "state-folder-test", "cwd": cwd, "tool_name": "Agent",
                          "tool_input": {"prompt": prompt, "subagent_type": subagent, "description": "probe"}})
    subprocess.run(["bash", DISPATCH], input=payload, capture_output=True, text=True,
                   env=env or clean_env(CLAUDE_PROJECT_DIR=root), check=False)


def rows(path):
    try:
        with open(path) as handle:
            return [line.rstrip("\n").split("\t") for line in handle][1:]
    except OSError:
        return []


# Scenario 1: the dispatch log lives where PROJECT_STATE_DIR says, at the top of the checkout.
root = repo()
settings(root, {"PROJECT_STATE_DIR": ".work/state"})
dispatch(root, root)
dispatch(root, os.path.join(root, "app", "lib"))
log = os.path.join(root, ".work", "state", "dispatches.tsv")
expect("a dispatch from the top lands in PROJECT_STATE_DIR, and one from a subfolder lands in the same log",
       len(rows(log)), 2)
expect("nothing is written to .claude/state when PROJECT_STATE_DIR names another folder",
       os.path.exists(os.path.join(root, ".claude", "state", "dispatches.tsv")), False)
expect("nothing is written under the subfolder",
       os.path.exists(os.path.join(root, "app", "lib", ".work")) or os.path.exists(os.path.join(root, "app", "lib", ".claude")), False)

# The worker counts from what --state-path prints, run as a skill runs it (no CLAUDE_PROJECT_DIR).
out = subprocess.run([sys.executable, FACT, "--state-path"], cwd=os.path.join(root, "app"),
                     env=clean_env(), capture_output=True, text=True).stdout.strip()
expect("--state-path from a subfolder names the folder the row went to", out, os.path.join(root, ".work", "state"))

# With no fact, the default folder at the top.
plain = repo()
dispatch(plain, os.path.join(plain, "app"))
expect("with no fact, a subfolder's dispatch lands in .claude/state at the top",
       len(rows(os.path.join(plain, ".claude", "state", "dispatches.tsv"))), 1)

# The worker and the PR steps name that one command for the folder, and no file hard-codes the default as the log.
with open(os.path.join(ROOT, "skills", "work-on", "worker.md")) as handle:
    worker = handle.read()
with open(os.path.join(ROOT, "references", "session-cliffs.md")) as handle:
    cliffs = handle.read()
expect("worker.md no longer counts rows of .claude/state/dispatches.tsv", ".claude/state/dispatches.tsv" in worker, False)
expect("session-cliffs says which folder <state> is", "project_fact.py --state-path" in cliffs, True)


def section(text, start, stop):
    """The text from the heading `start` up to the next heading `stop`."""
    begin = text.find(start)
    end = text.find(stop, begin + 1) if begin >= 0 else -1
    return text[begin:end] if begin >= 0 and end > begin else ""


# Round 0, A1: step 4 names the log the count is taken from, and step 7 counts from step 4's number.
step4 = section(worker, "## 4. What done is", "## 5.")
step7 = section(worker, "## 7. Report", "## A question")
expect("worker.md step 4 names <state>/dispatches.tsv", "`<state>/dispatches.tsv`" in step4, True)
expect("worker.md step 4 notes how many rows the log holds", "how many rows the dispatch log holds" in step4, True)
expect("worker.md step 7 counts from the number noted in step 4", "since the count you noted in\nstep 4" in step7 or "since the count you noted in step 4" in step7, True)
step9 = section(cliffs, "9. Push and open one PR", "10. Once it merges")
expect("session-cliffs step 9 counts rows of <state>/dispatches.tsv", "`<state>/dispatches.tsv`" in step9, True)

# Round 0, A6: no instruction says a fact comes from settings.json alone, now that the personal file wins.
with open(os.path.join(ROOT, "references", "dispatch-brief.md")) as handle:
    brief = handle.read()
expect("dispatch-brief.md does not say <state> comes from settings.json alone",
       "PROJECT_STATE_DIR fact from the env block of its .claude/settings.json" in brief, False)
expect("session-cliffs.md does not say the push check comes from settings.json alone",
       "its `.claude/settings.json` env names as `PROJECT_PUSH_CHECK`" in cliffs, False)

# A raised cap shows on the row: the dispatch record names it.
root = repo()
dispatch(root, root, prompt="Re-verify: round 3, claim 2\nVerify the fix.\n\nClaims:\n- the gate refuses the third round",
         subagent="masthead:verifier", env=clean_env(CLAUDE_PROJECT_DIR=root, MASTHEAD_REVERIFY_CAP="3"))
got = [r[5] for r in rows(os.path.join(root, ".claude", "state", "dispatches.tsv"))]
expect("a round sent under a raised cap is logged with the cap", got, ["re-verify round 3 (cap raised to 3)"])
dispatch(root, root, prompt="Re-verify: round 1, claim 2\nVerify the fix.\n\nClaims:\n- the gate refuses the third round",
         subagent="masthead:verifier")
got = [r[5] for r in rows(os.path.join(root, ".claude", "state", "dispatches.tsv"))]
expect("a round under the usual cap is logged as before", got[-1], "re-verify round 1")


# Scenario 4: one function finds the private state root. No hook other than
# project_fact.py names CLAUDE_PLUGIN_DATA, builds the masthead-<uid> root, or
# keeps a state folder of its own in TMPDIR.
OWN_ROOT = re.compile(r"CLAUDE_PLUGIN_DATA|masthead-\$\(id -u\)|masthead-\{\}|masthead-%|rev-parse --git-path|rev-parse --absolute-git-dir")
TMP_STATE = re.compile(r"(TMPDIR|/tmp|gettempdir).*(claude-[a-z]+|\.skipped)")
for name in sorted(os.listdir(HOOKS)):
    path = os.path.join(HOOKS, name)
    if not os.path.isfile(path) or not name.endswith((".py", ".sh")) or name == "project_fact.py":
        continue
    if name.startswith("test-") or name == "run-tests.sh":
        continue
    with open(path) as handle:
        text = handle.read()
    own = [line.strip() for line in text.splitlines() if OWN_ROOT.search(line) and not line.lstrip().startswith("#")]
    tmp = [line.strip() for line in text.splitlines() if TMP_STATE.search(line) and not line.lstrip().startswith("#")]
    expect("{} finds the private state root through project_fact.py".format(name), own, [])
    expect("{} keeps no state folder of its own in TMPDIR".format(name), tmp, [])


def private_root(tmp):
    return os.path.join(tmp, "masthead-{}".format(os.getuid()))


def run_hook(name, mode, payload, tmp, **extra):
    argv = ["python3", os.path.join(HOOKS, name)] if name.endswith(".py") else ["bash", os.path.join(HOOKS, name)]
    if mode:
        argv.append(mode)
    return subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                          env=clean_env(TMPDIR=tmp, **extra), cwd=tmp, check=False)


# The skill review gate's read record goes under the private root, 0700.
tmp = os.path.realpath(tempfile.mkdtemp(prefix="state-private-"))
run_hook("skill-review-gate.py", "record", {"session_id": "s4", "tool_name": "Read",
                                            "tool_input": {"file_path": "/x/SKILL.md"}}, tmp)
folder = os.path.join(private_root(tmp), "claude-skillreview", "s4")
expect("skill-review-gate keeps its read record under the private root", os.path.isfile(os.path.join(folder, "read.txt")), True)
expect("and not in a bare TMPDIR folder", os.path.exists(os.path.join(tmp, "claude-skillreview")), False)
if os.path.isdir(folder):
    expect("its folder is 0700", stat.S_IMODE(os.stat(folder).st_mode), 0o700)

# A root planted as a symlink is refused: nothing is written through it.
evil_tmp = os.path.realpath(tempfile.mkdtemp(prefix="state-evil-"))
target = os.path.realpath(tempfile.mkdtemp(prefix="state-target-"))
os.symlink(target, private_root(evil_tmp))
run_hook("skill-review-gate.py", "record", {"session_id": "s4", "tool_name": "Read",
                                            "tool_input": {"file_path": "/x/SKILL.md"}}, evil_tmp)
run_hook("engram-protocol.sh", "mark-edit", {"session_id": "s4"}, evil_tmp)
run_hook("irreversible-action-gate.sh", None, {"session_id": "s4", "tool_name": "Bash",
                                               "tool_input": {"command": "git push --force origin main"}}, evil_tmp)
expect("no hook writes through a symlinked private root", os.listdir(target), [])

# CLAUDE_PLUGIN_DATA moves every hook's root the same way.
data = os.path.realpath(tempfile.mkdtemp(prefix="state-data-"))
tmp = os.path.realpath(tempfile.mkdtemp(prefix="state-private-"))
run_hook("engram-protocol.sh", "mark-edit", {"session_id": "s4"}, tmp, CLAUDE_PLUGIN_DATA=data)
run_hook("skill-review-gate.py", "record", {"session_id": "s4", "tool_name": "Read",
                                            "tool_input": {"file_path": "/x/SKILL.md"}}, tmp, CLAUDE_PLUGIN_DATA=data)
expect("engram-protocol.sh uses CLAUDE_PLUGIN_DATA/state", os.path.isfile(os.path.join(data, "state", "claude-engram", "s4", "edited")), True)
expect("skill-review-gate.py uses the same root", os.path.isfile(os.path.join(data, "state", "claude-skillreview", "s4", "read.txt")), True)
expect("neither writes to TMPDIR then", sorted(os.listdir(tmp)), [])

# --private-dir keeps a session id inside the root.
out = subprocess.run([sys.executable, FACT, "--private-dir", "claude-engram", "../../etc"],
                     env=clean_env(TMPDIR=tmp), capture_output=True, text=True).stdout.strip()
expect("--private-dir keeps a session id with .. inside the root",
       out, os.path.join(private_root(tmp), "claude-engram", "etc"))
res = subprocess.run([sys.executable, FACT, "--private-dir", "claude-engram", "s"],
                     env=clean_env(TMPDIR=evil_tmp), capture_output=True, text=True)
expect("--private-dir prints nothing and exits 1 for a symlinked root", (res.returncode, res.stdout), (1, ""))


# Scenario 5: the personal file wins, as in Claude Code, for every fact.
root = repo()
settings(root, {"PROJECT_STATE_DIR": ".shared/state", "ADR_DIR": "shared-adr"})
settings(root, {"PROJECT_STATE_DIR": ".mine/state", "ADR_DIR": "my-adr"}, "settings.local.json")
out = subprocess.run([sys.executable, FACT, "--state-path"], cwd=root, env=clean_env(),
                     capture_output=True, text=True).stdout.strip()
expect("the state folder from settings.local.json wins", out, os.path.join(root, ".mine", "state"))
out = subprocess.run([sys.executable, FACT, "ADR_DIR"], cwd=root, env=clean_env(CLAUDE_PROJECT_DIR=root),
                     capture_output=True, text=True).stdout.strip()
expect("any fact from settings.local.json wins", out, "my-adr")


# Scenario 6: run.sh and the switches a repository's own files set.
COMMIT = json.dumps({"session_id": "run-sh-38", "tool_name": "Bash", "tool_input": {
    "command": "git commit -m \"x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\""}})


def through_run(project):
    out = subprocess.run(["bash", RUN, "commit-attribution-gate.py"], input=COMMIT, capture_output=True, text=True,
                         env=clean_env(CLAUDE_PROJECT_DIR=project, CLAUDE_PLUGIN_OPTION_STRICT_COMMITS="false"),
                         check=False).stdout
    return "deny" if '"deny"' in out else "allow"


root = repo()
settings(root, {"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "false"}, "settings.local.json")
git("add", "-f", ".claude/settings.local.json", cwd=root)
expect("a tracked settings.local.json cannot switch a gate off", through_run(root), "deny")

root = repo()
settings(root, {"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "false"}, "settings.local.json")
expect("an untracked settings.local.json is the person's own, and its switch holds", through_run(root), "allow")

# A worktree: Claude Code reads the personal file at the main checkout's top.
main = repo()
settings(main, {"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "false"}, "settings.local.json")
git("add", "-f", ".claude/settings.local.json", cwd=main)
git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init", cwd=main)
tree = os.path.join(main, "wt")
git("worktree", "add", "-q", "-b", "other", tree, cwd=main)
expect("in a worktree, the main checkout's tracked settings.local.json cannot switch a gate off",
       through_run(tree), "deny")

# The keys run.sh unsets come from project_fact.py, the one reader.
out = subprocess.run([sys.executable, FACT, "--repo-switch-keys"], env=clean_env(CLAUDE_PROJECT_DIR=main),
                     capture_output=True, text=True).stdout.split()
expect("--repo-switch-keys lists the tracked file's switch", out, ["CLAUDE_PLUGIN_OPTION_STRICT_COMMITS"])
with open(RUN) as handle:
    run_text = handle.read()
expect("run.sh asks project_fact.py which keys to unset", "--repo-switch-keys" in run_text, True)

# Round 0, A2: state in the checkout's own git folder comes from project_fact.py too.
root = repo()
out = subprocess.run([sys.executable, FACT, "--root", os.path.join(root, "app"), "--git-state", "masthead-push-gate-pass"],
                     env=clean_env(), capture_output=True, text=True).stdout.strip()
expect("--git-state names the file in the checkout's own git folder", out, os.path.join(root, ".git", "masthead-push-gate-pass"))
out = subprocess.run([sys.executable, FACT, "--root", root, "--git-state", "../escape"],
                     env=clean_env(), capture_output=True, text=True).stdout.strip()
expect("--git-state keeps a name inside the git folder", out, os.path.join(root, ".git", "escape"))
wt_main = repo()
git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "init", cwd=wt_main)
wt = os.path.join(wt_main, "wt2")
git("worktree", "add", "-q", "-b", "wt2", wt, cwd=wt_main)
out = subprocess.run([sys.executable, FACT, "--root", wt, "--git-state", "korium-index-stop.pid"],
                     env=clean_env(), capture_output=True, text=True).stdout.strip()
expect("in a worktree, --git-state names the worktree's own git folder",
       out, os.path.join(wt_main, ".git", "worktrees", "wt2", "korium-index-stop.pid"))


# Round 0, A3: when the person's untracked settings.local.json sets a switch the shared file
# also sets, Claude Code uses the person's value, and so do the hook and run.sh.
root = repo()
settings(root, {"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "true"})
settings(root, {"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "false"}, "settings.local.json")
expect("the hook's fact is the person's value", subprocess.run(
    [sys.executable, FACT, "CLAUDE_PLUGIN_OPTION_STRICT_COMMITS"], cwd=root, env=clean_env(CLAUDE_PROJECT_DIR=root),
    capture_output=True, text=True).stdout.strip(), "false")
expect("run.sh keeps the person's value when the shared file names the same switch", through_run(root), "allow")
settings(root, {"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "false"})
os.remove(os.path.join(root, ".claude", "settings.local.json"))
expect("the shared file alone still cannot switch the gate off", through_run(root), "deny")


# Round 0, A4: a key the printer cannot write does not hide the others.
root = repo()
with open(os.path.join(root, ".claude", "settings.local.json"), "w") as handle:
    handle.write('{"env": {"CLAUDE_PLUGIN_OPTION_A\\ud800": "x", "CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "false"}}')
git("add", "-f", ".claude/settings.local.json", cwd=root)
expect("a tracked file with an unprintable key still cannot switch a gate off", through_run(root), "deny")

# And when the reader fails, run.sh does not leave the switches set: it unsets every switch and says so.
lone = os.path.realpath(tempfile.mkdtemp(prefix="state-noreader-"))
shutil.copy(RUN, os.path.join(lone, "run.sh"))
with open(os.path.join(lone, "envprobe.sh"), "w") as handle:
    handle.write('printf "%s" "${MASTHEAD_BRIEF_GATE:-unset}"\n')
res = subprocess.run(["bash", os.path.join(lone, "run.sh"), "envprobe.sh"], input="{}", capture_output=True, text=True,
                     env=clean_env(CLAUDE_PROJECT_DIR=root, MASTHEAD_BRIEF_GATE="off"), check=False)
expect("with no reader, run.sh unsets the switches rather than keep them", res.stdout, "unset")
expect("and says why", "project_fact.py" in res.stderr, True)


# Re-verify round 1, SEC-1: a committed .claude/Settings.local.json is tracked whatever the case of its
# name. On a disk that ignores case (a Mac's default), Claude Code opens it as settings.local.json.
root = repo()
with open(os.path.join(root, ".claude", "Settings.local.json"), "w") as handle:
    json.dump({"env": {"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS": "false"}}, handle)
git("add", "-f", ".claude/Settings.local.json", cwd=root)
caseless = os.path.exists(os.path.join(root, ".claude", "settings.local.json"))
keys = subprocess.run([sys.executable, FACT, "--repo-switch-keys"], env=clean_env(CLAUDE_PROJECT_DIR=root),
                      capture_output=True, text=True).stdout.split()
if caseless:
    expect("a committed Settings.local.json with a capital S cannot switch a gate off", through_run(root), "deny")
    expect("its switch is on the list run.sh unsets", keys, ["CLAUDE_PLUGIN_OPTION_STRICT_COMMITS"])
    # And it does not shield a switch the shared file sets (the round 0 regression).
    settings(root, {"MASTHEAD_EDIT_GATE": "off"})
    keys = subprocess.run([sys.executable, FACT, "--repo-switch-keys"], env=clean_env(CLAUDE_PROJECT_DIR=root),
                          capture_output=True, text=True).stdout.split()
    expect("nor shield the shared file's switches", keys, ["CLAUDE_PLUGIN_OPTION_STRICT_COMMITS", "MASTHEAD_EDIT_GATE"])
else:
    # A disk that keeps case never opens it as settings.local.json, so Claude Code does not load it at all.
    expect("on a disk that keeps case, the capital-S file is not read as the personal file", keys, [])


# Round 0, A5: python3 that does not run is a refusal, never a silent allow.
stub = os.path.realpath(tempfile.mkdtemp(prefix="state-nopython-"))
with open(os.path.join(stub, "python3"), "w") as handle:
    handle.write("#!/bin/sh\nexit 1\n")
os.chmod(os.path.join(stub, "python3"), 0o755)
root = repo()
brief = json.dumps({"session_id": "nopy", "cwd": root, "tool_name": "Agent", "tool_input": {
    "subagent_type": "masthead:verifier", "description": "probe",
    "prompt": "Re-verify: round 3, claim 1\nVerify it.\n\nClaims:\n- the gate refuses the third round"}})
broken = clean_env(CLAUDE_PROJECT_DIR=root, PATH=stub + os.pathsep + os.environ.get("PATH", ""))
res = subprocess.run(["bash", os.path.join(HOOKS, "agent-brief-gates.sh")], input=brief, capture_output=True,
                     text=True, env=broken, check=False)
expect("a dispatch is refused when python3 does not run, jq or not", '"deny"' in res.stdout, True)
expect("and the refusal names python3", "python3" in res.stdout, True)
res = subprocess.run(["bash", os.path.join(HOOKS, "engram-protocol.sh"), "gate-verify-brief"], input=brief,
                     capture_output=True, text=True, env=broken, check=False)
expect("gate-verify-brief alone refuses when it cannot find its folder", '"deny"' in res.stdout, True)

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
