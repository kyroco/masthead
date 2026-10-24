#!/usr/bin/env bash
# agent-brief-gates.sh: PreToolUse Agent hook that runs every brief check on the same input and joins all their refusals (or any check that cannot run) into one deny decision; always exits 0.

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

# Pass the payload to each check unparsed.
command -v jq >/dev/null 2>&1 || exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || HERE="$(dirname "$0")"
PROTOCOL="$HERE/engram-protocol.sh"
DISPATCH="$HERE/dispatch-record-gate.sh"

# Collect refusals as JSON so reason text is never shell-escaped.
REFUSALS='[]'

refuse() {
  REFUSALS="$(printf '%s' "$REFUSALS" \
    | jq --arg id "$1" --arg reason "$2" '. + [{id: $id, reason: $reason}]' 2>/dev/null \
    || printf '%s' "$REFUSALS")"
}

TOTAL=0

collect() {
  TOTAL=$((TOTAL + 1))
  local id="$1"
  shift
  local script="$2"

  if [ ! -r "$script" ]; then
    refuse "$id" "This check could not be run at all: ${script} is missing or unreadable. That is a broken hook installation and not a problem with the brief. Restore the file, or take this check out of agent-brief-gates.sh deliberately."
    return 0
  fi

  local out status
  out="$(printf '%s' "$INPUT" | "$@" 2>/dev/null)"
  status=$?

  # Nothing written and a clean exit means allow.
  if [ -z "${out//[[:space:]]/}" ]; then
    if [ "$status" -ne 0 ]; then
      refuse "$id" "This check exited ${status} without writing a decision, so what it would have said is unknown. A check whose answer cannot be read is treated as a refusal rather than an allow, because the alternative is losing it silently."
    fi
    return 0
  fi

  # Pull every reason the refusal carried.
  local reasons
  reasons="$(printf '%s' "$out" | jq -rj '
      [ .. | objects | select(has("permissionDecisionReason")) | .permissionDecisionReason ]
      | join("\n\n")' 2>/dev/null)"

  # Quote the raw output when the decision cannot be read.
  if [ -z "${reasons//[[:space:]]/}" ]; then
    reasons="This check refused, but its decision could not be read. Its raw output was:"$'\n'"$out"
  fi

  refuse "$id" "$reasons"
  return 0
}

# Run every check in a fixed reporting order.
collect "dispatch-record-gate"  bash "$DISPATCH"
# The model gate is an install option; unset means on, so a copy outside a plugin keeps it.
case "$(printf '%s' "${CLAUDE_PLUGIN_OPTION_HAIKU_DEFAULT:-on}" | tr '[:upper:]' '[:lower:]')" in
  false|0|no|off) ;;
  *) collect "model-choice-gate"     bash "$HERE/model-choice-gate.sh" ;;
esac
collect "gate-agent"            bash "$PROTOCOL" gate-agent
collect "gate-fix-evidence"     bash "$PROTOCOL" gate-fix-evidence
collect "gate-wave-brief"       bash "$PROTOCOL" gate-wave-brief
collect "gate-brief-inference"  bash "$PROTOCOL" gate-brief-inference

[ "$(printf '%s' "$REFUSALS" | jq -r 'length' 2>/dev/null || echo 0)" != "0" ] || exit 0

printf '%s' "$REFUSALS" | jq --arg total "$TOTAL" '
  length as $n
  | (if $n == 1 then "check" else "checks" end) as $plural
  | (to_entries
     | map("[" + ((.key + 1) | tostring) + " of " + ($n | tostring) + "] "
           + .value.id + "\n" + .value.reason)
     | join("\n\n")) as $body
  | {
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: (
          "This dispatch is refused by " + ($n | tostring) + " of the " + $total + " brief "
          + $plural + " on the Agent tool. All of them are listed below, with "
          + "what each one wants, so a single editing pass answers the lot "
          + "instead of you learning about the next one only after fixing this "
          + "one.\n\n"
          + $body
          + "\n\nEach heading names the check that wrote it. They are "
          + "independent: satisfying one does not satisfy another, and none of "
          + "them is answered by mentioning it."
        )
      }
    }' 2>/dev/null

exit 0
