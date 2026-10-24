#!/usr/bin/env python3
"""Check scan-tool-output-for-secrets.py fires on credential shapes and stays quiet otherwise.

The QUIET half is the one that decides whether this hook survives. A backstop
that cries wolf on every hash and UUID gets ignored, and an ignored alarm is
worse than none because it looks like coverage.

Fixture values here are synthetic and follow only the SHAPE of a credential.
None is real, and none may be replaced with a real one: this file is committed.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
HOOK = HERE.parent / "scan-tool-output-for-secrets.py"

WARN = [
    ("live Stripe key", "STRIPE_SECRET_KEY=sk_live_AAAABBBBCCCCDDDDEEEE"),
    ("Stripe restricted key", "key rk_live_AAAABBBBCCCCDDDD in config"),
    ("Stripe webhook secret", "whsec_AAAABBBBCCCCDDDDEEEEFFFF0000"),
    ("GitHub token", "token ghp_AAAABBBBCCCCDDDDEEEEFFFF0000111122"),
    ("GitHub fine-grained", "github_pat_AAAABBBBCCCCDDDDEEEEFFFF0000"),
    ("Slack token", "xoxb-1111-2222-AAAABBBBCCCCDDDD"),
    ("AWS key id", "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"),
    ("private key header", "-----BEGIN RSA PRIVATE KEY-----"),
    ("openssh private key", "-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("1Password token", "OP_SERVICE_ACCOUNT_TOKEN=ops_AAAABBBBCCCCDDDDEEEEFFFF"),
    ("Vault token", "hvs.AAAABBBBCCCCDDDDEEEEFFFF0000"),
    ("postgres url with password", "postgres://app:hunter2@db.internal:5432/engram"),
    ("redis url with password", "rediss://default:s3cr3t@cache.internal:6379"),
    # The incident's own shape: a whole secret payload echoed as JSON.
    ("whole secret payload", '{"SECRET_KEY_BASE":"x","STRIPE_SECRET_KEY":"sk_live_AAAABBBBCCCCDDDD"}'),
]

QUIET = [
    ("plain output", "37 tests, 0 failures"),
    ("a git sha", "commit af79c9ad6b5e696da416974a8b2693b7e1179ec6"),
    ("a uuid", "container d69174e1-4a4b-48a0-8d17-fa7faebe3b7a"),
    ("a sha256 hex", "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),
    ("base64 blob", "Zm9vYmFyYmF6cXV1eGNvcmdlZ3JhdWx0Z2FycGx5"),
    ("stripe TEST key", "STRIPE_SECRET_KEY=sk_test_AAAABBBBCCCCDDDDEEEE"),
    ("public dev pepper", 'code_pepper: "dev-only-recovery-code-pepper-not-a-secret-0123456789"'),
    ("test pepper", 'code_pepper: "test-only-recovery-code-pepper-not-a-secret-0123456789"'),
    ("migrate sentinel", "RECOVERY_CODE_PEPPER=migrate-only-sentinel-no-recovery-codes-are-digested-here-0000"),
    ("out of band sentinel", "value is SET-OUT-OF-BAND-see-secrets-conventions"),
    ("postgres url no password", "postgres://localhost:5432/engram_dev"),
    ("redis url no password", "redis://cache.internal:6379"),
    ("the word secret", "aws secretsmanager describe-secret --secret-id engram/prod/app"),
    ("a describe-secret result", '{"Name":"engram/prod/app","LastChangedDate":"2026-07-31"}'),
]


def fired(text):
    payload = json.dumps({"tool_name": "Bash", "tool_response": text})
    out = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return bool(out)


def main():
    failures = []
    for label, text in WARN:
        if not fired(text):
            failures.append("expected a warning and got none: %s" % label)
    for label, text in QUIET:
        if fired(text):
            failures.append("expected silence and got a warning: %s" % label)

    for f in failures:
        print("FAIL " + f)
    print("%d cases, %d failures" % (len(WARN) + len(QUIET), len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
