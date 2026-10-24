#!/usr/bin/env python3
"""Stop hook: remind once per turn, on stderr and never blocking, when a reply reported a finding and nothing was captured since the user last spoke; logs each turn."""
import json
import os
import re
import sys
import time

LOG = os.path.expanduser("~/.claude/capture-reminder.log")

# Words that mark a reply as delivering a finding; each entry is a name and a pattern, kept narrow.
TRIGGERS = [
    ("blocker", re.compile(r"\bblockers?\b", re.I)),
    ("verdict", re.compile(r"\b(verdict|adjudicat\w+)\b", re.I)),
    ("root_cause", re.compile(r"\broot cause\b", re.I)),
    ("confirmed", re.compile(r"\b(confirmed|refuted|disproved|disproven)\b", re.I)),
    ("correction", re.compile(r"\b(i was wrong|got that wrong|correction|supersed\w+|stale)\b", re.I)),
    ("measured", re.compile(r"\bmeasured\b", re.I)),
    ("defect", re.compile(r"\b(defect|regression|silently|never fires?|can never)\b", re.I)),
]

# A short reply ending in a question mark is asking, not reporting.
QUESTION_TAIL = re.compile(r"\?\s*$")


def state_dir():
    directory = os.path.join(os.environ.get("TMPDIR", "/tmp"), "claude-capture-reminder")
    os.makedirs(directory, exist_ok=True)
    return directory


def safe_name(value):
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(value))


def capture_marker_mtime(session):
    """The time of the last successful capture in this session, or 0."""
    base = os.path.join(os.environ.get("TMPDIR", "/tmp"), "claude-engram", safe_name(session))
    try:
        return os.path.getmtime(os.path.join(base, "captured"))
    except Exception:
        return 0.0


def turn_started_mtime(session):
    """The time the user last spoke, taken from the marker this hook writes each turn, or 0."""
    path = os.path.join(state_dir(), safe_name(session) + "--turn")
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def stamp_turn(session):
    path = os.path.join(state_dir(), safe_name(session) + "--turn")
    try:
        open(path, "w").close()
    except Exception:
        pass


def matched_triggers(message):
    return [name for name, pattern in TRIGGERS if pattern.search(message)]


def log_row(session, fired, triggers, words, captured_recently):
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session": str(session)[:64],
        "fired": fired,
        "triggers": triggers,
        "words": words,
        "captured_since_user_spoke": captured_recently,
    }
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as handle:
            handle.write(json.dumps(row) + "\n")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if not isinstance(data, dict):
        sys.exit(0)

    session = data.get("session_id", "unknown")
    message = data.get("last_assistant_message") or ""
    if not isinstance(message, str):
        sys.exit(0)

    words = len(message.split())
    triggers = matched_triggers(message)

    # A capture after the user last spoke belongs to this turn.
    captured_recently = capture_marker_mtime(session) > turn_started_mtime(session)

    short_question = words < 60 and bool(QUESTION_TAIL.search(message.strip()))
    fired = bool(triggers) and not captured_recently and not short_question

    log_row(session, fired, triggers, words, captured_recently)
    stamp_turn(session)

    if fired:
        names = ", ".join(triggers)
        sys.stderr.write(
            "Korium: this reply reported a finding ({}) and nothing has been "
            "captured since the user last spoke. If a later session would need "
            "it - a verdict, a blocker, a measured number, a correction to "
            "something already stored - write it with agent_capture now. If it "
            "was already captured, or it is only true of this conversation, "
            "carry on; this is a reminder, not a gate.\n".format(names)
        )

    sys.exit(0)


main()
