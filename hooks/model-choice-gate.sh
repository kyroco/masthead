#!/usr/bin/env bash
# model-choice-gate.sh - PreToolUse Agent: refuse a dispatch that would run on Opus unless the brief's first line is `Model-choice: opus, <why>`.
# Reads tool-call JSON on stdin, prints one deny decision as JSON or nothing, and always exits 0.

set -uo pipefail

case "${MASTHEAD_MODEL_GATE:-}" in off|0|false|no) exit 0 ;; esac

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

field() { printf '%s' "$INPUT" | jq -r "$1" 2>/dev/null || true; }

[ "$(field '.tool_name // empty')" = "Agent" ] || exit 0

TYPE="$(field '.tool_input.subagent_type // ""')"
MODEL="$(field '.tool_input.model // ""' | tr '[:upper:]' '[:lower:]')"
PROMPT="$(field '.tool_input.prompt // ""')"

[ "$TYPE" = "fork" ] && exit 0

# The model a plain-named agent's own file sets, project folder first.
agent_file_model() {
  case "$1" in ''|*[!A-Za-z0-9_-]*) return 0 ;; esac
  local file="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/agents/$1.md"
  [ -r "$file" ] || file="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}/agents/$1.md"
  [ -r "$file" ] || return 0
  tr -d '\r' < "$file" 2>/dev/null | awk '
    NR == 1 { if ($0 ~ /^---[[:space:]]*$/) { inside = 1; next } else exit }
    inside && /^---[[:space:]]*$/ { exit }
    inside && /^model:/ { sub(/^model:[[:space:]]*/, ""); sub(/[[:space:]]+$/, ""); print; exit }'
}

if [ -z "$MODEL" ]; then
  case "$TYPE" in
    Explore|claude-code-guide|statusline-setup|*:*) exit 0 ;;
  esac
  [ -n "$(agent_file_model "$TYPE")" ] && exit 0
  MODEL="inherited"
fi

case "$MODEL" in *haiku*|*sonnet*) exit 0 ;; esac

# Read the first non-empty line as a declaration only when it opens with Model-choice: and names a tier other than haiku or sonnet.
first="$(printf '%s\n' "$PROMPT" | awk 'NF { print; exit }' | sed 's/^[[:space:]]*//' | tr '[:upper:]' '[:lower:]')"
case "$first" in
  model-choice:*)
    tier="$(printf '%s' "${first#model-choice:}" | sed 's/^[[:space:]]*//' | cut -d, -f1 | awk '{print $1}')"
    case "$tier" in ''|haiku*|sonnet*) ;; *) exit 0 ;; esac
    ;;
esac

if [ "$MODEL" = "inherited" ]; then
  runs="sets no model, so it runs on this session's model (Opus)"
else
  runs="runs on ${MODEL}"
fi
jq -n --arg r "Haiku is the default for helper work. This dispatch ${runs} and the brief does not say why. Either set model to \"haiku\" (or \"sonnet\") on the Agent call, or make the brief's first line \"Model-choice: opus, <why>\", for work that decides something no later step checks, such as writing code or judging a design." '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'
exit 0
