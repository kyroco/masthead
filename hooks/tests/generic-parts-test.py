#!/usr/bin/env python3
"""MAST-40: Masthead's generic parts hold no repository to Kyroco's own setup.

1. A repository that named no ADR folder is held by no ADR gate.
2. A repository that opted in is asked for the same sections by both ADR gates.
3. Refusal text and injected context name no Kyroco repo, app path, ADR number or person.
4. prime-context.py reads only the plugin's own files and the repository's.

Run: python3 hooks/tests/generic-parts-test.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.dirname(HOOKS)
SECTIONS_GATE = os.path.join(HOOKS, "adr-sections-gate.py")
STRUCTURE_GATE = os.path.join(HOOKS, "adr-structure-gate.sh")
PRIME = os.path.join(HOOKS, "prime-context.py")
PROTOCOL = os.path.join(HOOKS, "engram-protocol.sh")

# The one section list both gates must ask for, in order (hooks/adr_shape.py SECTIONS):
# the union of the two lists the gates asked for before MAST-40.
SHAPE = ["Status", "Principle Alignment", "Context", "Options Considered", "Decision",
         "Rationale", "Acceptance Criteria", "You Are Done When", "Falsifiability"]

# What a reader outside Kyroco must never meet: its repos and apps, its ADR numbers, its people.
KYROCO = re.compile(r"(?i)kyroco|maryam|\bADR-\d{4}\b|products/apps|engram_core|salon_web|_ADR-TEMPLATE")

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print("ok   - %s" % name)
    else:
        failed += 1
        print("FAIL - %s: got %r, want %r" % (name, got, want))


T = os.path.realpath(tempfile.mkdtemp(prefix="generic-parts-test."))
BASE_ENV = {k: v for k, v in os.environ.items()
            if k not in ("ADR_DIR", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "ADR_STRUCTURE_GATE")}


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
                    "-c", "user.email=t@example.com"] + list(args),
                   capture_output=True, check=True)


def make_repo(name, settings_env=None):
    """A git repository with one commit; its settings name ADR_DIR only when asked."""
    repo = os.path.join(T, name)
    os.makedirs(os.path.join(repo, ".claude"))
    git(repo, "init", "-q")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("x\n")
    if settings_env is not None:
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as f:
            json.dump({"env": settings_env}, f)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def sections_gate(repo, tool, tool_input):
    """The write-time gate's refusal reason, or '' when it allows."""
    env = dict(BASE_ENV, CLAUDE_PROJECT_DIR=repo)
    out = subprocess.run([sys.executable, SECTIONS_GATE],
                         input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
                         capture_output=True, text=True, cwd=repo, env=env).stdout
    if not out.strip():
        return ""
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


def structure_gate(repo, payload="{}"):
    """The stop-time gate's exit code and what it said."""
    env = dict(BASE_ENV, CLAUDE_PROJECT_DIR=repo)
    r = subprocess.run(["bash", STRUCTURE_GATE], input=payload, capture_output=True,
                       text=True, cwd=repo, env=env)
    return r.returncode, r.stderr


def absent(text):
    """The section names a refusal says are absent, in order."""
    return re.findall(r"`## ([^`]+)` is absent", text)


TITLE_ONLY = "# Use a queue\n\nWe will use a queue.\n"

# ---------------------------------------------------------------- scenario 1
print("--- 1. a repository that named no ADR folder is held by no ADR gate ---")
for label, settings in (("no settings file", None), ("settings with no ADR_DIR", {"OTHER": "x"})):
    repo = make_repo("plain-" + label.replace(" ", "-"), settings)
    for rel in ("adr/0001-record-architecture-decisions.md",
                "docs/adr/0002-use-a-queue.md",
                "docs/decisions/0003-use-madr.md",
                "docs/adr/ADR-0004-use-a-queue.md"):
        path = os.path.join(repo, rel)
        check("%s: writing %s is not refused" % (label, rel),
              sections_gate(repo, "Write", {"file_path": path, "content": TITLE_ONLY}), "")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(TITLE_ONLY)
    check("%s: a shell write into adr/ is not refused" % label,
          sections_gate(repo, "Bash", {"command": "echo x > docs/adr/ADR-0005-x.md"}), "")
    code, err = structure_gate(repo)
    check("%s: stopping with four short ADRs is not held" % label, (code, err.strip()), (0, ""))

# ---------------------------------------------------------------- scenario 2
print("--- 2. an opted-in repository is asked for the same sections by both gates ---")
names = SHAPE
for folder, rel in (("docs/adr", "docs/adr/ADR-0007-use-a-queue.md"),
                    ("doc/architecture/decisions", "doc/architecture/decisions/0007-use-a-queue.md")):
    repo = make_repo("opted-in-" + folder.replace("/", "-"), {"ADR_DIR": folder})
    path = os.path.join(repo, rel)
    write_reason = sections_gate(repo, "Write", {"file_path": path, "content": TITLE_ONLY})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(TITLE_ONLY)
    code, err = structure_gate(repo)
    check("%s: the write gate asks for every section" % folder, absent(write_reason), names)
    check("%s: the stop gate holds the finish" % folder, code, 2)
    check("%s: the stop gate asks for the same sections" % folder, absent(err), names)

    # A record with the whole shape passes both.
    full = "# Use a queue\n\n" + "\n".join(
        "## %s\n\n%s\n" % (t, "- AC-1: one.\n- AC-2: two." if t == "Acceptance Criteria" else "Text.")
        for t in names) + "\nSee `lib/queue.py:1`.\n"
    with open(path, "w") as f:
        f.write(full)
    check("%s: the write gate allows a full record" % folder,
          sections_gate(repo, "Write", {"file_path": path, "content": full}), "")
    check("%s: the stop gate allows a full record" % folder, structure_gate(repo)[0], 0)

# The settings fact and the ADR_DIR environment variable opt in alike.
repo = make_repo("opted-in-by-env")
path = os.path.join(repo, "docs/adr/ADR-0008-x.md")
env = dict(BASE_ENV, CLAUDE_PROJECT_DIR=repo, ADR_DIR="docs/adr")
out = subprocess.run([sys.executable, SECTIONS_GATE],
                     input=json.dumps({"tool_name": "Write",
                                       "tool_input": {"file_path": path, "content": TITLE_ONLY}}),
                     capture_output=True, text=True, cwd=repo, env=env).stdout
check("ADR_DIR in the environment opts in too", '"deny"' in out, True)

# A record whose file name holds a space is held by both gates (judge's fix V2-J1).
repo = make_repo("opted-in-space", {"ADR_DIR": "docs/adr"})
spaced = os.path.join(repo, "docs/adr/ADR-0007 use a queue.md")
check("the write gate asks a spaced name for every section",
      absent(sections_gate(repo, "Write", {"file_path": spaced, "content": TITLE_ONLY})), names)
os.makedirs(os.path.dirname(spaced), exist_ok=True)
with open(spaced, "w") as f:
    f.write(TITLE_ONLY)
spaced_code, spaced_err = structure_gate(repo)
check("the stop gate holds a spaced name too", spaced_code, 2)
check("and asks it for the same sections", absent(spaced_err), names)
for command in ('echo x > "docs/adr/ADR-0009 new one.md"',
                "echo x > 'docs/adr/ADR-0009 new one.md'",
                "echo x > docs/adr/ADR-0009\\ new\\ one.md",
                'cp draft.md "docs/adr/ADR-0009 new one.md"'):
    check("a shell write to a spaced name is refused: %s" % command,
          "through the shell" in sections_gate(repo, "Bash", {"command": command}), True)

# A folder named with a leading "~", in a wiki clone outside the repository, as Kyroco named it:
# "ADR_DIR": "~/projects/kyroco.wiki/ADR". Decision records must live in the repository (MAST-48; Robert,
# November 20, 2026: "just use the local repo as ADR tracking the wiki has been causing a lot of problems").
# No gate checks such a folder, and the session is told so once, in one line, at its start.
home = os.path.join(T, "tilde-home")
wiki = os.path.join(home, "projects", "wiki")
os.makedirs(os.path.join(wiki, "ADR"))
git(wiki, "init", "-q")
with open(os.path.join(wiki, "README.md"), "w") as f:
    f.write("x\n")
git(wiki, "add", ".")
git(wiki, "commit", "-q", "-m", "first")
repo = make_repo("opted-in-tilde", {"ADR_DIR": "~/projects/wiki/ADR"})
record = os.path.join(wiki, "ADR", "ADR-0010-use-a-queue.md")
tilde_env = dict(BASE_ENV, CLAUDE_PROJECT_DIR=repo, HOME=home)
out = subprocess.run([sys.executable, SECTIONS_GATE],
                     input=json.dumps({"tool_name": "Write", "cwd": repo,
                                       "tool_input": {"file_path": record, "content": TITLE_ONLY}}),
                     capture_output=True, text=True, cwd=repo, env=tilde_env).stdout
check("a ~ folder outside the repository: the write gate holds nothing there", out.strip(), "")
out = subprocess.run([sys.executable, SECTIONS_GATE],
                     input=json.dumps({"tool_name": "Bash", "cwd": repo, "tool_input": {
                         "command": "echo x > ~/projects/wiki/ADR/ADR-0011-new.md"}}),
                     capture_output=True, text=True, cwd=repo, env=tilde_env).stdout
check("a ~ folder outside the repository: nor a shell write there", out.strip(), "")
with open(record, "w") as f:
    f.write(TITLE_ONLY)
r = subprocess.run(["bash", STRUCTURE_GATE], input="{}", capture_output=True, text=True,
                   cwd=repo, env=tilde_env)
check("a ~ folder outside the repository: the stop gate holds nothing there", r.returncode, 0)
start = subprocess.run([sys.executable, PRIME, "session-start"],
                       input=json.dumps({"session_id": "g", "cwd": repo, "hook_event_name": "SessionStart"}),
                       capture_output=True, text=True, cwd=repo,
                       env=dict(tilde_env, CLAUDE_PLUGIN_OPTION_KORIUM="off")).stdout.strip()
check("a ~ folder outside the repository: the session is told once, in one line, that records must live in it",
      len(start.splitlines()) == 1 and "ADR_DIR" in start and "must live in the repository" in start, True)

# ---------------------------------------------------------------- scenario 3
print("--- 3. what Masthead says names nothing of Kyroco's ---")
said = {
    "the write gate's refusal": write_reason,
    "the stop gate's refusal": err,
}
cap = subprocess.run(["bash", PROTOCOL, "gate-capture"], capture_output=True, text=True,
                     env=dict(BASE_ENV, TMPDIR=T),
                     input=json.dumps({"session_id": "g", "cwd": T, "agent_name": "zeina",
                                       "tool_name": "mcp__korium__agent_capture",
                                       "tool_input": {"source_agent": "thiago", "content": "x",
                                                      "thought_type": "insight",
                                                      "importance": 0.6}})).stdout
said["the capture gate's refusal"] = cap
said["the session-start context"] = subprocess.run(
    [sys.executable, PRIME, "session-start"], input="{}", capture_output=True, text=True,
    env=BASE_ENV).stdout
check("the capture gate did refuse, so its text is read", '"deny"' in cap, True)
for name, text in said.items():
    check("%s names nothing of Kyroco's" % name, KYROCO.findall(text), [])

# Every text a hook can print lives in its source, so read the sources themselves.
generic = sorted(
    os.path.join(HOOKS, f) for f in os.listdir(HOOKS)
    if f.endswith((".py", ".sh", ".json")) and not f.startswith("test-"))
hits = []
for path in generic:
    with open(path) as f:
        for n, line in enumerate(f, 1):
            if KYROCO.search(line):
                hits.append("%s:%d" % (os.path.basename(path), n))
check("no hook source names a Kyroco repo, app path, ADR number or person", hits, [])
for doc in ("skills/work-on/worker.md", "skills/work-on/foreman.md"):
    with open(os.path.join(PLUGIN, doc)) as f:
        check("%s says nothing happened \"on Kyroco\"" % doc, "on Kyroco" in f.read(), False)

# ---------------------------------------------------------------- scenario 4
print("--- 4. prime-context reads only the plugin's files and the repository's ---")
home = os.path.join(T, "home")
os.makedirs(os.path.join(home, ".claude", "hooks"))
for leaf in ("shared-run.sh", "hook-entries.json", "engram-protocol.sh"):
    with open(os.path.join(home, ".claude", "hooks", leaf), "w") as f:
        f.write("{}\n")
with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
    json.dump({"hooks": {}}, f)
repo = make_repo("prime")
log = os.path.join(T, "opened.txt")
# Run the hook under an audit hook that records every file it opens or lists.
runner = (
    "import sys, runpy\n"
    "log = open(%r, 'a')\n"
    "def audit(event, args):\n"
    "    if event in ('open', 'os.listdir', 'os.scandir') and args and isinstance(args[0], str):\n"
    "        log.write(args[0] + '\\n'); log.flush()\n"
    "sys.addaudithook(audit)\n"
    "sys.argv = [%r] + sys.argv[1:]\n"
    "runpy.run_path(%r, run_name='__main__')\n" % (log, PRIME, PRIME))
outputs = []
for mode, payload in (("session-start", {"session_id": "p", "cwd": repo}),
                      ("user-prompt", {"session_id": "p", "cwd": repo, "prompt": "open a PR"})):
    for plugin_env in ({}, {"CLAUDE_PLUGIN_ROOT": PLUGIN}):
        r = subprocess.run([sys.executable, "-c", runner, mode], input=json.dumps(payload),
                           capture_output=True, text=True, cwd=repo,
                           env=dict(BASE_ENV, HOME=home, CLAUDE_CONFIG_DIR=os.path.join(home, ".claude"),
                                    CLAUDE_PROJECT_DIR=repo, **plugin_env))
        outputs.append(r.stdout)
with open(log) as f:
    opened = sorted({line.strip() for line in f if line.strip()})
roots = [os.path.realpath(d) for d in (PLUGIN, repo, sys.prefix, sys.base_prefix)]


def allowed(path):
    """A root itself or anything under it. Python's importer lists the working folder, the repo's top."""
    real = os.path.realpath(path)
    return any(real == root or real.startswith(root + "/") for root in roots)


outside = [p for p in opened
           # Python's own bytecode cache and random source are Python's, not the hook's.
           if not allowed(p) and ".pyc" not in p
           and not p.startswith("/dev/") and p != os.path.realpath(log)]
check("prime-context opened a file at all, so the audit is live", bool(opened), True)
check("every file prime-context opened is the plugin's, the repository's or Python's", outside, [])
check("no ~/.claude/hooks file was opened",
      [p for p in opened if p.startswith(os.path.join(home, ".claude"))], [])
check("no run reports pre-plugin shared gates",
      [o for o in outputs if "SHARED GATES" in o or ".claude/hooks" in o], [])
check("the PR prompt still gets the plugin's procedure",
      any("Opening a PR." in o for o in outputs), True)

shutil.rmtree(T, ignore_errors=True)
print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
