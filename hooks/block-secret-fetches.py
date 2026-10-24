#!/usr/bin/env python3
"""PreToolUse hook on Bash: refuse a command that fetches a secret value from a secret store; fails open on a parse error."""
import sys
import json
import re

# The commands that return a secret value, each paired with a tool name for the refusal message.
FETCH_PATTERNS = [
    # AWS: a secret read, and a parameter read only when it asks for decryption.
    (re.compile(r"\bsecretsmanager\s+get-secret-value\b"), "AWS Secrets Manager"),
    (re.compile(r"\bssm\s+get-parameters?\b(?=.*--with-decryption)", re.DOTALL), "AWS SSM"),
    (re.compile(r"\bssm\s+get-parameters-by-path\b(?=.*--with-decryption)", re.DOTALL), "AWS SSM"),
    # 1Password: reading a secret reference prints the value.
    (re.compile(r"\bop\s+read\b"), "1Password"),
    (re.compile(r"\bop\s+item\s+get\b(?=.*--(?:reveal|fields))", re.DOTALL), "1Password"),
    # GitHub and GitLab secret and variable reads.
    (re.compile(r"\bgh\s+secret\s+(?!list\b)\w+"), "GitHub secrets"),
    (re.compile(r"\bglab\s+variable\s+get\b"), "GitLab variables"),
    # Kubernetes: reading a secret as yaml or json.
    (re.compile(r"\bkubectl\s+get\s+secrets?\b(?=.*-o\s*(?:yaml|json|jsonpath))", re.DOTALL), "Kubernetes"),
    # HashiCorp Vault.
    (re.compile(r"\bvault\s+(?:kv\s+get|read)\b"), "Vault"),
    # Google Cloud.
    (re.compile(r"\bgcloud\s+secrets\s+versions\s+access\b"), "Google Secret Manager"),
    # Azure.
    (re.compile(r"\baz\s+keyvault\s+secret\s+show\b"), "Azure Key Vault"),
    # Platform CLIs that dump a whole environment.
    (re.compile(r"\bdoppler\s+secrets\b(?!\s+(?:set|delete))"), "Doppler"),
    (re.compile(r"\binfisical\s+secrets\b(?!\s+set)"), "Infisical"),
    (re.compile(r"\bheroku\s+config(?::get)?\b(?!.*--set)", re.DOTALL), "Heroku config"),
    (re.compile(r"\bflyctl?\s+secrets\s+list\b(?=.*--reveal)", re.DOTALL), "Fly secrets"),
    (re.compile(r"\brailway\s+variables\b(?!\s+set)"), "Railway variables"),
    (re.compile(r"\bvercel\s+env\s+pull\b"), "Vercel env"),
]

# Calls that answer whether a secret exists without returning it; checked first and never refused.
PRESENCE_ONLY = [
    re.compile(r"\bsecretsmanager\s+(?:describe-secret|list-secrets|list-secret-version-ids)\b"),
    re.compile(r"\bssm\s+(?:describe-parameters|get-parameter-history)\b"),
    re.compile(r"\bgh\s+secret\s+list\b"),
    re.compile(r"\bglab\s+variable\s+list\b"),
    re.compile(r"\bvault\s+kv\s+(?:list|metadata)\b"),
    re.compile(r"\bgcloud\s+secrets\s+(?:list|describe|versions\s+list)\b"),
    re.compile(r"\baz\s+keyvault\s+secret\s+(?:list|show-deleted)\b"),
    re.compile(r"\bop\s+item\s+list\b"),
]

REFUSAL = """\
{tool} returns the secret VALUE, and a tool result is written to this session's
transcript on disk. That is how a live Stripe key, the production database
password and eight other credentials reached 61 transcript files between
2026-08-17 and 2026-09-07 before anyone noticed.

If you need to know whether a key is PRESENT, or how long it is, or whether it
equals a known sentinel, use a call that does not return the value:

    aws secretsmanager describe-secret --secret-id <id>
    aws secretsmanager list-secrets
    gh secret list

To compare a value without printing it, pipe it straight into a test and print
only the verdict, never the value or any part of it:

    aws secretsmanager get-secret-value --secret-id <id> --query SecretString \\
      --output text | jq -r '.KEY // ""' | wc -c

To call an API with a 1Password token as a request header, without the token
reaching the transcript, use the one sanctioned wrapper:

    scripts/kyroco/op-header-curl.sh op://<vault>/<item>/<field> <Header-Name> <curl args...>

And do not write the guard the incident that produced this hook wrote. It was
`if echo "$V" | grep -q "ERROR"`, meant to print AWS's error on a denial; the
SUCCESSFUL payload matched, because it contains ERROR inside the key name
STRIPE_METER_ERROR_WEBHOOK_SECRET, so the failure branch fired on success and
echoed all 21 values. Test a guard against a successful response before you
trust it.

If you genuinely need the value in front of a human, that is the user's call: ask
them rather than routing around this."""


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0

    # Let a presence-only call through unless the command also holds a fetch.
    for allowed in PRESENCE_ONLY:
        if allowed.search(command) and not any(p.search(command) for p, _ in FETCH_PATTERNS):
            return 0

    for pattern, tool in FETCH_PATTERNS:
        if pattern.search(command):
            deny(REFUSAL.format(tool=tool))

    return 0


if __name__ == "__main__":
    sys.exit(main())
