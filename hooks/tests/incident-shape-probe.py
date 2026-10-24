#!/usr/bin/env python3
"""Prove the backstop fires on the exact 2026-09-07 incident shape, and does not echo the value.

The second assertion is the one worth having. A hook that scans for credentials
is the code most likely to write one into the transcript a second time, so it
must name WHAT it found and never the match itself.

Values here are synthetic and follow only the shape. This file is committed.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
HOOK = HERE.parent / "scan-tool-output-for-secrets.py"

FAKE_KEY = "sk_live_AAAABBBBCCCCDDDD"

# The incident: a guard meant to print AWS's error on denial fired on SUCCESS,
# because the payload contains ERROR inside the key name
# STRIPE_METER_ERROR_WEBHOOK_SECRET, and echoed the whole secret.
INCIDENT = (
    'DENIED: {"SECRET_KEY_BASE":"aaa",'
    '"STRIPE_SECRET_KEY":"' + FAKE_KEY + '",'
    '"STRIPE_METER_ERROR_WEBHOOK_SECRET":"whsec_BBBBCCCCDDDDEEEEFFFF0000",'
    '"ENGRAM_CONTROL_POSTGRES_URL":"postgres://app:pw@db.internal:5432/engram"}'
)


def main():
    payload = json.dumps({"tool_name": "Bash", "tool_response": INCIDENT})
    out = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
    ).stdout.strip()

    failures = []
    if not out:
        failures.append("the backstop did not fire on the incident payload")
    else:
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        print("fired:", context.splitlines()[0])
        if FAKE_KEY in context:
            failures.append("the warning echoed the credential it found")
        if "already written" not in context:
            failures.append("the warning does not say the value is already on disk")

    for f in failures:
        print("FAIL " + f)
    print("%d failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
