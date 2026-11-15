#!/usr/bin/env bash
# adr-structure-gate.sh: Stop hook that, in a repository that opted in with ADR_DIR, blocks (exit 2) when a changed ADR is short of the shape in adr_shape.py or has an unmarked Factual Claims list, and advises when it cites no evidence.

set -uo pipefail

# Stand down when ADR_STRUCTURE_GATE is off; the block message does not mention it.
[ "${ADR_STRUCTURE_GATE:-on}" = "off" ] && exit 0

HERE="$(cd "$(dirname "$0")" && pwd)"
SHAPE="$HERE/adr_shape.py"

# Not opted in: no ADR folder named, so no record is held to Masthead's shape.
ADR_DIR="$(python3 "$SHAPE" folder 2>/dev/null)"
[ -n "$ADR_DIR" ] || exit 0
ADR_DIR="${ADR_DIR%/}"

# ---------- self-scoping: hold only the main session's stop ----------
# A named agent's stop is skipped: the main session's own stop holds whatever it left.
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
  [ -n "${EVENT_AGENT:-}" ] && exit 0
fi

# ---------- in-domain: did this change touch an ADR file? ----------
CHANGED=""
if TOP="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  cd "$TOP" || exit 0
  # List changed files from git status, including untracked files one by one.
  # -z prints each path whole and unquoted, so a name with a space stays whole. A rename's
  # old name follows as a bare entry; cut mangles it, and the file check below skips it.
  CHANGED="$(git status --porcelain -z -u 2>/dev/null | tr '\0' '\n' | cut -c4- || true)"
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
$(git -C "$ADR_TOP" status --porcelain -z -u 2>/dev/null | tr '\0' '\n' | cut -c4- | awk -v top="$ADR_TOP" '{print top "/" $0}' || true)"
      fi
    fi
    ;;
esac

# Keep only the records inside the opted-in folder.
ADR_FILES="$(printf '%s\n' "$CHANGED" | python3 "$SHAPE" pick 2>/dev/null)"

# Pass when no ADR file changed.
[ -z "$(printf '%s' "$ADR_FILES" | tr -d '[:space:]')" ] && exit 0

fail=0
advise=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue   # skip deletions/renames-away
  CONTENT="$(cat "$f" 2>/dev/null || true)"
  [ -z "$CONTENT" ] && continue

  # A new record must carry the whole shape; one already committed must keep the sections it had.
  short="$(python3 "$SHAPE" check "$f" 2>/dev/null)"
  if [ -n "$short" ]; then
    echo "BLOCKED (adr-structure-gate): $f is short of the ADR shape this repository asked for:" >&2
    printf '%s\n' "$short" | sed 's/^/  - /' >&2
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
        echo "  live state, where the source is one word such as code, docs or aws, or flag" >&2
        echo "  it '[unverified: <reason>]'. Mark each claim, or flag it unverified, then continue." >&2
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

done <<<"$ADR_FILES"

if [ "$fail" -ne 0 ]; then
  echo "ADR structure gate FAILED - add the missing section(s) above, then continue." >&2
  echo "Note: this gate checks section PRESENCE, not semantic quality." >&2
  exit 2
fi

[ "$advise" -ne 0 ] && echo "Note: the read-before-decide advisory above is a non-blocking nudge." >&2

exit 0
