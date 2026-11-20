#!/usr/bin/env python3
"""Inject context at SessionStart (the Korium-search rule) and UserPromptSubmit (the matching procedure); it fails open and refuses nothing."""
import json
import os
import re
import shlex
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


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from project_fact import trusted, project_root, repo_root, RepoUnclear
except Exception:
    def trusted(_root):
        return False

    def project_root(cwd=None):
        return cwd or os.getcwd()

    def repo_root(_path, _cwd):
        raise RepoUnclear("Masthead: project_fact.py could not be read, so the repository is unclear.")

    class RepoUnclear(Exception):
        pass


def repo_unclear(cwd):
    """repo_root()'s one line when the repository the shell at `cwd` is about is unclear, else None."""
    try:
        repo_root(None, cwd or os.getcwd())
    except RepoUnclear as unclear:
        return str(unclear)
    return None


def cliff_source(cwd):
    """Return the repo's own procedures followed by the plugin's general ones."""
    # Read a repo's own procedures only from one of the workspace's repositories, the one the shell is about
    # (project_fact.repo_root), at the top of its checkout so a package unpacked inside it cannot supply them.
    texts = []
    root = project_root(cwd)
    if trusted(root):
        path = os.path.join(root, CLIFF_SOURCE_REL)
        if os.path.isfile(path):
            texts.append(open(path).read())
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin = os.path.join(root, "references", "session-cliffs.md")
    if os.path.isfile(plugin):
        texts.append(open(plugin).read())
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
    root = project_root(cwd)
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
        "check-tests-bite is running (pid %s, since %s). It has reverted the\n"
        "files this branch changed for the length of its run, and DELETED the\n"
        "ones this branch added.\n\n"
        "So: do not commit, do not stage, do not git checkout anything, and treat\n"
        "any test number you take now as measuring the merge base rather than this\n"
        "branch. A file that looks deleted or rewritten is that run, not a\n"
        "colleague. It restores on exit." % (pid, started or "unknown")
    )


def hand_workspace():
    """Write the workspace to CLAUDE_ENV_FILE, so every later shell command of the session, where Claude Code
    sets no CLAUDE_PROJECT_DIR, knows it as MASTHEAD_WORKSPACE (project_fact.workspace)."""
    target, space = os.environ.get("CLAUDE_ENV_FILE"), os.environ.get("CLAUDE_PROJECT_DIR")
    if not target or not space:
        return
    with open(target, "a") as handle:
        handle.write("export MASTHEAD_WORKSPACE={}\n".format(shlex.quote(os.path.realpath(space))))


def session_start(data):
    hand_workspace()
    # When the repository is unclear, say so once, here; each skill then stops with the same line.
    unclear = repo_unclear(data.get("cwd"))
    if unclear:
        print(unclear)
    # An ADR folder outside the repository is not checked, and the session is told so once, here.
    try:
        import adr_shape
        line = adr_shape.outside_line(project_root(data.get("cwd")))
    except Exception:
        line = None
    if line:
        print(line)
    # The memory protocol is an install option; unset means on, so a copy outside a plugin keeps it.
    if os.environ.get("CLAUDE_PLUGIN_OPTION_KORIUM", "on").lower() not in ("false", "0", "no", "off"):
        print(SESSION_START)


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


def show(lead):
    """Print one procedure exactly as user_prompt would inject it from this folder."""
    # Only a lead the hook declares, named with or without its closing period.
    leads = [known for known, _ in CLIFFS if known.rstrip(".") == lead.rstrip(".")]
    text = cliff_source(os.getcwd())
    block = cliff_block(text, leads[0]) if text and leads else None
    if block:
        print(block)


def main():
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        # A worker reads the PR steps the hook injects with: prime-context.py show "Opening a PR".
        if mode == "show":
            if len(sys.argv) > 2:
                show(sys.argv[2])
            sys.exit(0)
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        if mode == "session-start":
            session_start(data)
        elif mode == "user-prompt":
            user_prompt(data)
    except Exception:
        # Stay silent: the hook fails open.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
