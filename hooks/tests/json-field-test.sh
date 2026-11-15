#!/usr/bin/env bash
# json_field.py stands in for jq on a machine without it (MAST-37). Every filter the gates hand it must
# print what jq prints, so a gate decides the same either way. Needs jq, to compare against.
set -uo pipefail
HELPER="$(cd "$(dirname "$0")/.." && pwd -P)/json_field.py"
command -v jq >/dev/null 2>&1 || { echo "skipped: jq is not installed, so there is nothing to compare with"; exit 77; }

pass=0; fail=0
same() {
  local payload="$1" filter="$2" want got
  want="$(printf '%s' "$payload" | jq -r "$filter" 2>/dev/null)"
  got="$(printf '%s' "$payload" | python3 -I "$HELPER" "$filter" 2>/dev/null)"
  if [ "$want" = "$got" ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); echo "FAIL: $filter on $payload: jq '$want', json_field '$got'" >&2; fi
}

FULL='{"tool_name":"Agent","session_id":"s1","cwd":"/w","tool_input":{"prompt":"line one\nClaims:\n- a b c d","subagent_type":"masthead:verifier","model":"opus","name":"n","description":"d","command":"git push -f"}}'
BARE='{"tool_name":"Bash","tool_input":{"description":"only a description","model":null,"name":false}}'
for payload in "$FULL" "$BARE" '{}'; do
  for filter in '.tool_name // empty' '.tool_input.command // empty' '.session_id // "nosession"' \
                '.tool_input.prompt // ""' '.tool_input.subagent_type // "(default)"' \
                '.tool_input.name // .tool_input.description // "(unnamed)"' \
                '.tool_input.model // "(inherited)"' '.cwd // empty' '.cwd // ""' \
                '.tool_input.subagent_type // ""' '.tool_input.model // ""' '.tool_input.model'; do
    same "$payload" "$filter"
  done
done

# A filter it does not read prints nothing, which the gates take as an absent field.
out="$(printf '%s' "$FULL" | python3 -I "$HELPER" '.tool_input | keys' 2>/dev/null)"; code=$?
if [ -z "$out" ] && [ "$code" -eq 2 ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: an unread filter printed '$out' (exit $code)" >&2; fi

# The refusal it writes is the one jq writes.
want="$(jq -cn --arg r 'no "claims" here' '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}')"
got="$(python3 -I "$HELPER" --deny 'no "claims" here' | jq -c .)"
if [ "$want" = "$got" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: --deny wrote $got" >&2; fi

# Every reason in a decision, at any depth, as the brief wrapper's jq program joins them.
DECISION='{"hookSpecificOutput":{"permissionDecisionReason":"first"},"more":[{"permissionDecisionReason":"second"}]}'
want="$(printf '%s' "$DECISION" | jq -rj '[ .. | objects | select(has("permissionDecisionReason")) | .permissionDecisionReason ] | join("\n\n")')"
got="$(printf '%s' "$DECISION" | python3 -I "$HELPER" --reasons)"
if [ "$want" = "$got" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: --reasons wrote '$got', jq '$want'" >&2; fi

echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
