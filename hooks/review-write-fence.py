#!/usr/bin/env python3
"""PreToolUse hook that lets reviewer and security-reviewer agents write only their own review file or the review scratch folder, and denies every other write; fails closed."""

import json
import os
import re
import sys

FILES = {
    "reviewer": re.compile(r"findings-reviewer-[a-z0-9][a-z0-9-]*\.json"),
    "security-reviewer": re.compile(r"findings-security-reviewer(-[a-z0-9][a-z0-9-]*)?\.json"),
}
WANT = {
    "reviewer": "findings-reviewer-<angle>-<name>.json",
    "security-reviewer": "findings-security-reviewer-<name>.json",
}
SCRATCH = "scratch"
AGENT_LIST_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bash-scope-reviewer.sh")
IDENTITY_FIELDS = ("agent_type", "subagent_type", "agent_name")
# Only this plugin's agents are fenced; another plugin's agent of the same name is not ours to police.
PLUGIN_PREFIX = "masthead:"
# Take the repo's state folder from project_fact.py, else the default.
try:
    from project_fact import state_dir as _state_dir
    STATE_DIR = _state_dir()
except Exception:
    STATE_DIR = ".claude/state"
REVIEW_REL = STATE_DIR + "/review"
REVIEW_PARTS = tuple(part.casefold() for part in REVIEW_REL.split("/"))
TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "review-write-fence: " + reason,
        }
    }))
    sys.exit(0)


def identity_pattern():
    """The identity rule, built from REVIEWER_AGENTS in bash-scope-reviewer.sh."""
    with open(AGENT_LIST_SOURCE) as handle:
        match = re.search(r'^REVIEWER_AGENTS="([a-z0-9|-]+)"$', handle.read(), re.M)
    if not match:
        raise ValueError(f"no REVIEWER_AGENTS line in {AGENT_LIST_SOURCE}")
    names = [n for n in match.group(1).split("|") if n]
    return re.compile(r"^(" + "|".join(re.escape(n) for n in names) + r")([-_.:]|$)")


def governing_agent(payload, pattern):
    """The governed agent this call belongs to, or None."""
    for field in IDENTITY_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            continue
        # A masthead: name is ours when any of its parts names a reviewer, so a subfolder of agents/ cannot hide one;
        # the last such part is the agent, since Claude Code puts the folders first.
        parts = value[len(PLUGIN_PREFIX):].split(":") if value.startswith(PLUGIN_PREFIX) else [value]
        for part in reversed(parts):
            match = pattern.match(part)
            if match:
                return match.group(1)
    return None


def review_file(path, cwd, pattern):
    """The resolved review folder when the path is an allowed review file, else None."""
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    if not pattern.fullmatch(os.path.basename(path)) or os.path.islink(path):
        return None
    folder = os.path.realpath(os.path.dirname(path))
    parts = folder.split(os.sep)
    depth = len(REVIEW_PARTS)
    if len(parts) <= depth or tuple(part.casefold() for part in parts[-depth:]) != REVIEW_PARTS:
        return None
    checkout = os.sep.join(parts[:-depth]) or os.sep
    if not os.path.exists(os.path.join(checkout, ".git")):
        return None
    return folder


def scratch_file(path, cwd):
    """True when the path is inside <checkout>/<state>/review/scratch with no symlink on the way."""
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    path = os.path.normpath(path)
    if os.path.islink(path):
        return False
    parts = path.split(os.sep)
    window = list(REVIEW_PARTS) + [SCRATCH]
    depth = len(window)
    for i in range(len(parts) - depth):
        if [part.casefold() for part in parts[i + 1:i + 1 + depth]] != window or i + 1 + depth >= len(parts):
            continue
        checkout = os.sep.join(parts[:i + 1]) or os.sep
        if not os.path.exists(os.path.join(checkout, ".git")):
            return False
        # Require that the deepest existing folder on the way resolves to itself, so no symlink lies between the checkout and it.
        existing = os.path.dirname(path)
        while not os.path.lexists(existing):
            existing = os.path.dirname(existing)
        expected = os.path.normpath(os.path.join(os.path.realpath(checkout), os.path.relpath(existing, checkout)))
        return os.path.realpath(existing) == expected
    return False


def check(payload, agent):
    if agent not in FILES:
        deny(f"{agent} is a review agent in bash-scope-reviewer.sh, but no review file is defined for it here, "
             "so its writes are refused until review-write-fence.py names one.")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        deny(f"{agent}'s {payload.get('tool_name')} call carried no readable tool_input.")
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if isinstance(path, str) and path and scratch_file(path, payload.get("cwd")):
        return
    folder = review_file(path, payload.get("cwd"), FILES[agent]) if isinstance(path, str) and path else None
    if folder is None:
        deny(f"{agent} may write only {REVIEW_REL}/{WANT[agent]}, or anything under "
             f"{REVIEW_REL}/{SCRATCH}/, in the checkout under review, and this call writes "
             f"{path or '(no path)'}. A reviewer never edits the code it judges or another reviewer's "
             f"file; to run a test against changed code, make a throwaway worktree under "
             f"{REVIEW_REL}/{SCRATCH}/ and change that. If this is the file your dispatch names and it "
             "was still refused, put the findings in your final reply and say the write was refused.")


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        deny("the tool call did not parse, so it cannot be shown to come from anyone but a reviewer.")
    if not isinstance(payload, dict) or payload.get("tool_name") not in TOOLS:
        return
    try:
        pattern = identity_pattern()
    except Exception as err:
        if any(isinstance(payload.get(f), str) and payload.get(f) for f in IDENTITY_FIELDS):
            deny(f"the review agent list could not be read ({type(err).__name__}: {err}), so a call from "
                 "any named agent is refused.")
        agent = None
    else:
        agent = governing_agent(payload, pattern)
    if agent is None:
        return
    try:
        check(payload, agent)
    except SystemExit:
        raise
    except Exception as err:  # fail closed for a governed agent
        deny(f"checking {agent}'s write failed ({type(err).__name__}: {err}), so it is refused.")


if __name__ == "__main__":
    main()
