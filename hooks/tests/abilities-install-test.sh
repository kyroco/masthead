#!/usr/bin/env bash
# Test for "abilities.py install-yaml" and for how a missing PyYAML is reported.
# A stand-in pip and yaml go first on PYTHONPATH, so no case installs anything:
# the stand-in pip logs what it was asked and "installs" by making yaml importable.
#
# Usage: bash hooks/tests/abilities-install-test.sh
# Exit 0 = every assertion passed.

set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="$HERE/abilities.py"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/abilities-install-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
ok() {
  if [ "$1" = "$2" ]; then pass=$((pass + 1)); echo "  ok: $3"
  else fail=$((fail + 1)); echo "  FAIL: $3 (expected '$2', got '$1')" >&2; fi
}
has() {
  if printf '%s' "$1" | grep -qF -- "$2"; then pass=$((pass + 1)); echo "  ok: $3"
  else fail=$((fail + 1)); echo "  FAIL: $3 (no '$2' in: $(printf '%s' "$1" | head -5 | tr '\n' ' '))" >&2; fi
}
lacks() {
  if printf '%s' "$1" | grep -qF -- "$2"; then fail=$((fail + 1)); echo "  FAIL: $3 (found '$2')" >&2
  else pass=$((pass + 1)); echo "  ok: $3"; fi
}

# FAKE_PIP: ok installs; pep668 refuses the way Homebrew's Python does unless told
# --break-system-packages; refuse always refuses that way; fail fails for another reason.
mkdir -p "$TMP/pip"
cat > "$TMP/pip/__main__.py" <<'PY'
import os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_PIP_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
mode = os.environ.get("FAKE_PIP", "ok")
if mode in ("pep668", "refuse") and (mode == "refuse" or "--break-system-packages" not in args):
    print("error: externally-managed-environment")
    sys.exit(1)
if mode == "fail":
    print("ERROR: Could not find a version that satisfies the requirement pyyaml")
    sys.exit(1)
open(os.environ["FAKE_YAML"], "w").write("")
PY
: > "$TMP/pip/__init__.py"

# Each case starts with no PyYAML: a yaml module that refuses to import.
fresh() {
  mkdir -p "$TMP/site"
  printf 'raise ImportError("no yaml here")\n' > "$TMP/site/yaml.py"
  : > "$TMP/pip.log"
}
install() {
  OUT="$(FAKE_PIP="$1" FAKE_PIP_LOG="$TMP/pip.log" FAKE_YAML="$TMP/site/yaml.py" \
    PYTHONPATH="$TMP/site:$TMP" python3 "$TOOL" install-yaml 2>&1)"
  STATUS=$?
  CALLS="$(cat "$TMP/pip.log")"
}
imports() {
  PYTHONPATH="$TMP/site:$TMP" python3 -c 'import yaml' 2>/dev/null && echo yes || echo no
}

echo "install-yaml"
fresh
: > "$TMP/site/yaml.py"
install ok
ok "$STATUS" 0 "with PyYAML already there, it succeeds"
has "$OUT" "PyYAML is already installed" "and says so"
ok "$CALLS" "" "without running pip"

fresh
install ok
ok "$STATUS" 0 "where pip works, it installs"
ok "$CALLS" "install --user pyyaml" "with one plain --user install"
ok "$(imports)" yes "and yaml imports afterwards"
has "$OUT" "-m pip install --user pyyaml" "and names the command it ran"

fresh
install pep668
ok "$STATUS" 0 "on a Python that refuses a plain pip install (Homebrew), it still installs"
ok "$(printf '%s\n' "$CALLS" | sed -n 2p)" "install --user --break-system-packages pyyaml" "by retrying into the user's own folder"
ok "$(imports)" yes "and yaml imports afterwards"
has "$OUT" "--break-system-packages pyyaml" "and names the command that worked"

fresh
install refuse
ok "$STATUS" 2 "when every install is refused, it fails"
has "$OUT" "PyYAML could not be installed" "and says so"
has "$OUT" "Run '" "and prints a command"
has "$OUT" "-m pip install --user --break-system-packages pyyaml'" "the one that gets past the refusal"
ok "$(imports)" no "and nothing was installed"

fresh
install fail
ok "$STATUS" 2 "when pip fails for another reason, it fails"
has "$OUT" "-m pip install --user pyyaml'" "and prints the plain command"
lacks "$OUT" "break-system-packages" "without the Homebrew flag, which an older pip does not know"

echo "a missing PyYAML, as the push gate and checker see it"
fresh
OUT="$(PYTHONPATH="$TMP/site" python3 "$TOOL" check "$TMP/none.yaml" 2>&1)"
ok "$?" 2 "the checker stops"
has "$OUT" "PyYAML is not installed" "says why"
has "$OUT" "abilities.py install-yaml" "and names the one command that installs it"
lacks "$OUT" "'python3 -m pip install pyyaml'" "not the plain pip install Homebrew refuses"

echo "the abilities suite without PyYAML"
fresh
OUT="$(PYTHONPATH="$TMP/site" bash "$HERE/tests/abilities-test.sh" 2>&1)"
ok "$?" 77 "the suite exits 77, which means skipped"
has "$OUT" "skipped: PyYAML is not installed" "and says why"
lacks "$OUT" "FAIL" "with no failed case"
OUT="$(RUN_ONLY="abilities file" PYTHONPATH="$TMP/site" bash "$HERE/run-tests.sh" 2>&1)"
ok "$?" 0 "the full runner does not fail on it"
has "$OUT" "skip  abilities file" "it reports the suite as skipped"
has "$OUT" "PyYAML is not installed" "with the reason on the same line"
has "$OUT" "1 skipped" "and counts it in the last line"
lacks "$OUT" "FAIL" "not as a failure"
ok "$(printf '%s\n' "$OUT" | grep -c '^\(ok\|skip\|FAIL\) ')" 1 "RUN_ONLY ran that one suite"

echo "setup turns the check on with PyYAML in place"
has "$(cat "$HERE/../skills/setup/SKILL.md")" "abilities.py\" install-yaml" "the setup skill runs install-yaml when it turns the check on"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
