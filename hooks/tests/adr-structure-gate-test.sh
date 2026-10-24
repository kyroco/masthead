#!/usr/bin/env bash
# Tests for adr-structure-gate.sh, each in a throwaway git repository holding
# one changed ADR.
#
# The first case is the one that was broken: on an ADR larger than a
# pipe buffer, grep -q stopped reading at its first match, printf took SIGPIPE,
# and under pipefail a Status section that was there read as missing. ADR-0140
# (77 KB) was refused that way. The filler below makes every ADR here 200 KB.
#
# Run from anywhere: bash .claude/hooks/tests/adr-structure-gate-test.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GATE="$HERE/../adr-structure-gate.sh"
# Stop on a failed mktemp: bash 3.2 takes cd "" as success, so T would be the
# working directory and the trap would delete it.
T="$(mktemp -d "${TMPDIR:-/tmp}/adr-structure-gate-test.XXXXXX")" || exit 1
T="$(cd "$T" && pwd)" || exit 1
trap 'rm -rf "$T"' EXIT

pass=0
failures=0
ok() { echo "ok   - $1"; pass=$((pass + 1)); }
bad() { echo "FAIL - $1"; failures=$((failures + 1)); }

FILLER="$(awk 'BEGIN { for (i = 0; i < 2500; i++) printf "Filler line %05d, long enough to make the ADR larger than any pipe buffer.\n", i }')"

# $1 = case name, $2 = the ADR body. Commits a first version so the ADR shows
# as modified, the state the gate reads, then writes $2 over it.
repo() {
  local r="$T/$1"
  mkdir -p "$r/docs/adr"
  git -C "$r" init -q
  echo "first" > "$r/docs/adr/ADR-9999-test.md"
  git -C "$r" add . >/dev/null
  git -C "$r" -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@example.com commit -q -m first
  printf '%s\n' "$2" > "$r/docs/adr/ADR-9999-test.md"
  echo "$r"
}

# $1 = repo, $2 = stdin payload (empty for none). Sets code and err.
run_gate() {
  err="$T/err.txt"
  code=0
  if [ -n "$2" ]; then
    (cd "$1" && printf '%s' "$2" | bash "$GATE") 2>"$err" || code=$?
  else
    (cd "$1" && bash "$GATE" </dev/null) 2>"$err" || code=$?
  fi
}

sections() {
  cat <<'MD'
# ADR-9999: a test decision

## Status

Accepted

## Principle Alignment

P7.

## Context

See `products/apps/engram_core/lib/engram.ex:1`.

## Options Considered

One.

## Decision

This one.

## Rationale

Because.
MD
}

FALSIFIABILITY="## Falsifiability

If it breaks, revisit."

# ---------------------------------------------------------------- the pipe bug
r="$(repo large-complete "$(sections)
$FALSIFIABILITY
$FILLER")"
run_gate "$r" ""
if [ "$code" -eq 0 ] && ! grep -q 'missing required' "$err"; then
  ok "a 200 KB ADR with every section passes"
else
  bad "a 200 KB ADR with every section passes (exit $code: $(head -1 "$err"))"
fi

r="$(repo large-missing "$(sections)
$FILLER")"
run_gate "$r" ""
if [ "$code" -eq 2 ] && grep -q 'missing required ADR section(s): Falsifiability$' "$err"; then
  ok "a 200 KB ADR missing Falsifiability is refused, naming only that section"
else
  bad "a 200 KB ADR missing Falsifiability is refused, naming only that section (exit $code: $(head -1 "$err"))"
fi

# ---------------------------------------------------------------- Factual Claims
claims() {
  printf '%s\n%s\n\n### Factual Claims\n\n- The table has an index. %s\n\n%s\n' \
    "$(sections)" "$FALSIFIABILITY" "$1" "$FILLER"
}

r="$(repo claims-unmarked "$(claims '')")"
run_gate "$r" ""
if [ "$code" -eq 2 ] && grep -q 'Factual Claims with no verification marker' "$err"; then
  ok "Factual Claims with no verification marker are refused"
else
  bad "Factual Claims with no verification marker are refused (exit $code: $(head -1 "$err"))"
fi

r="$(repo claims-marked "$(claims '[verified: code]')")"
run_gate "$r" ""
if [ "$code" -eq 0 ]; then
  ok "Factual Claims marked verified pass"
else
  bad "Factual Claims marked verified pass (exit $code: $(head -1 "$err"))"
fi

# ---------------------------------------------------------------- scoping
r="$(repo other-agent "$(sections)")"
run_gate "$r" '{"agent_name":"reviewer"}'
if [ "$code" -eq 0 ]; then
  ok "another agent's stop event is not held"
else
  bad "another agent's stop event is not held (exit $code)"
fi

run_gate "$r" '{"agent_name":"maryam"}'
if [ "$code" -eq 2 ]; then
  ok "Maryam's stop event is held on an incomplete ADR"
else
  bad "Maryam's stop event is held on an incomplete ADR (exit $code)"
fi

r="$T/no-adr"
mkdir -p "$r"
git -C "$r" init -q
echo "x" > "$r/notes.md"
run_gate "$r" ""
if [ "$code" -eq 0 ]; then
  ok "a change with no ADR in it is not held"
else
  bad "a change with no ADR in it is not held (exit $code)"
fi

echo
echo "$pass passed, $failures failed"
[ "$failures" -eq 0 ]
