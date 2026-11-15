#!/usr/bin/env python3
"""json_field.py: what the shell gates ask of jq, for a machine without jq (MAST-37).

The gates call jq when it is installed and this file when it is not, so a gate
refuses the same calls either way instead of letting everything through.

  json_field.py FILTER
      Read JSON on stdin and print FILTER's value the way `jq -r` does. FILTER
      is one or more paths such as `.tool_input.command`, joined by ` // `; the
      last may be a "double-quoted" string or `empty`. As in jq, a path whose
      value is missing, null or false falls through to the next one.
  json_field.py --deny REASON
      Print a PreToolUse deny decision carrying REASON.
  json_field.py --reasons
      Print every permissionDecisionReason in the JSON on stdin, at any depth
      and in any number of JSON values, joined by a blank line.

A filter it does not read, or input that is not JSON, exits 2 and prints
nothing, which the gates read as the field being absent.
"""
import json
import re
import sys

PATH = re.compile(r"^(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
STRING = re.compile(r'^"((?:[^"\\]|\\.)*)"$')


def parse(text):
    """The filter as a list of ("path", [keys]), ("string", value) or ("empty", None)."""
    parts = [p.strip() for p in text.split("//")]
    out = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if PATH.match(part):
            out.append(("path", part[1:].split(".")))
        elif last and part == "empty":
            out.append(("empty", None))
        elif last and STRING.match(part):
            out.append(("string", json.loads(part)))
        else:
            raise ValueError(part)
    return out


def walk(data, keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def show(value):
    """As jq -r prints one value."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def values(text):
    """Every JSON value in a stream of them, as jq reads its input."""
    decoder, i, found = json.JSONDecoder(), 0, []
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return found
        value, i = decoder.raw_decode(text, i)
        found.append(value)


def reasons(value, found):
    if isinstance(value, dict):
        if "permissionDecisionReason" in value:
            found.append(str(value["permissionDecisionReason"]))
        for item in value.values():
            reasons(item, found)
    elif isinstance(value, list):
        for item in value:
            reasons(item, found)


def main(argv):
    # Claude Code sends UTF-8 whatever the locale, so read and write UTF-8; a Latin-1 locale would
    # otherwise fail on an arrow in a command, and the gate would read nothing (MAST-37).
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8", errors="surrogateescape")
    if len(argv) == 2 and argv[0] == "--deny":
        # ASCII JSON, so no locale or stray byte can stop the refusal being printed.
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": argv[1]}}))
        return 0
    if argv == ["--reasons"]:
        found = []
        try:
            for value in values(sys.stdin.read()):
                reasons(value, found)
        except ValueError:
            return 2
        sys.stdout.write("\n\n".join(found))
        return 0
    if len(argv) != 1:
        return 2
    try:
        steps = parse(argv[0])
        data = json.load(sys.stdin)
    except ValueError:
        return 2
    for i, (kind, arg) in enumerate(steps):
        if kind == "empty":
            return 0
        value = arg if kind == "string" else walk(data, arg)
        # The last alternative is printed whatever it holds, as jq does.
        if (value is not None and value is not False) or i == len(steps) - 1:
            print(show(value))
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
