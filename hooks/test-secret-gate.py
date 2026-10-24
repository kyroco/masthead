#!/usr/bin/env python3
"""Prove block-secret-reads.py refuses what it must and allows what it must.

    python3 .claude/hooks/test-secret-gate.py

THE CASES LIVE IN THIS FILE RATHER THAN ON A COMMAND LINE, and that is not a
style choice. The gate refuses any Bash command that MENTIONS a credential path,
so a one-liner that pipes `{"file_path": "~/.zshenv"}` into the hook is itself
refused - correctly. Testing from a file keeps the paths out of the command
string, so the harness can exercise the gate without tripping it.

This exists because the first attempt to verify the gate was `head ~/.zshenv`,
run against the real file, which leaked the very token the gate was written to
protect. A safety gate is never tested by performing the unsafe act. It is
tested by feeding it the tool call and reading the decision, which is all this
does.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block-secret-reads.py")

HOME = os.path.expanduser("~")

# The reader the gate's refusal names, in the three spellings a person types.
CONFIG = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
READER = "python3 " + CONFIG + "/hooks/read-redacted.py"
READER_TILDE = "python3 " + CONFIG.replace(HOME, "~", 1) + "/hooks/read-redacted.py"
READER_HOME = "python3 " + CONFIG.replace(HOME, "$HOME", 1) + "/hooks/read-redacted.py"

# A repo can ship a `.env` that is a symlink to a file the reader does not mask.
import tempfile
LINK_DIR = tempfile.mkdtemp()
open(os.path.join(LINK_DIR, ".netrc"), "w").close()
os.symlink(os.path.join(LINK_DIR, ".netrc"), os.path.join(LINK_DIR, ".env"))

# (label, tool, tool_input, expected decision)
CASES = [
    ("shell profile, whole file", "Read", {"file_path": HOME + "/.zshenv"}, "deny"),
    ("shell profile, rc variant", "Read", {"file_path": HOME + "/.bashrc"}, "deny"),
    ("shell profile via sed", "Bash", {"command": "sed -n 5,25p " + HOME + "/.zshenv"}, "deny"),
    ("shell profile via head", "Bash", {"command": "head -20 ~/.zshenv"}, "deny"),
    ("dotenv", "Read", {"file_path": "products/.env.local"}, "deny"),
    ("dotenv via cat", "Bash", {"command": "cat .env"}, "deny"),
    ("aws credentials", "Read", {"file_path": HOME + "/.aws/credentials"}, "deny"),
    ("ssh private key", "Read", {"file_path": HOME + "/.ssh/id_ed25519"}, "deny"),
    ("pem file", "Read", {"file_path": "infra/certs/server.pem"}, "deny"),
    ("grep into a profile", "Grep", {"pattern": "token", "path": HOME + "/.zshenv"}, "deny"),
    # The allow side matters just as much: a gate that blocks ordinary work gets
    # switched off, and a gate that is off protects nothing.
    ("dotenv example", "Read", {"file_path": "products/.env.example"}, "allow"),
    ("dotenv template", "Read", {"file_path": ".env.template"}, "allow"),
    ("ssh known_hosts", "Read", {"file_path": HOME + "/.ssh/known_hosts"}, "allow"),
    ("ordinary source file", "Read", {"file_path": "products/apps/salon_web/lib/foo.ex"}, "allow"),
    ("ordinary command", "Bash", {"command": "mix test --only browser"}, "allow"),
    ("a path that is not a string is refused, not crashed on", "Read", {"file_path": ["x"]}, "deny"),
    ("git command", "Bash", {"command": "git status --short"}, "allow"),
    ("the redacting reader itself", "Bash",
     {"command": "python3 " + HOME + "/.claude/hooks/read-redacted.py"}, "allow"),
    # The reader on the files it exists for is REFUSED since 2026-09-30: two
    # security checks measured it leaking keys it could not recognise, so the
    # exception is off (MASKED_READ_ALLOWED in the gate) and the refusal says to
    # ask the user. These rows flip to allow if the exception is ever turned on.
    ("the reader on a profile", "Bash", {"command": READER + " " + HOME + "/.zshrc"}, "deny"),
    ("the reader with a line range", "Bash", {"command": READER + " ~/.zshenv 5 25"}, "deny"),
    ("the reader spelled with ~", "Bash", {"command": READER_TILDE + " ~/.zshrc"}, "deny"),
    ("the reader spelled with $HOME", "Bash", {"command": READER_HOME + " ~/.zshrc"}, "deny"),
    # ...and nothing may ride along with it.
    ("the reader, then cat", "Bash", {"command": READER + " ~/.zshrc; cat ~/.zshrc"}, "deny"),
    ("the reader, and cat", "Bash", {"command": READER + " ~/.zshrc && cat ~/.zshrc"}, "deny"),
    ("the reader, newline, cat", "Bash", {"command": READER + " ~/.zshrc\ncat ~/.zshrc"}, "deny"),
    ("the reader piped on", "Bash", {"command": READER + " ~/.zshrc | cat"}, "deny"),
    ("cat substituted into the reader", "Bash",
     {"command": READER + " $(cat ~/.zshrc)"}, "deny"),
    ("cat in backticks", "Bash", {"command": READER + " `cat ~/.zshrc`"}, "deny"),
    ("a third number", "Bash", {"command": READER + " ~/.zshrc 5 25 99"}, "deny"),
    ("a reader somewhere else", "Bash",
     {"command": "python3 /tmp/read-redacted.py ~/.zshrc"}, "deny"),
    ("a reader in this folder", "Bash",
     {"command": "python3 ./read-redacted.py ~/.zshrc"}, "deny"),
    ("the reader named by a bare relative path", "Bash",
     {"command": "python3 read-redacted.py ~/.zshrc"}, "deny"),
    ("the reader on a dotenv file", "Bash", {"command": READER + " products/.env.local"}, "deny"),
    # The reader masks NAME=value lines only. These formats it would print
    # whole, so they stay refused.
    ("the reader on a netrc", "Bash", {"command": READER + " ~/.netrc"}, "deny"),
    ("the reader on a pgpass", "Bash", {"command": READER + " ~/.pgpass"}, "deny"),
    ("the reader on an npmrc", "Bash", {"command": READER + " ~/.npmrc"}, "deny"),
    ("the reader on an ssh key", "Bash", {"command": READER + " ~/.ssh/id_ed25519"}, "deny"),
    ("the reader on a .env that links to a netrc", "Bash",
     {"command": READER + " " + LINK_DIR + "/.env"}, "deny"),
    # Prose is not a path. These blocked a commit whose MESSAGE discussed the
    # gate, which is how the bare-word matching was found.
    ("the word credential in prose", "Bash",
     {"command": "git commit -m 'refuse to read credential files'"}, "allow"),
    ("the word secrets in prose", "Bash",
     {"command": "echo 'it masks secrets by name and by shape'"}, "allow"),
    ("this gate's own test file", "Read",
     {"file_path": ".claude/hooks/test-secret-gate.py"}, "allow"),
    ("this gate itself", "Read",
     {"file_path": ".claude/hooks/block-secret-reads.py"}, "allow"),
    # A jq field accessor is not a key file. The extension pattern matched a
    # bare ".key", so `jq 'to_entries[] | .key'` was refused outright, which is
    # ordinary config reading and not credential handling. Found by the gate
    # blocking a /doctor run.
    ("jq field accessor", "Bash",
     {"command": "jq -r 'to_entries[] | .key' config.json"}, "allow"),
    ("a bare extension token", "Read", {"file_path": ".key"}, "allow"),
    ("jq array syntax around the accessor", "Bash",
     {"command": "jq -r 'to_entries[] | [.key, .value] | @tsv' config.json"}, "allow"),
    # ...while a real key file still is one, and the named dotfiles still are.
    ("a real key file", "Read", {"file_path": "certs/server.key"}, "deny"),
    ("a bare dotenv still blocks", "Read", {"file_path": ".env"}, "deny"),
    # ...but a real path is still a path, prose around it or not.
    ("a real path inside a sentence", "Bash",
     {"command": "echo 'the value came from ~/.zshenv today'"}, "deny"),
    ("secrets.yaml is a store, not a word", "Read",
     {"file_path": "deploy/secrets.yaml"}, "deny"),
]


def decision_for(tool, tool_input):
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    result = subprocess.run(
        [sys.executable, HOOK],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )

    out = result.stdout.strip()
    if not out:
        return "allow"

    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "unparseable: " + out[:80]


def main():
    failures = 0

    for label, tool, tool_input, expected in CASES:
        actual = decision_for(tool, tool_input)
        ok = actual == expected
        failures += 0 if ok else 1
        print("{:4}  {:<32} expected {:<5} got {}".format(
            "ok" if ok else "FAIL", label, expected, actual))

    # The refusal must not send the user to the masked reader: it cannot mask every shape.
    raw = subprocess.run([sys.executable, HOOK],
                         input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": HOME + "/.aws/credentials"}}),
                         capture_output=True, text=True, check=False).stdout
    sends_to_reader = "read-redacted" in raw
    failures += 1 if sends_to_reader else 0
    print("{:4}  {:<32}".format("FAIL" if sends_to_reader else "ok", "the refusal sends nobody to the reader"))

    print("")
    if failures:
        print("{} of {} cases wrong".format(failures, len(CASES)))
        return 1

    print("all {} cases correct".format(len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
