#!/usr/bin/env bash
# dispatch-record-gate.sh: PreToolUse Agent hook that appends each dispatch's model, outcome and reason to the repo's dispatches.tsv; it never refuses and always exits 0.
# The outcome is dispatched, refused (agent-brief-gates.sh sets MASTHEAD_DISPATCH_OUTCOME when a check refused), or re-verify round N for a brief whose line starts "Re-verify:"; gate-verify-brief counts the re-verify rows.

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

command -v jq >/dev/null 2>&1 || exit 0

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
[ "$TOOL" = "Agent" ] || exit 0

PROMPT="$(printf '%s' "$INPUT" | jq -r '.tool_input.prompt // ""' 2>/dev/null || true)"
# Skip a payload with no prompt.
[ -n "$PROMPT" ] || exit 0
SUBTYPE="$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // "(default)"' 2>/dev/null || echo "(default)")"
NAME="$(printf '%s' "$INPUT" | jq -r '.tool_input.name // .tool_input.description // "(unnamed)"' 2>/dev/null || echo "(unnamed)")"
MODEL="$(printf '%s' "$INPUT" | jq -r '.tool_input.model // "(inherited)"' 2>/dev/null || echo "(inherited)")"
SID="$(printf '%s' "$INPUT" | jq -r '.session_id // "nosession"' 2>/dev/null || echo nosession)"

ROOT="$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)"
[ -n "$ROOT" ] || ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
RECORD_DIR="$ROOT/.claude/state"
RECORD="$RECORD_DIR/dispatches.tsv"

# Read the reason only from the first non-empty line of the prompt.
REASON="$(printf '%s' "$PROMPT" | awk '
  NF == 0 { next }
  {
    line = $0
    sub(/^[[:space:]]+/, "", line)
    if (tolower(substr(line, 1, 13)) == "model-choice:") {
      r = substr(line, 14)
      sub(/^[[:space:]]+/, "", r)
      sub(/[[:space:]]+$/, "", r)
      print r
    }
    exit
  }')"

# Flatten tabs and newlines so a field stays on one row.
flatten() { printf '%s' "$1" | tr '\t\n' '  ' | sed 's/  */ /g'; }

record() {
  # Append one row, best effort; every failure is ignored.
  mkdir -p "$RECORD_DIR" 2>/dev/null || return 0
  if [ ! -s "$RECORD" ]; then
    printf 'when\tsession\tagent\ttype\tmodel\toutcome\treason\n' >> "$RECORD" 2>/dev/null || return 0
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(printf '%s' "$SID" | cut -c1-8)" \
    "$(flatten "$NAME")" "$(flatten "$SUBTYPE")" "$(flatten "$MODEL")" \
    "$1" "$(flatten "$2")" >> "$RECORD" 2>/dev/null || return 0
  return 0
}

# Read the model from the agent's own file (project, then user folder) when the call sets none.
agent_file_model() {
  case "$1" in
    ''|*[!A-Za-z0-9_-]*) return 0 ;;
  esac
  local file="${CLAUDE_PROJECT_DIR:-$ROOT}/.claude/agents/$1.md"
  [ -r "$file" ] || file="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}/agents/$1.md"
  [ -r "$file" ] || return 0
  tr -d '\r' < "$file" 2>/dev/null | awk '
    NR == 1 { if ($0 ~ /^---[[:space:]]*$/) { inside = 1; next } else exit }
    inside && /^---[[:space:]]*$/ { exit }
    inside && /^model:/ { sub(/^model:[[:space:]]*/, ""); sub(/[[:space:]]+$/, ""); print; exit }'
}
if [ "$SUBTYPE" = "fork" ]; then
  # A fork runs on the parent's model.
  MODEL="(parent)"
elif [ "$MODEL" = "(inherited)" ]; then
  FROM_FILE="$(agent_file_model "$SUBTYPE")"
  [ -n "$FROM_FILE" ] && MODEL="$FROM_FILE (agent file)"
fi

# The outcome: what the wrapper says, else a re-verify round read from the brief, else dispatched.
OUTCOME="${MASTHEAD_DISPATCH_OUTCOME:-}"
if [ -z "$OUTCOME" ]; then
  OUTCOME="$(printf '%s' "$PROMPT" | awk '
    {
      line = $0
      sub(/^[[:space:]]*(\*\*)?/, "", line)
      if (tolower(substr(line, 1, 10)) == "re-verify:") {
        r = substr(line, 11)
        if (match(tolower(r), /round[[:space:]]+[0-9]+/)) {
          n = substr(r, RSTART, RLENGTH)
          sub(/^[^0-9]*/, "", n)
          print "re-verify round " n
        } else {
          print "re-verify"
        }
        exit
      }
    }')"
fi
record "${OUTCOME:-dispatched}" "${REASON:-(no Model-choice line)}"
exit 0
