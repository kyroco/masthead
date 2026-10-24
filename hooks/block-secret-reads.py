#!/usr/bin/env python3
"""PreToolUse hook on Read, Grep and Bash: refuse to read a credential file, matching Bash on any mention; fails open on a parse error."""
import sys
import json
import os
import re

# Files that exist to hold credentials, matched on basename.
SECRET_BASENAMES = {
    ".env",
    ".envrc",
    ".netrc",
    ".pgpass",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    ".dockercfg",
    ".git-credentials",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

# Shell profiles, which often hold exported tokens.
SHELL_PROFILES = {
    ".zshenv",
    ".zshrc",
    ".zprofile",
    ".zlogin",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".profile",
    ".kshrc",
    ".cshrc",
}

# Basename patterns such as .env.local, secrets.yaml and foo.pem.
SECRET_PATTERNS = [
    re.compile(r"^\.env($|\.)", re.IGNORECASE),
    # Key-file extensions need a non-empty stem; .env and friends are named in SECRET_BASENAMES.
    re.compile(r".+\.(pem|key|p12|pfx|jks|keystore|asc|gpg)$", re.IGNORECASE),
    re.compile(r"(^|[._\-])secrets?([._\-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._\-])credentials?([._\-]|$)", re.IGNORECASE),
]

# Names that mark a shape rather than a value; always allowed.
TEMPLATE_MARKERS = re.compile(
    r"\.(example|sample|template|dist|schema)($|\.)|(^|[._\-])example($|[._\-])",
    re.IGNORECASE,
)

# Source code extensions, exempt from the word-based name patterns.
SOURCE_EXTENSIONS = {
    ".py", ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".ex", ".exs", ".eex", ".heex", ".erl",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".rb", ".go", ".rs", ".java", ".kt", ".swift",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs",
    ".md", ".rst", ".txt", ".sql", ".tf", ".hcl",
    ".html", ".css", ".scss",
}

# The masked reader beside this file: the plugin root as a plugin, else the folder above hooks/.
_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READER = "python3 {}/hooks/read-redacted.py".format(_ROOT)

# Match one plain call to the real reader in the config folder; no shell metacharacters may ride along.
_MASKED_READ = re.compile(
    r"python3[ \t]+(\$HOME/[\w./~-]+|~/[\w./~-]+|/[\w./~-]+)"
    r"[ \t]+([\w./~+@%:,-]+)"
    r"(?:[ \t]+\d+){0,2}"
)


def _masked_kind(path):
    base = os.path.basename(path.rstrip("/"))
    return base in SHELL_PROFILES or base == ".envrc" or bool(re.match(r"^\.env($|\.)", base))


# Switch for the masked-read exception; off, so no profile or .env is read through the reader.
MASKED_READ_ALLOWED = False


def reader_masks(target, cwd=None):
    """True when the reader would mask the written name and the file it resolves to."""
    if not _masked_kind(target):
        return False
    path = os.path.expanduser(target)
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    return _masked_kind(os.path.realpath(path))


def is_masked_read(command, cwd=None):
    match = _MASKED_READ.fullmatch(command.strip(" \t"))
    if not match or not reader_masks(match.group(2), cwd):
        return False
    reader = match.group(1)
    if reader.startswith("$HOME/"):
        reader = os.path.join(os.path.expanduser("~"), reader[len("$HOME/"):])
    reader = os.path.expanduser(reader)
    real = os.path.join(_CONFIG_DIR, "hooks", "read-redacted.py")
    return os.path.realpath(reader) == os.path.realpath(real)


def is_secret_path(path):
    if not path:
        return False

    base = os.path.basename(path.rstrip("/"))
    if not base:
        return False

    if TEMPLATE_MARKERS.search(base):
        return False

    if base in SECRET_BASENAMES or base in SHELL_PROFILES:
        return True

    _, extension = os.path.splitext(base)
    is_source = extension.lower() in SOURCE_EXTENSIONS

    for pattern in SECRET_PATTERNS:
        if not pattern.search(base):
            continue
        # Exact names like .env, .pem and .key match even on a source-shaped name; word-based patterns skip source files.
        word_based = pattern.pattern.startswith("(^|[._\\-])")
        if word_based and is_source:
            continue
        return True

    # ~/.aws/credentials, ~/.ssh/* and ~/.gnupg/* hold keys whatever the leaf is called.
    normalised = path.replace("\\", "/")
    if re.search(r"(^|/)\.ssh/(?!known_hosts|config$)", normalised):
        return True
    if re.search(r"(^|/)\.aws/credentials", normalised):
        return True
    if re.search(r"(^|/)\.gnupg/", normalised):
        return True

    return False


def looks_like_a_path(token):
    """True only for a fragment shaped like a filename, not an English word."""
    if "/" in token or token.startswith("."):
        return True
    return bool(re.search(r"\.[A-Za-z0-9]{1,10}$", token))


def secret_mentioned_in_command(command, cwd=None):
    """Find a credential path named anywhere in a shell command."""
    if not command or (MASKED_READ_ALLOWED and is_masked_read(command, cwd)):
        return None

    # Split on whitespace and shell metacharacters and test each fragment as a path.
    for token in re.split(r"[\s;|&<>()\[\]{}\"'`,]+", command):
        token = token.strip().rstrip(".:;")
        if not token or token.startswith("-"):
            continue
        # Strip a leading redirect or assignment that swallowed the path.
        token = token.split("=")[-1]
        if not looks_like_a_path(token):
            continue
        if is_secret_path(token):
            return token

    return None


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
        data = json.load(sys.stdin)
    except Exception:
        return 0

    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}

    target = None

    if tool in ("Read", "NotebookRead"):
        target = ti.get("file_path") if is_secret_path(ti.get("file_path")) else None
    elif tool == "Grep":
        for key in ("path", "glob"):
            if is_secret_path(ti.get(key)):
                target = ti.get(key)
                break
    elif tool == "Bash":
        target = secret_mentioned_in_command(ti.get("command"), data.get("cwd"))

    if not target:
        return 0

    deny(
        "Blocked: '{target}' is a credential-bearing file, and reading it whole "
        "puts its values into the transcript permanently. This is a hard account "
        "rule and there is no exception for 'I only need one line' - that is the "
        "exact call that leaked a live 1Password token on 2026-07-31.\n\n"
        "No command reads it, the masked reader included: it cannot mask every "
        "way a shell file holds a secret. Ask the user for the lines or the value "
        "you need, and say why. They can run `! {reader} {target}` themselves if they "
        "choose to show you the file.".format(target=target, reader=READER)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
