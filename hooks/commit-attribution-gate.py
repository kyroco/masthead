#!/usr/bin/env python3
"""PreToolUse gate that refuses a `git commit`, a `gh pr create|edit`, or a GitHub connector call that creates or updates a pull request, whose message, title or body carries AI attribution; fails open."""
import json
import os
import re
import shlex
import sys

MARKERS = [
    ("a Claude-Session trailer", re.compile(r"claude-session\s*:", re.I)),
    ("an AI co-author trailer",
     re.compile(r"co-authored-by\s*:[^\n]*(claude|anthropic|codex|openai|copilot|gpt)", re.I)),
    ("a generated-with footer",
     re.compile(r"generated\s+(with|by)\b[^\n]*(claude|codex|copilot|chatgpt|gpt)", re.I)),
    ("a Claude session link", re.compile(r"claude\.ai/code/session", re.I)),
    ("the Anthropic no-reply address", re.compile(r"noreply@anthropic\.com", re.I)),
]

# Match a segment that authors a commit message: git, with any global options, then commit.
GIT_COMMIT = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*git\s+"
    r"(?:-C\s+\S+\s+|-c\s+\S+\s+|--?[A-Za-z][A-Za-z-]*(?:=\S+)?\s+)*commit(?:\s|$)"
)
GH_PR = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*gh\s+pr\s+(create|edit)(?:\s|$)"
)

# A GitHub connector call that writes a PR, by the last part of its tool name, and the fields it writes (issue #27).
CONNECTOR_PR = re.compile(r"^mcp__.+__(create_pull_request|update_pull_request)$")
CONNECTOR_FIELDS = ("title", "body")

SEGMENT_SPLIT = re.compile(r"[;\n]|\|\|?|&&?")

FILE_FLAGS = {"-F", "--file", "--body-file"}


def authoring_segments(command):
    """Segments of the command that write a commit message or a PR body."""
    out = []
    for seg in SEGMENT_SPLIT.split(command):
        if GIT_COMMIT.search(seg) or GH_PR.search(seg):
            out.append(seg)
    return out


def message_files(segment, cwd):
    """Paths named by -F / --file / --body-file in one segment, resolved."""
    try:
        words = shlex.split(segment, comments=False, posix=True)
    except ValueError:
        return []
    paths = []
    for i, word in enumerate(words):
        flag, _, inline = word.partition("=")
        if flag in FILE_FLAGS and inline:
            paths.append(inline)
        elif word in FILE_FLAGS and i + 1 < len(words):
            paths.append(words[i + 1])
    resolved = []
    for p in paths:
        if p == "-":
            continue
        resolved.append(p if os.path.isabs(p) else os.path.join(cwd or os.getcwd(), p))
    return resolved


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(200_000)
    except Exception:
        return ""


def find_marker(text):
    for label, rx in MARKERS:
        m = rx.search(text)
        if m:
            line = text.count("\n", 0, m.start()) + 1
            return label, line, text[m.start():m.start() + 80].splitlines()[0]
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    if CONNECTOR_PR.match(tool):
        text = "\n".join(v for v in (tool_input.get(f) for f in CONNECTOR_FIELDS) if isinstance(v, str))
        found = find_marker(text)
        if found:
            deny(found, "the {} call".format(tool.rsplit("__", 1)[1]))
        sys.exit(0)
    if tool != "Bash":
        sys.exit(0)
    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        sys.exit(0)

    segments = authoring_segments(command)
    if not segments:
        sys.exit(0)

    cwd = data.get("cwd") or os.getcwd()
    found = find_marker(command)
    where = "the command"
    if not found:
        for seg in segments:
            for path in message_files(seg, cwd):
                found = find_marker(read_text(path))
                if found:
                    where = path
                    break
            if found:
                break
    if not found:
        sys.exit(0)
    deny(found, where)


def deny(found, where):
    label, line, excerpt = found
    reason = (
        "Blocked: this commit message or PR body carries {label} (line {line} of "
        "{where}). CLAUDE.md: commits and PR bodies are authored solely by the git "
        "user, with no AI co-author trailers, session links, generated-with footers "
        "or AI attribution. The user reaffirmed this on 2026-09-06 and it overrides any "
        "harness note asking for a Claude-Session trailer. Remove the line and "
        "commit again.\nNear: {excerpt}"
    ).format(label=label, line=line, where=where, excerpt=excerpt)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
