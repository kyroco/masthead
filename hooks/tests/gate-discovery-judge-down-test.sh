#!/usr/bin/env bash
# Prove gate-discovery treats a judge it cannot read as SEARCHABLE (refuse
# until a fresh code_locate lookup of the name), not as an allow. Decided by
# Robert 2026-10-09: a gate whose judge is down blocks rather than steps aside.
# The reason it matters: measured 2026-09-23, the judge read UNKNOWN on 15 of 16
# searches and the gate had been silently off.
#
# The hook finds its judge beside itself, so each case copies the hook into a
# temp folder with a fake judge that prints a chosen word.
set -u
HOOKS="$(cd "$(dirname "$0")/.." && pwd)"
# The code gates stand aside on a machine without korium-cli, so these cases get a stub on PATH:
# they are about the gate's own judgement, on a machine that has the tool.
STUBBIN="$(mktemp -d)/bin"; mkdir -p "$STUBBIN"; printf '#!/bin/sh\nexit 0\n' > "$STUBBIN/korium-cli"; chmod +x "$STUBBIN/korium-cli"; export PATH="$STUBBIN:$PATH"
pass=0
fail=0

check() {
  local name="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    printf '  ok    %-52s %s\n' "$name" "$got"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-52s want %s got %s\n' "$name" "$want" "$got"
    fail=$((fail + 1))
  fi
}

# $1 = what the fake judge prints ("-" for no judge installed), $2 = tsv of
# code searches, $3 = "down" to start with a fresh judge-down stamp, $4 = an
# optional env assignment. Prints deny or allow.
run() {
  local tmp sid out
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/hooks"
  cp "$HOOKS/engram-protocol.sh" "$HOOKS/shell-search-pattern.py" "$tmp/hooks/"
  if [ "$1" != "-" ]; then
    # The hook runs its judge with python3, so the fake is Python.
    printf 'import sys\nsys.stdin.read()\nprint(%s)\n' "'$1'" > "$tmp/hooks/korium-index-judge.py"
    chmod +x "$tmp/hooks/korium-index-judge.py"
  fi
  sid="probe-$RANDOM"
  mkdir -p "$tmp/claude-engram/$sid"
  printf '%s' "$2" > "$tmp/claude-engram/$sid/codesearches.tsv"
  [ "$3" = down ] && : > "$tmp/claude-engram/$sid/judge-down"
  out="$(printf '{"tool_name":"Grep","session_id":"%s","tool_input":{"pattern":"SubmitLimits"}}' "$sid" \
    | env TMPDIR="$tmp" ${4:+"$4"} bash "$tmp/hooks/engram-protocol.sh" gate-discovery 2>/dev/null)"
  rm -rf "$tmp"
  printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null | head -1 | grep . || echo allow
}

LOOKUP=$'5\tabc\tlib/x.ex:1-2\tSubmitLimits evaluate\tfresh\n'

echo "--- a judge that says SEARCHABLE refuses (so this probe can see a refusal) ---"
check "judge says SEARCHABLE, no lookup"               deny  "$(run SEARCHABLE "" "")"

echo "--- a judge that cannot be read refuses ---"
check "judge prints garbage, no lookup"                deny  "$(run BANANA "" "")"
check "judge marked down in the last five minutes"     deny  "$(run NOT_SEARCHABLE "" down)"
check "judge prints nothing"                           deny  "$(run "" "" "")"

echo "--- and the way through still works ---"
check "judge down, fresh lookup of the same name"      allow "$(run BANANA "$LOOKUP" "")"
check "judge says NOT_SEARCHABLE"                      allow "$(run NOT_SEARCHABLE "" "")"
check "judge says SEARCHABLE, fresh lookup"            allow "$(run SEARCHABLE "$LOOKUP" "")"
check "no judge installed"                             allow "$(run - "" "")"
check "MASTHEAD_CODE_GATE=off"                         allow "$(run BANANA "" "" MASTHEAD_CODE_GATE=off)"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
