#!/usr/bin/env bash
#
# Proof for the brief gates in engram-protocol.sh, the file beside this folder.
#
# WHY THIS FILE EXISTS. gate-wave-brief and gate-brief-inference each screened
# a fixed list of agent names, so every dispatch under `general-purpose` or
# `fork` was exempt. The nine-reviewer wave of 2026-08-19 ran entirely under
# names neither gate had heard of, and neither gate read one of those briefs.
# Both were found by feeding the real hook synthetic payloads, which is what
# this script does, so the finding and the guard are the same mechanism.
#
# A gate keyed on one spelling of a thing teaches you the other spelling. So
# every case below is a way of expressing the SAME intention, and the gate has
# to answer them the same.
#
# Run it: bash ~/.claude/hooks/proof/brief-gates-selftest.sh
# It needs bash and jq. It runs the hook only and changes nothing.

set -uo pipefail

HOOKS="${GATE_HOOKS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
HOOK="$HOOKS/engram-protocol.sh"

if [ ! -x "$HOOK" ] && [ ! -f "$HOOK" ]; then
  echo "engram-protocol selftest: cannot find $HOOK" >&2
  exit 2
fi

command -v jq >/dev/null 2>&1 || { echo "engram-protocol selftest: jq is required" >&2; exit 2; }

FAILURES=0

# verdict <mode> <payload json> -> "deny" or "allow"
#
# Allow is the EMPTY answer, which is the fail-open direction, so a gate that
# crashes reads as allow here exactly as it would in the client. That is the
# honest thing to assert against.
verdict() {
  local out
  out="$(printf '%s' "$2" | bash "$HOOK" "$1" 2>/dev/null)"
  if printf '%s' "$out" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; then
    echo deny
  else
    echo allow
  fi
}

check() {
  local what="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  ok   $what"
  else
    echo "  FAIL $what"
    echo "       expected: [$expected]"
    echo "       actual:   [$actual]"
    FAILURES=$((FAILURES + 1))
  fi
}

agent_payload() { jq -n --arg s "$1" --arg p "$2" '{session_id:"selftest", tool_input:{subagent_type:$s, prompt:$p}}'; }

echo "engram-protocol selftest: the hook still answers when fed to bash -c"

# `set -u` is on and BASH_SOURCE is unbound when the file is fed to `bash -c`
# rather than run as a path. An abort before any mode runs would print nothing,
# and an empty answer is allow for every gate in the file at once. gate-edit
# denies an unsearched edit, so it has to produce output.
hookless_verdict() {
  local out
  out="$(printf '%s' "$1" | bash -c "$(cat "$HOOK")" _ "$2" 2>/dev/null)"
  if printf '%s' "$out" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; then
    echo deny
  else
    echo allow
  fi
}

check "fed to bash -c, gate-edit still answers rather than falling silent" \
  "deny" "$(hookless_verdict "$(jq -n '{session_id:"selftest", tool_input:{file_path:"/repo/docs/x.md"}}')" gate-edit)"

echo "engram-protocol selftest: gate-wave-brief screens the two review agents only"

THIN_REVIEW="Review this diff and report what you find."

check "a thin review brief to reviewer" \
  "deny" "$(verdict gate-wave-brief "$(agent_payload reviewer "$THIN_REVIEW")")"

check "a thin review brief to security-reviewer" \
  "deny" "$(verdict gate-wave-brief "$(agent_payload security-reviewer "$THIN_REVIEW")")"

check "the same words to general-purpose are not screened" \
  "allow" "$(verdict gate-wave-brief "$(agent_payload general-purpose "$THIN_REVIEW")")"

check "the same words to a fork are not screened" \
  "allow" "$(verdict gate-wave-brief "$(agent_payload fork "$THIN_REVIEW")")"

# The escape hatch has to stay truthful and usable, or the gate becomes theatre.
check "a brief carrying the author's claims and the seam is allowed" \
  "allow" \
  "$(verdict gate-wave-brief "$(agent_payload general-purpose \
      'Review this. The author claims the pass never raises, and could not prove the ambiguous-commit case. It is self-contained and depends on nothing outside the diff.')")"

check "a brief that is not asking for a review at all is allowed" \
  "allow" "$(verdict gate-wave-brief "$(agent_payload general-purpose 'Add a column to the tenants table.')")"

echo "engram-protocol selftest: gate-brief-inference, whoever is being asked"

CANNOT="This cannot be done any other way, so use the atomics cell."

check "an unattributed impossibility under general-purpose" \
  "deny" "$(verdict gate-brief-inference "$(agent_payload general-purpose "$CANNOT")")"

check "an unattributed impossibility under fork" \
  "deny" "$(verdict gate-brief-inference "$(agent_payload fork "$CANNOT")")"

check "an unattributed impossibility under a named specialist, which always worked" \
  "deny" "$(verdict gate-brief-inference "$(agent_payload thiago "$CANNOT")")"

check "the same sentence, marked as the lead's own inference, is allowed" \
  "allow" \
  "$(verdict gate-brief-inference "$(agent_payload general-purpose \
      'This cannot be done any other way. That is my inference, not a rule: disprove it if you can.')")"

check "a reviewer is exempt, because its brief is screened by gate-wave-brief" \
  "allow" "$(verdict gate-brief-inference "$(agent_payload reviewer "$CANNOT")")"

check "a brief claiming no impossibility is allowed" \
  "allow" "$(verdict gate-brief-inference "$(agent_payload general-purpose 'Make the report print the skipped count.')")"

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "engram-protocol selftest: all checks passed."
  exit 0
fi

echo "engram-protocol selftest: $FAILURES check(s) FAILED." >&2
exit 1
