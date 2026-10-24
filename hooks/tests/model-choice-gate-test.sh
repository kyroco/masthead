#!/usr/bin/env bash
# Prove model-choice-gate.sh refuses an unexplained Opus dispatch and lets the
# rest through. Decided by Robert 2026-10-09: Haiku is the default for helper
# work; Opus takes a first line `Model-choice: opus, <why>`.
set -u
HOOKS="$(cd "$(dirname "$0")/.." && pwd)"
GATE="$HOOKS/model-choice-gate.sh"
pass=0
fail=0

check() {
  local name="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    printf '  ok    %-56s %s\n' "$name" "$got"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-56s want %s got %s\n' "$name" "$want" "$got"
    fail=$((fail + 1))
  fi
}

# A throwaway project and user folder, so agent files are under test control.
ROOT="$(mktemp -d)"
mkdir -p "$ROOT/proj/.claude/agents" "$ROOT/conf/agents"
printf -- '---\nname: judge\nmodel: opus\n---\nbody\n' > "$ROOT/conf/agents/judge.md"
printf -- '---\nname: helper\nmodel: haiku\n---\nbody\n' > "$ROOT/conf/agents/helper.md"
printf -- '---\nname: plain\n---\nbody\n' > "$ROOT/conf/agents/plain.md"

# $1 subagent_type, $2 model field ("" for none), $3 prompt. Prints deny or allow.
run() {
  local payload out
  payload="$(jq -n --arg t "$1" --arg m "$2" --arg p "$3" \
    '{tool_name:"Agent", tool_input:({subagent_type:$t, prompt:$p} + (if $m == "" then {} else {model:$m} end))}')"
  out="$(printf '%s' "$payload" | env CLAUDE_PROJECT_DIR="$ROOT/proj" CLAUDE_PLUGIN_ROOT="$ROOT/conf" bash "$GATE" 2>/dev/null)"
  [ -n "$out" ] || { echo allow; return; }
  printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null | head -1
}

WHY=$'Model-choice: opus, this writes the fix and nothing checks its judgement\nDo the work.'
WHY_INDENTED=$'\n\n  model-choice: Opus, decides the design\nDo the work.'
NONE=$'Fix the bug in Extractor.Pool.'

echo "--- an unexplained Opus dispatch is refused ---"
check "general-purpose, no model, no line"                 deny  "$(run general-purpose "" "$NONE")"
check "no type at all, no model, no line"                  deny  "$(run "" "" "$NONE")"
check "model opus set on the call, no line"                deny  "$(run helper opus "$NONE")"
check "an agent file with no model line"                   deny  "$(run plain "" "$NONE")"
check "Plan inherits the session model"                    deny  "$(run Plan "" "$NONE")"
check "a Model-choice line that is not the first line"     deny  "$(run general-purpose "" $'Do the work.\nModel-choice: opus, because')"
check "a Model-choice line naming another tier"            deny  "$(run general-purpose opus $'Model-choice: haiku, cheap\nDo it.')"

echo "--- and everything else goes through ---"
check "general-purpose with model haiku"                   allow "$(run general-purpose haiku "$NONE")"
check "general-purpose with model sonnet"                  allow "$(run general-purpose sonnet "$NONE")"
check "general-purpose, Model-choice: opus line"           allow "$(run general-purpose "" "$WHY")"
check "opus on the call with the line (indented, any case)" allow "$(run helper opus "$WHY_INDENTED")"
check "an agent whose file sets opus"                      allow "$(run judge "" "$NONE")"
check "an agent whose file sets haiku"                     allow "$(run helper "" "$NONE")"
check "a fork runs on the parent's model"                  allow "$(run fork "" "$NONE")"
check "Explore picks its own model"                        allow "$(run Explore "" "$NONE")"
check "a plugin agent picks its own model"                 allow "$(run codex:codex-rescue "" "$NONE")"
check "a tool that is not Agent"                           allow "$(printf '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | bash "$GATE" | grep -q . && echo deny || echo allow)"
check "empty stdin"                                        allow "$(printf '' | bash "$GATE" | grep -q . && echo deny || echo allow)"
check "operator escape MASTHEAD_MODEL_GATE=off"            allow "$(printf '%s' "$(jq -n '{tool_name:"Agent",tool_input:{subagent_type:"general-purpose",prompt:"x"}}')" | MASTHEAD_MODEL_GATE=off bash "$GATE" | grep -q . && echo deny || echo allow)"

rm -rf "$ROOT"
echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
