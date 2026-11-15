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

# Python 3.6 (RHEL 8's python3) has no TextIOWrapper.reconfigure: the helper must not need it (MAST-37).
out="$(printf '%s' "$FULL" | python3 -I -c '
import io, runpy, sys
class Old(io.TextIOWrapper):
    def __getattribute__(self, name):
        if name == "reconfigure":
            raise AttributeError(name)
        return io.TextIOWrapper.__getattribute__(self, name)
sys.stdin = Old(sys.stdin.buffer, encoding="utf-8")
sys.stdout = Old(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.argv = [sys.argv[1], ".tool_input.command"]
runpy.run_path(sys.argv[0], run_name="__main__")' "$HELPER" 2>&1)"
if [ "$out" = "git push -f" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: with no reconfigure (Python 3.6) the helper printed '$out'" >&2; fi

# A lone surrogate, which JSON can carry as \ud800, must not stop the command being read (MAST-37).
out="$(printf '%s' '{"tool_input":{"command":"git push --force origin main # \ud800"}}' | python3 -I "$HELPER" '.tool_input.command' 2>/dev/null)"
case "$out" in "git push --force origin main # "*) pass=$((pass + 1)) ;; *) fail=$((fail + 1)); echo "FAIL: a lone surrogate gave '$out'" >&2 ;; esac
out="$(python3 -I "$HELPER" --deny "$(printf 'x \355\240\200 y')" 2>/dev/null)"
case "$out" in *'"deny"'*) pass=$((pass + 1)) ;; *) fail=$((fail + 1)); echo "FAIL: a refusal with a stray byte printed '$out'" >&2 ;; esac

echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
