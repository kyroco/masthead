#!/usr/bin/env python3
"""Prove read-redacted.py masks every assigned value a shell profile or .env can
hold, whatever the variable is called.

    python3 ~/.claude/hooks/tests/read-redacted-test.py

The values are made up and built here from pieces, so no token-shaped string
sits in this file. Each case writes a throwaway file, runs the reader on it and
checks the made-up value is absent from what it printed.
"""
import os
import subprocess
import sys
import tempfile

READER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "read-redacted.py")

HEX = "0123456789abcdef" * 2
ALNUM = "Ab3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dF3"
SECRETS = {
    "OPENAI_KEY": HEX,
    "GOOGLE_MAPS_KEY": "AIza" + ALNUM,
    "MAILGUN_KEY": "key-" + HEX,
    "HF": "hf_" + ALNUM,
    "SHORT_ONE": "hunter2x",
}
PEM_BODY = ["MIIEvQIBADANBgkqhkiG9w0BAQEFAASC", "Q9sT5vW7yZ9bC1dF3Ab3dE5gH7jK9mN1", "pQ3sT5=="]

lines = []
for name, value in SECRETS.items():
    lines.append("{}={}\n".format(name, value))
lines.append("export HF_TOO={}\n".format(SECRETS["HF"]))
lines.append('DATABASE="host=db password={} port=5432"\n'.format(SECRETS["SHORT_ONE"]))
lines.append('PRIVATE_BLOB="-----BEGIN SOMETHING-----\n')
lines.extend(line + "\n" for line in PEM_BODY)
lines.append('-----END SOMETHING-----"\n')
lines.append('export PATH="$HOME/bin:$PATH"\n')
lines.append("GOPATH=~/go\n")
lines.append("WORKERS=4\n")

failures = 0


def check(label, ok):
    global failures
    failures += 0 if ok else 1
    print("{:4}  {}".format("ok" if ok else "FAIL", label))


def read(path, *args):
    return subprocess.run([sys.executable, READER, path] + list(args),
                          capture_output=True, text=True, check=False).stdout


with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, ".env")
    with open(path, "w") as handle:
        handle.writelines(lines)
    out = read(path)
    for name, value in SECRETS.items():
        check("{} is masked whatever its name".format(name), value not in out)
    check("a password inside a quoted value is masked", "password=" + SECRETS["SHORT_ONE"] not in out)
    for piece in PEM_BODY:
        check("every line of a multi-line value is masked ({}...)".format(piece[:6]), piece not in out)
    check("a PATH made of references stays readable", '"$HOME/bin:$PATH"' in out)
    check("a home path stays readable", "GOPATH=~/go" in out)
    check("a number stays readable", "WORKERS=4" in out)
    first_pem = lines.index(PEM_BODY[1] + "\n") + 1
    ranged = read(path, str(first_pem), str(first_pem + 1))
    check("a range that starts inside a multi-line value still masks it",
          PEM_BODY[1] not in ranged and PEM_BODY[2] not in ranged and ranged.count("\n") >= 2)
    machine_file = os.path.join(tmp, "machine-sample.txt")
    with open(machine_file, "w") as handle:
        handle.write("machine api.example.com\nlogin alice\npassword Hunter2Fake\n")
    check("a machine-login-password line is masked", "Hunter2Fake" not in read(machine_file))
    pg_file = os.path.join(tmp, "pg-sample.txt")
    with open(pg_file, "w") as handle:
        handle.write("localhost:5432:appdb:appuser:FakePgPw77\n")
    check("a five-field database password line is masked", "FakePgPw77" not in read(pg_file))

print()
print("{} failed".format(failures) if failures else "all cases correct")
sys.exit(1 if failures else 0)
