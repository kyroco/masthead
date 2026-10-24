#!/usr/bin/env python3
"""Feed each case in block-secret-fetches-cases.txt to the gate and check the verdict.

Cases live in a data file rather than in this script so a new command can be
added without touching code, and so the ALLOW half is as visible as the BLOCK
half. The ALLOW half is the one that matters: a gate that refuses the
sanctioned presence check teaches people to route around it, which is worse
than no gate.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
GATE = HERE.parent / "block-secret-fetches.py"
CASES = HERE / "block-secret-fetches-cases.txt"


def verdict(command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    out = subprocess.run(
        [sys.executable, str(GATE)],
        input=payload,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not out:
        return "ALLOW"
    return "BLOCK" if json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny" else "ALLOW"


def main():
    failures = []
    total = 0
    for line in CASES.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        expected, command = line.split("\t", 1)
        total += 1
        got = verdict(command)
        if got != expected:
            failures.append((expected, got, command))

    # The refusal must not send the model to a script inside the repository, which any clone could plant.
    sample = "op read op://vault/item/field"
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": sample}})
    reason = subprocess.run([sys.executable, str(GATE)], input=payload, capture_output=True, text=True).stdout
    total += 1
    if "scripts/" in reason or "op-header-curl" in reason:
        failures.append(("no repository script in the refusal", "named one", sample))

    for expected, got, command in failures:
        print("FAIL expected %s got %s: %s" % (expected, got, command))
    print("%d cases, %d failures" % (total, len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
