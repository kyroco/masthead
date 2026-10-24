#!/usr/bin/env bash
# adr-structure-gate.sh: Stop / SubagentStop hook that blocks (exit 2) when a changed ADR lacks a required section or has an unmarked Factual Claims list, and advises when it cites no evidence.

set -uo pipefail

# Stand down when ADR_STRUCTURE_GATE is off; the block message does not mention it.
[ "${ADR_STRUCTURE_GATE:-on}" = "off" ] && exit 0

# Read the ADR folder from ADR_DIR, falling back to the repo's settings through project_fact.py.
ADR_DIR="$(python3 "$(dirname "$0")/project_fact.py" ADR_DIR "${ADR_DIR:-docs/adr}" 2>/dev/null)"
ADR_DIR="${ADR_DIR:-docs/adr}"
ADR_DIR="${ADR_DIR%/}"
# Expand a leading ~ in the ADR folder.
case "$ADR_DIR" in "~/"*) ADR_DIR="$HOME/${ADR_DIR#\~/}" ;; esac

# ---------- self-scoping: skip stop events from other named agents ----------
PAYLOAD=""
if [ ! -t 0 ]; then
  PAYLOAD="$(cat 2>/dev/null || true)"
fi

if [ -n "$PAYLOAD" ]; then
  if command -v jq >/dev/null 2>&1; then
    EVENT_AGENT="$(printf '%s' "$PAYLOAD" | jq -r '.agent_name // .agent_type // .subagent_type // empty' 2>/dev/null || true)"
  else
    # Read the agent name without jq when jq is missing.
    EVENT_AGENT="$(printf '%s' "$PAYLOAD" | tr ',{}' '\n\n\n' \
      | grep -Eo '"(agent_name|agent_type|subagent_type)"[[:space:]]*:[[:space:]]*"[^"]*"' 2>/dev/null \
      | head -n 1 \
      | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/' || true)"
  fi
  if [ -n "${EVENT_AGENT:-}" ] && [ "$EVENT_AGENT" != "maryam" ]; then
    exit 0
  fi
fi

# ---------- in-domain: did this change touch an ADR file? ----------
CHANGED=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # List changed files from git status, including untracked files one by one.
  CHANGED="$(git status --porcelain -u 2>/dev/null | awk '{print $NF}' || true)"
else
  echo "WARN (adr-structure-gate): not a git repo - cannot delta-scope; skipping cleanly." >&2
  exit 0
fi
# Also list the changed files of an ADR folder that lives in its own repository, as absolute paths.
case "$ADR_DIR" in
  /*)
    if [ -d "$ADR_DIR" ]; then
      ADR_TOP="$(git -C "$ADR_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
      if [ -n "$ADR_TOP" ]; then
        CHANGED="$CHANGED
$(git -C "$ADR_TOP" status --porcelain -u 2>/dev/null | awk -v top="$ADR_TOP" '{print top "/" $NF}' || true)"
      fi
    fi
    ;;
esac

# Keep only paths that look like ADR files.
ADR_FILES=""
for f in $CHANGED; do
  base="${f##*/}"
  is_adr=0
  case "$base" in
    ADR-*.md|adr-*.md) is_adr=1 ;;
  esac
  case "$f" in
    */adr/*|"$ADR_DIR"/*|*/"$ADR_DIR"/*)
      case "$base" in
        [0-9][0-9][0-9][0-9]-*.md|[0-9][0-9][0-9][0-9]_*.md|ADR-*.md|adr-*.md) is_adr=1 ;;
      esac
      ;;
  esac
  [ "$is_adr" -eq 1 ] && ADR_FILES="$ADR_FILES $f"
done

# Pass when no ADR file changed.
[ -z "$(printf '%s' "$ADR_FILES" | tr -d ' ')" ] && exit 0

# List the required section names, matched case-insensitively as a header or a bold or bullet label.
REQUIRED="Status|Principle Alignment|Context|Options Considered|Decision|Rationale|Falsifiability"

has_section() {
  # $1 = file content ; $2 = section label
  local content="$1" label="$2"
  # Match the label as a markdown header or a bold label, reading the content from a here-string so grep -q cannot break a pipe.
  grep -Eiq "^[[:space:]]*#{1,6}[[:space:]]+${label}([[:space:]]|$|:)|\*\*[[:space:]]*${label}[[:space:]]*\*\*|^[[:space:]]*-[[:space:]]+\*\*[[:space:]]*${label}" <<<"$content"
}

fail=0
advise=0
for f in $ADR_FILES; do
  [ -f "$f" ] || continue   # skip deletions/renames-away
  CONTENT="$(cat "$f" 2>/dev/null || true)"
  [ -z "$CONTENT" ] && continue

  missing=""
  OLD_IFS="$IFS"; IFS='|'
  for sec in $REQUIRED; do
    has_section "$CONTENT" "$sec" || missing="$missing, $sec"
  done
  IFS="$OLD_IFS"

  if [ -n "$missing" ]; then
    missing="${missing#, }"
    echo "BLOCKED (adr-structure-gate): $f is missing required ADR section(s): $missing" >&2
    echo "  An ADR records a decision in a fixed shape so the next reader and the" >&2
    echo "  implementer can act on it. Add the section(s) above. Required set:" >&2
    echo "    Status / Principle Alignment / Context / Options Considered / Decision /" >&2
    echo "    Rationale / Falsifiability." >&2
    echo "  This gate checks PRESENCE, not quality - a real Falsifiability line still" >&2
    echo "  needs a concrete 'if X happens, revisit', not a hedge." >&2
    fail=1
  fi

  # --- blocking: Factual Claims present but unverified ---
  FC_SECTION="$(printf '%s\n' "$CONTENT" | awk '
    tolower($0) ~ /^[[:space:]]*#+[[:space:]]+factual[[:space:]]+claims[[:space:]]*:?[[:space:]]*$/ { grab=1; next }
    grab==1 && /^[[:space:]]*#+[[:space:]]+/ { grab=0 }
    grab==1 { print }
  ')"

  if [ -n "$FC_SECTION" ]; then
    # Claim lines are bullet lines inside the section.
    if grep -Eq '^[[:space:]]*-[[:space:]]+' <<<"$FC_SECTION"; then
      # Accept a [verified: source] mark, an [unverified...] or [no worker...] flag, or a "No resident worker" line.
      if ! grep -Eiq '\[verified:[[:space:]]*[a-z]+\]|\[unverified[^]]*\]|\[no worker[^]]*\]|no resident worker' <<<"$FC_SECTION"; then
        echo "BLOCKED (adr-structure-gate): $f has Factual Claims with no verification marker." >&2
        echo "  Mark each claim [verified: <source>] once checked against the code, docs or" >&2
        echo "  live state, where the source is one word such as code, hexdocs or aws, or flag" >&2
        echo "  it '[unverified: <reason>]'. See Factual Claims in $ADR_DIR/_ADR-TEMPLATE.md." >&2
        echo "  Mark each claim, or flag it unverified, then continue." >&2
        fail=1
      fi
    fi
  fi

  # --- advisory: no evidence the codebase was read ---
  if ! grep -Eiq '\.[a-z0-9]+:[0-9]+|`[^`]+/[^`]+`|^[[:space:]]*#{1,6}[[:space:]]+Sources|\*\*[[:space:]]*Sources' <<<"$CONTENT"; then
    echo "ADVISORY (adr-structure-gate): $f cites no file:line / path reference and no" >&2
    echo "  Sources section - no evidence the codebase was read before deciding. If this" >&2
    echo "  decision touches existing code, ground it with a reference. ADVISORY ONLY;" >&2
    echo "  this does NOT block (a greenfield decision may legitimately cite nothing)." >&2
    advise=1
  fi

done

if [ "$fail" -ne 0 ]; then
  echo "ADR structure gate FAILED - add the missing section(s) above, then continue." >&2
  echo "Note: this gate checks section PRESENCE, not semantic quality." >&2
  exit 2
fi

[ "$advise" -ne 0 ] && echo "Note: the read-before-decide advisory above is a non-blocking nudge." >&2

exit 0
