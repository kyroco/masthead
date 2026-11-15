#!/usr/bin/env bash
# MAST-41: the adjudicator runs on Opus at high effort. Its placement is final
# and no later step re-checks it, so it gets the strong model. Robert, November
# 14, 2026: "opus 5.5 high". Reads only the agent file's frontmatter, so a word
# in the body cannot pass or fail it.
#
# Run from anywhere: bash hooks/tests/adjudicator-model-test.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FILE="$ROOT/agents/adjudicator.md"
pass=0
fail=0

# The value of one key between the first two --- lines.
front() {
  awk -v k="$1" '
    NR == 1 && $0 == "---" { f = 1; next }
    f && $0 == "---" { exit }
    f && index($0, k ":") == 1 { sub("^" k ":[ \t]*", ""); print; exit }
  ' "$FILE"
}

check() {
  local key="$1" want="$2" got
  got="$(front "$key")"
  if [ "$got" = "$want" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL adjudicator %s is "%s", want "%s"\n' "$key" "$got" "$want"
  fi
}

check model opus
check effort high
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
