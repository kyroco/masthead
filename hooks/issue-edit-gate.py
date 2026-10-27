#!/usr/bin/env python3
"""PreToolUse gate on `gh issue edit`: refuses a new body that drops a line
quoted as the user's, or that carries a [NEEDS CLARIFICATION] question with no
"looked in:" part naming the decision record, the README rule and the Korium
query searched (issue #21). Fails open on broken plumbing.

A line quoted as the user's is a double-quoted span of three or more words on
a line that names the user: the first name from `git config user.name` in the
checkout, or the words "the user". A bullet that is only a quote inherits the
closest line above it that is not a bullet, so a list under a heading such as
"**Robert, October 20:**" is the user's too. A document quote (an ADR line, a
README rule) sits on a line without the user's name and may change freely.

The old body comes from `gh issue view --json body`. When gh cannot answer,
the edit itself would fail, so only the question check runs. A body the gate
cannot read (piped in, or a file that is not there) is refused, since an
unreadable body would be a way around the check.
"""
import json
import os
import re
import shlex
import subprocess
import sys

GH_ISSUE_EDIT = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*gh\s+issue\s+edit(?:\s|$)"
)
SEGMENT_SPLIT = re.compile(r"[;\n]|\|\|?|&&?")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)\n\2[ \t]*(?:\n|$)", re.S)
BODY_FLAGS = {"--body", "-b"}
FILE_FLAGS = {"--body-file", "-F"}
REPO_FLAGS = {"--repo", "-R"}
QUOTED = re.compile(r'"([^"\n]+)"')
QUESTION = re.compile(r"\[NEEDS CLARIFICATION\b[^\]\n]*\]?", re.I)
LOOKED_IN = re.compile(r"looked in:(.*)", re.I | re.S)
NAMES = [
    ("the decision record", re.compile(r"\bADR\b|decision record", re.I)),
    ("the README rule", re.compile(r"\bREADME\b", re.I)),
    ("the Korium query", re.compile(r"\bKorium\b", re.I)),
]


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def normalize(text):
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text)


def edit_segments(command):
    return [seg for seg in SEGMENT_SPLIT.split(command) if GH_ISSUE_EDIT.search(seg)]


def parse_edit(segment):
    """The issue reference, the repo, and how the body arrives: ('text', body),
    ('file', path), ('stdin', None) or (None, None) when no body is given."""
    try:
        words = shlex.split(segment, comments=False, posix=True)
    except ValueError:
        words = segment.split()
    ref = repo = None
    how = (None, None)
    i = 0
    seen_edit = False
    while i < len(words):
        word = words[i]
        flag, _, inline = word.partition("=")
        nxt = words[i + 1] if i + 1 < len(words) else None
        if not seen_edit:
            seen_edit = word == "edit"
        elif flag in BODY_FLAGS:
            how = ("text", inline if _ else (nxt or ""))
            i += 0 if _ else 1
        elif flag in FILE_FLAGS:
            path = inline if _ else (nxt or "")
            how = ("stdin", None) if path == "-" else ("file", path)
            i += 0 if _ else 1
        elif flag in REPO_FLAGS:
            repo = inline if _ else nxt
            i += 0 if _ else 1
        elif word.startswith("-"):
            pass
        elif ref is None:
            ref = word
        i += 1
    return ref, repo, how


def body_from(command, segment, cwd):
    ref, repo, (how, value) = parse_edit(segment)
    if how is None:
        return ref, repo, None, None
    if how == "text":
        return ref, repo, value, None
    if how == "stdin":
        docs = HEREDOC.findall(command)
        if docs:
            return ref, repo, docs[-1][2] + "\n", None
        return ref, repo, None, "the body comes from standard input with no heredoc in the command"
    path = value if os.path.isabs(value) else os.path.join(cwd, value)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return ref, repo, fh.read(400_000), None
    except Exception:
        return ref, repo, None, "the body file {} cannot be read".format(value)


def old_body(ref, repo, cwd):
    if not ref:
        return None
    args = ["gh", "issue", "view", ref, "--json", "body", "--jq", ".body"]
    if repo:
        args += ["--repo", repo]
    try:
        out = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=12, check=False)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def user_names(cwd):
    names = ["the user"]
    try:
        out = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True,
                             cwd=cwd, timeout=5, check=False)
        first = out.stdout.strip().split()
        if first:
            names.append(first[0])
    except Exception:
        pass
    return names


def user_quotes(body, names):
    """Quoted spans of three or more words on lines that name the user, each
    with its line number."""
    pattern = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9])", re.I)
    found = []
    context = ""
    for number, line in enumerate(body.split("\n"), 1):
        stripped = line.strip()
        if not stripped:
            continue
        is_bullet_quote = bool(re.match(r"^(?:[-*+]|\d+[.)])\s*\"", stripped))
        if not is_bullet_quote:
            context = line
        named = pattern.search(line) or (is_bullet_quote and pattern.search(context))
        if not named:
            continue
        for span in QUOTED.findall(line):
            if len(span.split()) >= 3:
                found.append((number, span))
    return found


def missing_quotes(old, new, names):
    flat_new = normalize(new)
    return [(n, q) for n, q in user_quotes(old, names) if normalize(q) not in flat_new]


def bad_questions(new):
    out = []
    for number, line in enumerate(new.split("\n"), 1):
        for q in QUESTION.findall(line):
            m = LOOKED_IN.search(q)
            if not m:
                out.append((number, q, "has no \"looked in:\" part"))
                continue
            lacking = [label for label, rx in NAMES if not rx.search(m.group(1))]
            if lacking:
                out.append((number, q, "its \"looked in:\" part does not name " + " or ".join(lacking)))
    return out


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not command:
        sys.exit(0)
    segments = edit_segments(command)
    if not segments:
        sys.exit(0)
    cwd = data.get("cwd") or os.getcwd()

    for segment in segments:
        ref, repo, new, problem = body_from(command, segment, cwd)
        if problem:
            deny("Blocked: this issue edit cannot be checked because {}. Write the body with "
                 "`gh issue edit <n> --body-file - <<'BODY'` ... `BODY`, or `--body-file <path>`, "
                 "so the check can read it (issue #21).".format(problem))
        if new is None:
            continue

        questions = bad_questions(new)
        if questions:
            number, q, why = questions[0]
            deny("Blocked: line {} of the new body {}: {}\nEvery [NEEDS CLARIFICATION] line says "
                 "where the answer was looked for, as `[NEEDS CLARIFICATION: the question; looked in: "
                 "<decision-record section>, <README rule>, Korium \"<query>\"]`. Look there first; a "
                 "question a source settles is written into the issue with the line quoted, not asked "
                 "(issue #21).".format(number, why, q[:120]))

        old = old_body(ref, repo, cwd)
        if old is None:
            continue
        gone = missing_quotes(old, new, user_names(cwd))
        if gone:
            number, quote = gone[0]
            deny("Blocked: the new body drops a line quoted as the user's (line {} of the current "
                 "body): \"{}\". Every line the user wrote stays, quoted under the scenario it rules on; "
                 "edit only the part that fails and keep the rest as it is (issue #21).".format(
                     number, quote[:160]))
    sys.exit(0)


if __name__ == "__main__":
    main()
