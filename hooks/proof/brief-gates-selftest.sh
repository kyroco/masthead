#!/usr/bin/env bash
#
# Proof for the brief check in engram-protocol.sh, the file beside this folder.
#
# WHY THIS FILE EXISTS. The brief checks once screened a fixed list of agent
# names, so every dispatch under `general-purpose` or `fork` was exempt. The
# nine-reviewer wave of 2026-08-19 ran entirely under names neither gate had
# heard of, and neither gate read one of those briefs. Both were found by
# feeding the real hook synthetic payloads, which is what this script does, so
# the finding and the guard are the same mechanism.
#
# Since masthead issue #20 there is one brief check, gate-verify-brief: a brief
# to the verifier or the security reviewer carries a claims list. It screens the
# two agents by name, and the names Claude Code sends for a plugin's agents.
#
# Run it: bash hooks/proof/brief-gates-selftest.sh
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

echo "engram-protocol selftest: gate-verify-brief screens the verifier and the security reviewer only"

THIN="Verify this diff and report what you find."
WITH_CLAIMS="Verify this diff. Claims: the pass never raises; the ambiguous-commit case is not proven."

check "a thin brief to the verifier" \
  "deny" "$(verdict gate-verify-brief "$(agent_payload verifier "$THIN")")"

check "a thin brief to security-reviewer" \
  "deny" "$(verdict gate-verify-brief "$(agent_payload security-reviewer "$THIN")")"

check "a thin brief to masthead's verifier, as Claude Code names it" \
  "deny" "$(verdict gate-verify-brief "$(agent_payload masthead:verifier "$THIN")")"

check "the same words to general-purpose are not screened" \
  "allow" "$(verdict gate-verify-brief "$(agent_payload general-purpose "$THIN")")"

check "the same words to a fork are not screened" \
  "allow" "$(verdict gate-verify-brief "$(agent_payload fork "$THIN")")"

# The escape hatch has to stay truthful and usable, or the gate becomes theatre.
check "a verifier brief carrying a claims list is allowed" \
  "allow" "$(verdict gate-verify-brief "$(agent_payload verifier "$WITH_CLAIMS")")"

check "a brief that is not asking for a verification at all is allowed" \
  "allow" "$(verdict gate-verify-brief "$(agent_payload general-purpose 'Add a column to the tenants table.')")"

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "engram-protocol selftest: all checks passed."
  exit 0
fi

echo "engram-protocol selftest: $FAILURES check(s) FAILED." >&2
exit 1
