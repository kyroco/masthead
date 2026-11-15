#!/usr/bin/env bash
# agent-brief-gates.sh: PreToolUse Agent hook that runs the brief check, the model option and the dispatch record on the same input and joins all their refusals (or any check that cannot run) into one deny decision; always exits 0.

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || HERE="$(dirname "$0")"

# The brief check and the dispatch record find the dispatch log through project_fact.py, so python3 must run,
# jq or not (MAST-38, round 0, A5). The macOS stub with no Command Line Tools is found and reads nothing. A missing
# project_fact.py is the brief check's own refusal: it cannot find its folder.
if ! python3 -I -c 'import json' >/dev/null 2>&1; then
  printf '%s\n' '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "python3 does not run, so the brief checks on the Agent tool cannot find the dispatch log or count re-verify rounds, and the dispatch is refused rather than sent unchecked. Install python3 (on macOS: xcode-select --install) and send it again."}}'
  exit 0
fi

# The payload goes to each check unparsed. The refusals are joined with jq when it is installed and with
# python3 when it is not, so a machine without jq is refused the same (MAST-37). With neither, every
# dispatch is refused, since no check could be read.
if command -v jq >/dev/null 2>&1; then
  HAVE_JQ=yes
# python3 must run, not only be found: the macOS stub with no Command Line Tools is found and reads nothing.
elif python3 -I -c 'import json' >/dev/null 2>&1 && [ -r "$HERE/json_field.py" ]; then
  HAVE_JQ=""
else
  printf '%s\n' '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Neither jq nor a working python3 is installed, so the brief checks on the Agent tool cannot run, and the dispatch is refused rather than sent unchecked. Install jq (brew install jq) and send it again."}}'
  exit 0
fi
PROTOCOL="$HERE/engram-protocol.sh"
DISPATCH="$HERE/dispatch-record-gate.sh"

# Collect refusals as JSON so reason text is never shell-escaped.
REFUSALS='[]'

refuse() {
  if [ -n "$HAVE_JQ" ]; then
    REFUSALS="$(printf '%s' "$REFUSALS" \
      | jq --arg id "$1" --arg reason "$2" '. + [{id: $id, reason: $reason}]' 2>/dev/null \
      || printf '%s' "$REFUSALS")"
  else
    REFUSALS="$(printf '%s' "$REFUSALS" | python3 -I -c 'import json, sys
print(json.dumps(json.load(sys.stdin) + [{"id": sys.argv[1], "reason": sys.argv[2]}]))' "$1" "$2" 2>/dev/null \
      || printf '%s' "$REFUSALS")"
  fi
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
  if [ -n "$HAVE_JQ" ]; then
    reasons="$(printf '%s' "$out" | jq -rj '
        [ .. | objects | select(has("permissionDecisionReason")) | .permissionDecisionReason ]
        | join("\n\n")' 2>/dev/null)"
  else
    reasons="$(printf '%s' "$out" | python3 -I "$HERE/json_field.py" --reasons 2>/dev/null)"
  fi

  # Quote the raw output when the decision cannot be read.
  if [ -z "${reasons//[[:space:]]/}" ]; then
    reasons="This check refused, but its decision could not be read. Its raw output was:"$'\n'"$out"
  fi

  refuse "$id" "$reasons"
  return 0
}

# Run every check in a fixed reporting order.
# The model gate is an install option; unset means on, so a copy outside a plugin keeps it.
case "$(printf '%s' "${CLAUDE_PLUGIN_OPTION_HAIKU_DEFAULT:-on}" | tr '[:upper:]' '[:lower:]')" in
  false|0|no|off) ;;
  *) collect "model-choice-gate"     bash "$HERE/model-choice-gate.sh" ;;
esac
collect "gate-verify-brief"     bash "$PROTOCOL" gate-verify-brief
# The record runs last so it can say whether the dispatch went through: a refused dispatch is recorded as refused and never counts as a re-verify round or an agent run.
if [ -n "$HAVE_JQ" ]; then
  REFUSED_COUNT="$(printf '%s' "$REFUSALS" | jq -r 'length' 2>/dev/null || echo 0)"
else
  REFUSED_COUNT="$(printf '%s' "$REFUSALS" | python3 -I -c 'import json, sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"
fi
if [ "$REFUSED_COUNT" != "0" ]; then
  collect "dispatch-record-gate"  bash "$DISPATCH" --refused
else
  collect "dispatch-record-gate"  bash "$DISPATCH"
fi

[ "$REFUSED_COUNT" != "0" ] || exit 0

if [ -z "$HAVE_JQ" ]; then
  # The same decision as the jq program below, word for word.
  printf '%s' "$REFUSALS" | python3 -I -c 'import json, sys
items, total = json.load(sys.stdin), sys.argv[1]
n = len(items)
plural = "check" if total == "1" else "checks"
body = "\n\n".join("[{} of {}] {}\n{}".format(i + 1, n, r["id"], r["reason"]) for i, r in enumerate(items))
reason = ("This dispatch is refused by " + str(n) + " of the " + total + " brief " + plural
          + " on the Agent tool. All of them are listed below, with what each one wants, so a single "
          + "editing pass answers the lot instead of you learning about the next one only after fixing "
          + "this one.\n\n" + body + "\n\nEach heading names the check that wrote it. They are "
          + "independent: satisfying one does not satisfy another, and none of them is answered by "
          + "mentioning it.")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                  "permissionDecision": "deny", "permissionDecisionReason": reason}}, ensure_ascii=False))' "$TOTAL" 2>/dev/null
  exit 0
fi

printf '%s' "$REFUSALS" | jq --arg total "$TOTAL" '
  length as $n
  | (if $total == "1" then "check" else "checks" end) as $plural
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
