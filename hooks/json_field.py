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


def read_in():
    """stdin as UTF-8 whatever the locale: Claude Code sends UTF-8."""
    return sys.stdin.buffer.read().decode("utf-8", "surrogateescape")


def write_out(text):
    """UTF-8 out whatever the locale and Python (3.6 has no reconfigure); a lone surrogate, which JSON
    can carry as \\ud800, is written as that escape rather than stopping the write (MAST-37)."""
    sys.stdout.buffer.write(text.encode("utf-8", "backslashreplace"))
    sys.stdout.buffer.flush()


def main(argv):
    if len(argv) == 2 and argv[0] == "--deny":
        # ASCII JSON, so no locale or stray byte can stop the refusal being printed.
        write_out(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": argv[1]}}) + "\n")
        return 0
    if argv == ["--object"]:
        # Exit 0 when stdin is one JSON object, so a gate can tell an unreadable call from an absent field.
        try:
            return 0 if isinstance(json.loads(read_in()), dict) else 2
        except ValueError:
            return 2
    if argv == ["--reasons"]:
        found = []
        try:
            for value in values(read_in()):
                reasons(value, found)
        except ValueError:
            return 2
        write_out("\n\n".join(found))
        return 0
    if len(argv) != 1:
        return 2
    try:
        steps = parse(argv[0])
        data = json.loads(read_in())
    except ValueError:
        return 2
    for i, (kind, arg) in enumerate(steps):
        if kind == "empty":
            return 0
        value = arg if kind == "string" else walk(data, arg)
        # The last alternative is printed whatever it holds, as jq does.
        if (value is not None and value is not False) or i == len(steps) - 1:
            write_out(show(value) + "\n")
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
