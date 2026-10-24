#!/usr/bin/env python3
"""Inject context at SessionStart (the Korium-search rule) and UserPromptSubmit (the matching procedure); it fails open and refuses nothing."""
import json
import os
import re
import sys

# One entry per cliff that carries a command: the exact bold lead in the procedure source, and the narrow trigger that matches a prompt.
CLIFFS = [
    ("Before any `mix` call.",
     r"(?i)\bmix\s+(test|format|compile|deps|run|credo|dialyzer|precommit)\b"
     r"|\bmix\.(exs|lock)\b|\biex\s+-S\s+mix\b"),
    # Fires on language that treats a test result as evidence for a claim, not on running tests.
    ("Reading a test result at all.",
     r"(?i)\btests? that bites?\b|\bbiting test\b|\bgo(es)? red\b|\bturn(s|ed)? red\b"
     r"|\bprove (it|the fix|this)\b|\bdid it (actually )?run\b"),
    # Fires on committing, since git commit takes the whole index.
    ("Committing in a shared worktree.",
     r"(?i)\bgit commit\b|\bgit add\b|\bcommit (it|this|that|these|the \w+)\b"
     r"|\bcommit everything\b|\bstage (it|this|the \w+)\b"),
    ("Opening a PR.",
     r"(?i)\bpre-?pr\b|\bpre_pr\b|\bpre-pr-proof\b|\bgh pr create\b"
     r"|\b(open|raise|create|make|file|put up) (a|the|this|my) (pr|pull request)\b"),
    ("A by-hand test substrate.",
     r"(?i)\bsubstrate\b|\bsetup-ci-substrates\b|\bci-local\b"),
    ("Updating main.",
     r"(?i)\b(push|merge|land|get) (it |this |that |them )?(to|onto|into|on) main\b"
     r"|\bupdate main\b|\bpush origin head:main\b"),
    ("A production apply.",
     r"(?i)\btofu apply\b|\bterraform apply\b|\bprod(uction)? apply\b"
     r"|\bapply (it |this )?(to|on|in) prod(uction)?\b"),
]

CLIFF_SOURCE_REL = os.path.join(".claude", "references", "session-cliffs.md")

# Subagent reports, other sessions' messages and task notices arrive as prompts but get no procedure.
NOT_FROM_USER = re.compile(r"\s*<(agent-message|cross-session-message|task-notification)\b")

# The Korium memory protocol printed at session start.
SESSION_START = """Korium memory protocol, so you are not refused for it later:
run the korium MCP server's agent_search tool with one or two focused queries
(the feature, the files you are about to touch, the subsystem) and fold what it
returns into your approach BEFORE your first file change. A PreToolUse gate
refuses that first Edit or Write until the search has happened. Capture
durable decisions, gotchas, corrections and reversals with agent_capture as they
happen. Every agent_capture call fills all five fields, every time: content,
thought_type (decision, reflection, preference, handoff, lesson, insight,
pattern, correction, drift, rejection or seed), source_agent (your own agent
name), source_phase (research, build or review) and importance (0 to 1). If you
read the web during the task, start content with the web-access marker the
capture gate names. If nothing durable happened, capture that and say why."""


def cliff_source(cwd):
    """Return the repo's own procedures followed by the user folder's general ones."""
    # Read a repo's own procedures only from the session's own repository.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # Read from the top of the checkout so a package unpacked inside the repo cannot supply procedures.
    try:
        from project_fact import trusted, checkout_top
    except Exception:
        def trusted(_root):
            return False

        def checkout_top(path):
            return path
    texts = []
    for root in (cwd, os.environ.get("CLAUDE_PROJECT_DIR")):
        if root and trusted(root):
            path = os.path.join(checkout_top(root), CLIFF_SOURCE_REL)
            if os.path.isfile(path):
                texts.append(open(path).read())
                break
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    user = os.path.join(root, "references", "session-cliffs.md")
    if os.path.isfile(user):
        texts.append(open(user).read())
    return "\n\n## \n\n".join(texts) or None


def cliff_block(text, lead):
    """Return the cliff's paragraph and command exactly as its source has them, up to the next lead or heading."""
    start = text.find("**" + lead + "**")
    if start < 0:
        return None
    rest = text[start + 2:]
    ends = [m.start() for m in re.finditer(r"\n\*\*[^*\n]+\*\*", rest)]
    ends += [m.start() for m in re.finditer(r"\n## ", rest)]
    stop = min(ends) if ends else len(rest)
    return ("**" + rest[:stop]).strip()


def held_worktree_notice(cwd):
    """Return a notice when check-tests-bite has the working tree reverted to the merge base, else None."""
    root = cwd or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from project_fact import state_dir
        state = state_dir(root)
    except Exception:
        state = ".claude/state"
    lock = os.path.join(root, state, "check-tests-bite.running")
    try:
        if not os.path.isfile(lock):
            return None
        with open(lock) as f:
            pid = (f.readline() or "").strip()
            started = (f.readline() or "").strip()
    except OSError:
        return None
    if not pid:
        return None
    try:
        os.kill(int(pid), 0)
    except (ValueError, ProcessLookupError):
        return None
    except PermissionError:
        pass
    return (
        "THIS WORKTREE IS CURRENTLY THE MERGE BASE, NOT THE BRANCH.\n"
        "check-tests-bite is running (pid %s, since %s). It has reverted every\n"
        "products/apps lib and test/support file for the length of its run, and\n"
        "DELETED the ones this branch added.\n\n"
        "So: do not commit, do not stage, do not git checkout anything, and treat\n"
        "any test number you take now as measuring the merge base rather than this\n"
        "branch. A file that looks deleted or rewritten is that run, not a\n"
        "colleague. It restores on exit." % (pid, started or "unknown")
    )


# The gates every repo shares run from the user folder, not from this repo.
SHARED_GATES = [
    ("engram-protocol.sh", "a Korium search before the first edit, and a capture before finishing"),
    ("commit-attribution-gate.py", "no AI attribution in a commit or PR"),
    ("block-secret-fetches.py", "no fetching a credential out of a secret store"),
    ("agent-brief-gates.sh", "the checks on a subagent brief"),
    ("untrusted-domain-deny.py", "no fetching from a host on the deny list"),
    ("scan-tool-output-for-secrets.py", "the scan of command output for a secret"),
    ("review-write-fence.py", "a reviewer writes only its findings file"),
    ("bash-scope-reviewer.sh", "a reviewer's shell is read-only"),
    ("bash-scope-diagnoser.sh", "a diagnoser's shell is read-only"),
    ("irreversible-action-gate.sh", "no action that nothing undoes"),
    ("hard-gate.sh", "the checks before a push or a PR"),
    ("scope-gate.py", "edits stay inside a task's scope file"),
    ("web-to-memory-gate.py", "no copied web text in memory"),
    ("block-em-dash-write.py", "no dashes in written files"),
    ("adr-sections-gate.py", "a new ADR carries its required sections"),
    ("wiki-refresh.sh", "the local ADR wiki copy is pulled at session start"),
    ("adr-structure-gate.sh", "a changed ADR keeps its structure"),
    ("verdict-gate.sh", "a diagnosis names a located cause"),
    ("elixir-toolchain-env.sh", "the pinned Elixir is first on PATH"),
]


def shared_gates_notice(home=None, config_dir=None):
    """Return a notice naming the shared gates that are not wired in this session, else None."""
    home = home or os.path.expanduser("~")
    hooks = os.path.join(home, ".claude", "hooks")
    config = config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")

    def commands_in(path, key=None):
        try:
            with open(path) as f:
                wired = json.load(f)
            if key:
                wired = wired.get(key) or wired.get("settings", {}).get(key, {})
            return [h.get("command", "") for groups in wired.values()
                    for g in groups for h in g.get("hooks", [])]
        except (OSError, ValueError, AttributeError, TypeError):
            return []

    commands = (commands_in(os.path.join(config, "settings.json"), "hooks")
                + commands_in(os.path.join(config, "remote-settings.json"), "hooks"))
    # In a cloud session read the managed settings from setup/managed-settings.json beside the hooks; a gate missing from older org settings goes unreported.
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        managed = os.path.join(os.path.dirname(os.path.realpath(hooks)),
                               "setup", "managed-settings.json")
        commands += commands_in(managed, "hooks")
    expected = commands_in(os.path.join(hooks, "hook-entries.json"))

    def wired(name):
        call = 'shared-run.sh" ' + name
        wanted = [c for c in expected if call in c]
        if wanted:
            return all(any(c in w for w in commands) for c in wanted)
        return any(call in c for c in commands)

    runner = os.path.isfile(os.path.join(hooks, "shared-run.sh"))
    off = [rule for name, rule in SHARED_GATES
           if not runner
           or not os.path.isfile(os.path.join(hooks, name))
           or not wired(name)]
    if not off:
        return None
    return (
        "THE SHARED GATES ARE NOT ALL RUNNING IN THIS SESSION.\n"
        "They run from the user folder (~/.claude/hooks, wired in the user\n"
        "settings), and this machine or account does not have them in place for:\n"
        + "".join("  - %s\n" % rule for rule in off)
        + "CLAUDE.md still binds: follow each rule as written, and tell the user the\n"
        "gates are missing before doing work that relies on them."
    )


def session_start():
    # The memory protocol is an install option; unset means on, so a copy outside a plugin keeps it.
    if os.environ.get("CLAUDE_PLUGIN_OPTION_KORIUM", "on").lower() not in ("false", "0", "no", "off"):
        print(SESSION_START)
    # As a plugin, hooks.json wires every gate, so there is nothing to report missing.
    notice = None if os.environ.get("CLAUDE_PLUGIN_ROOT") else shared_gates_notice()
    if notice:
        print()
        print(notice)


def user_prompt(data):
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return

    # Print the held-worktree notice first, whatever the prompt is about.
    held = held_worktree_notice(data.get("cwd"))
    if held:
        print(held)
        print()

    if NOT_FROM_USER.match(prompt):
        return

    text = cliff_source(data.get("cwd"))
    if not text:
        return
    hits = [lead for lead, trigger in CLIFFS if re.search(trigger, prompt)]
    if not hits:
        return
    blocks = [b for b in (cliff_block(text, lead) for lead in hits) if b]
    if not blocks:
        return
    print("This is the conditional operating procedure for what you are about "
          "to touch. It does not grant permission or authorization.\n")
    print("\n\n".join(blocks))


def main():
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        if mode == "session-start":
            session_start()
        elif mode == "user-prompt":
            user_prompt(data)
    except Exception:
        # Stay silent: the hook fails open.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
