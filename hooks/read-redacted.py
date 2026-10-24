#!/usr/bin/env python3
"""Print a secret-bearing file with its secrets masked. Usage: read-redacted.py PATH [START [END]], lines 1-indexed and inclusive."""
import sys
import os
import re

# Assignment forms: NAME=value, export NAME=value, NAME: value and "NAME": "value".
SECRET_NAME = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|PASS|PWD|CREDENTIAL|PRIVATE|SESSION|"
    r"APIKEY|API_KEY|ACCESS_KEY|SECRET_KEY|AUTH|BEARER|SALT|SIGNATURE|SIGNING|"
    r"CERT|COOKIE|DSN|CONN_STR|CONNECTION_STRING)",
    re.IGNORECASE,
)

ASSIGNMENT = re.compile(
    r"""^(?P<lead>\s*(?:export\s+|set\s+-x\s+|declare\s+-x\s+)?)
         (?P<name>["']?[A-Za-z_][A-Za-z0-9_.\-]*["']?)
         (?P<sep>\s*[:=]\s*)
         (?P<value>.+)$""",
    re.VERBOSE,
)

# Values that look secret whatever name they are stored under.
SECRET_VALUE_PATTERNS = [
    re.compile(r"\bsk_[A-Za-z0-9_\-]{8,}"),            # Stripe secret
    re.compile(r"\brk_[A-Za-z0-9_\-]{8,}"),            # Stripe restricted
    re.compile(r"\bops_[A-Za-z0-9+/=_\-]{16,}"),       # 1Password service account
    re.compile(r"\bghp_[A-Za-z0-9]{16,}"),             # GitHub PAT
    re.compile(r"\bgho_[A-Za-z0-9]{16,}"),
    re.compile(r"\bghs_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),    # Slack
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),      # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"),        # GitLab
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}"),
    # A URL carrying inline credentials: scheme://user:password@host
    re.compile(r"(?<=://)[^\s:/@]+:[^\s:/@]+(?=@)"),
]

# A long unbroken run of credential-shaped characters.
HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9+/_\-]{40,}={0,2}\b")

# 12-digit AWS account ids, wherever they appear.
AWS_ACCOUNT = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")

MASK = "<redacted>"


def looks_like_prose(value):
    """True for values that are plainly English, so they survive unmasked."""
    stripped = value.strip().strip("\"'")
    if " " in stripped and not HIGH_ENTROPY.search(stripped):
        return True
    return False


def mask_values(line):
    """Mask anything secret-shaped anywhere in the line."""
    out = line
    for pattern in SECRET_VALUE_PATTERNS:
        out = pattern.sub(MASK, out)
    out = HIGH_ENTROPY.sub(MASK, out)
    out = AWS_ACCOUNT.sub("<acct>", out)
    return out


# Values that cannot hold a credential by shape: a variable, command substitution, path, number or yes/no word; every other assigned value is masked.
SAFE_VALUE = re.compile(
    r"""^(["']?)(?:[$~/.][^\s"'`]*|[0-9]+|true|false|yes|no|on|off|)\1\s*(?:\#.*)?$""",
    re.IGNORECASE,
)


def opens_quote(value):
    """The quote a value opens and does not close on its own line, or None."""
    stripped = value.strip()
    if not stripped or stripped[0] not in "\"'":
        return None
    quote = stripped[0]
    body = stripped[1:].replace("\\" + quote, "")
    return quote if quote not in body else None


def redact(line):
    # Mask only secret-shaped text in a comment.
    if line.lstrip().startswith("#"):
        return mask_values(line)

    match = ASSIGNMENT.match(line.rstrip("\n"))
    if match and (SECRET_NAME.search(match.group("name"))
                  or not SAFE_VALUE.match(match.group("value").strip())):
        value = match.group("value")
        # Keep a trailing comment on a masked assignment.
        comment = ""
        hash_at = value.find(" #")
        if hash_at != -1:
            comment = value[hash_at:]
        return "{lead}{name}{sep}{mask}{comment}\n".format(
            lead=match.group("lead"),
            name=match.group("name"),
            sep=match.group("sep"),
            mask=MASK,
            comment=comment,
        )

    if match and looks_like_prose(match.group("value")):
        return mask_values(line)

    return mask_values(line)


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    path = os.path.expanduser(sys.argv[1])
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end = int(sys.argv[3]) if len(sys.argv) > 3 else None

    try:
        with open(path, "r", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as error:
        print("read-redacted: {}".format(error), file=sys.stderr)
        return 1

    last = end if end is not None else len(lines)
    width = len(str(min(last, len(lines))))

    # Mask a quoted value that runs over several lines until its quote closes, tracking the state from line 1.
    print("--- {} (values redacted) ---".format(path))
    open_quote = None
    for number in range(1, min(last, len(lines)) + 1):
        line = lines[number - 1]
        if open_quote:
            if open_quote in line.replace("\\" + open_quote, ""):
                open_quote = None
            text = MASK + "\n"
        else:
            match = ASSIGNMENT.match(line.rstrip("\n"))
            if match and not line.lstrip().startswith("#"):
                open_quote = opens_quote(match.group("value"))
            text = redact(line)
        if number >= start:
            sys.stdout.write("{:>{w}}\t{}".format(number, text, w=width))
    return 0


if __name__ == "__main__":
    sys.exit(main())
