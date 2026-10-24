#!/usr/bin/env python3
"""PostToolUse backstop: warn, after the fact, when a tool result carries something shaped like a credential; it never blocks and fails open on any error."""
import sys
import json
import re

# List each credential shape with a name to print; the matched text is never printed.
CREDENTIAL_SHAPES = [
    (re.compile(r"\bsk_live_[A-Za-z0-9]{8,}"), "a live Stripe secret key"),
    (re.compile(r"\brk_live_[A-Za-z0-9]{8,}"), "a live Stripe restricted key"),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{16,}"), "a Stripe webhook signing secret"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "a GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "a GitHub fine-grained token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key id"),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), "an AWS temporary access key id"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bops_[A-Za-z0-9]{20,}"), "a 1Password service account token"),
    (re.compile(r"\bhvs\.[A-Za-z0-9_-]{20,}"), "a Vault token"),
    # Match a connection string that carries a password.
    (re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb|redis|rediss|amqp)://[^\s:/@]+:[^\s@]+@"),
     "a connection string containing a password"),
]

# List public values that look like credentials and are removed before the shapes are checked.
KNOWN_PUBLIC = [
    re.compile(r"dev-only-recovery-code-pepper-not-a-secret"),
    re.compile(r"test-only-recovery-code-pepper-not-a-secret"),
    re.compile(r"sentinel-no-recovery-codes|no-recovery-codes-are-digested-here"),
    re.compile(r"SET-OUT-OF-BAND-see-secrets-conventions"),
    re.compile(r"\bsk_test_[A-Za-z0-9]+"),
]

WARNING = """\
CREDENTIAL SHAPE IN TOOL OUTPUT: {what}.

This ran AFTER the tool, so the value is already written to this session's
transcript on disk. Nothing can unwrite it. Treat that credential as
compromised and rotate it.

What to do now, in this order:
  1. Tell the user, in plain words, which credential and which command produced it.
  2. Do not re-run the command, and do not echo, grep or reformat the output:
     each of those writes it again.
  3. The transcript files live under the account's projects/ directory. The user
     decides whether they are deleted.

This is a smoke alarm, not a lock. It detects; it does not prevent. If you were
fetching a secret to answer whether a key is PRESENT, use a call that does not
return the value (describe-secret, list-secrets, gh secret list), or pipe the
value straight into a test and print only the verdict."""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    try:
        response = payload.get("tool_response")
        text = response if isinstance(response, str) else json.dumps(response)
        if not text:
            return 0

        for allowed in KNOWN_PUBLIC:
            text = allowed.sub("", text)

        for pattern, what in CREDENTIAL_SHAPES:
            if pattern.search(text):
                print(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": WARNING.format(what=what),
                    }
                }))
                return 0
    except Exception:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
