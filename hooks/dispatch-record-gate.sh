#!/usr/bin/env bash
# dispatch-record-gate.sh: PreToolUse Agent hook that appends each dispatch's model, outcome, reason and branch to the repo's dispatches.tsv; it never refuses and always exits 0.
# The outcome is dispatched, refused (agent-brief-gates.sh passes --refused when a check refused), or re-verify round N for a brief with a line that begins exactly "Re-verify: round N"; gate-verify-brief counts the verifier's re-verify rows on the checkout's branch. The row is written before the agent runs, so a dispatch that dies or is declined still has its row.

set -uo pipefail

# The one argument the wrapper may pass: --refused, when a brief check said no.
REFUSED=""
[ "${1:-}" = "--refused" ] && REFUSED=yes

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

# jq reads the call when it is installed, json_field.py when it is not, so every dispatch is recorded without jq too (MAST-37).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || HERE="$(dirname "$0")"
if command -v jq >/dev/null 2>&1; then
  field() { printf '%s' "$INPUT" | jq -r "$1" 2>/dev/null; }
else
  field() { printf '%s' "$INPUT" | python3 -I "$HERE/json_field.py" "$1" 2>/dev/null; }
fi

TOOL="$(field '.tool_name // empty' || true)"
[ "$TOOL" = "Agent" ] || exit 0

PROMPT="$(field '.tool_input.prompt // ""' || true)"
# Skip a payload with no prompt.
[ -n "$PROMPT" ] || exit 0
SUBTYPE="$(field '.tool_input.subagent_type // "(default)"' || echo "(default)")"
NAME="$(field '.tool_input.name // .tool_input.description // "(unnamed)"' || echo "(unnamed)")"
MODEL="$(field '.tool_input.model // "(inherited)"' || echo "(inherited)")"
SID="$(field '.session_id // "nosession"' || echo nosession)"

ROOT="$(field '.cwd // empty' || true)"
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
    printf 'when\tsession\tagent\ttype\tmodel\toutcome\treason\tbranch\n' >> "$RECORD" 2>/dev/null || return 0
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(printf '%s' "$SID" | cut -c1-8)" \
    "$(flatten "$NAME")" "$(flatten "$SUBTYPE")" "$(flatten "$MODEL")" \
    "$1" "$(flatten "$2")" "$(flatten "$BRANCH")" >> "$RECORD" 2>/dev/null || return 0
  return 0
}

# The checkout's branch, so a reused session's next issue starts its own count; "-" outside a branch.
BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
[ -n "$BRANCH" ] || BRANCH="-"

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

# The outcome: refused when the wrapper says so, else a re-verify round read from the brief, else dispatched.
OUTCOME=""
[ -n "$REFUSED" ] && OUTCOME="refused"
if [ -z "$OUTCOME" ]; then
  # One exact form, the same one gate-verify-brief reads: a line that begins "Re-verify: round N" at column zero. Any other spelling is not a re-verify (the gate refuses it before it runs).
  OUTCOME="$(printf '%s' "$PROMPT" | awk '
    {
      line = $0
      sub(/\r$/, "", line)
      if (match(line, /^Re-verify: round [0-9]+/)) {
        n = substr(line, 18, RLENGTH - 17)
        print "re-verify round " n
        exit
      }
    }')"
fi
record "${OUTCOME:-dispatched}" "${REASON:-(no Model-choice line)}"
exit 0
