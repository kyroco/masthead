#!/usr/bin/env bash
# Prove gate-redundant-grep both bites and stands aside, since a gate that only
# ever allows is indistinguishable from no gate at all.
#
# TWO THINGS THIS PROBE GOT WRONG FIRST, both worth keeping written down because
# each made a WORKING gate look dead:
#   1. The hook resolves its state as $TMPDIR/claude-engram/<session_id>, so a
#      probe must set TMPDIR and put the matching session_id in the payload. The
#      first version invented an env var the hook does not read.
#   2. These gates refuse by printing a JSON permissionDecision and exiting 0,
#      like every other gate in engram-protocol.sh. Reading $? scores a refusal
#      as an allow.
set -u
HOOK="$(cd "$(dirname "$0")" && pwd)/engram-protocol.sh"
pass=0
fail=0

check() {
  local name="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    printf '  ok    %-46s %s\n' "$name" "$got"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-46s want %s got %s\n' "$name" "$want" "$got"
    fail=$((fail + 1))
  fi
}

# $1 = tsv contents, $2 = grep pattern, $3 = optional env assignment.
# Fresh TMPDIR and session per case, so a once-per-pattern stamp written by one
# case cannot silence the next. Prints the decision: deny or allow.
run() {
  local tmp sid payload
  tmp="$(mktemp -d)"
  sid="probe-$RANDOM"
  mkdir -p "$tmp/claude-engram/$sid"
  printf '%s' "$1" > "$tmp/claude-engram/$sid/codesearches.tsv"
  payload="$(printf '{"tool_name":"Grep","session_id":"%s","tool_input":{"pattern":"%s"}}' "$sid" "$2")"
  local out
  out="$(printf '%s' "$payload" \
    | env TMPDIR="$tmp" ${3:+"$3"} bash "$HOOK" gate-redundant-grep 2>/dev/null)"
  # An allowing gate prints NOTHING and exits 0. Only a refusal emits JSON, so
  # empty output is the allow, not a parse failure.
  [ -n "$out" ] || { echo allow; return; }
  printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null | head -1
}

FRESH_HIT=$'5\tabc\tlib/x.ex:1-2\tSubmitLimits evaluate\tfresh\n'
STALE_HIT=$'5\tabc\tlib/x.ex:1-2\tSubmitLimits evaluate\tstale\n'
EMPTY=$'0\tabc\t-\tSubmitLimits evaluate\tfresh\n'
SHELL_ROW=$'-\t-\t-\tkorium-cli search SubmitLimits\t-\n'

echo "--- it refuses a grep for what the index just found ---"
check "same identifier, fresh hits"            deny "$(run "$FRESH_HIT" "SubmitLimits")"
check "the identifier inside a longer pattern" deny "$(run "$FRESH_HIT" "SubmitLimits.evaluate")"

echo "--- and stands aside everywhere ripgrep is the right tool ---"
check "index came back EMPTY"              allow "$(run "$EMPTY" "SubmitLimits")"
check "index reported itself STALE"        allow "$(run "$STALE_HIT" "SubmitLimits")"
check "an unrelated pattern"               allow "$(run "$FRESH_HIT" "tenant_id")"
check "no search recorded at all"          allow "$(run "" "SubmitLimits")"
check "a shell-surface row, no freshness"  allow "$(run "$SHELL_ROW" "SubmitLimits")"

echo "--- the operator escape still works ---"
check "MASTHEAD_CODE_GATE=off"               allow "$(run "$FRESH_HIT" "SubmitLimits" "MASTHEAD_CODE_GATE=off")"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
