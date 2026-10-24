#!/usr/bin/env bash
# elixir-format-after-edit.sh: PostToolUse Edit|Write|MultiEdit hook that runs mix format and credo on the one Elixir file just changed and reports the result as feedback; never blocks the edit and always exits 0.

set -uo pipefail

payload="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
file="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // .tool_input.notebook_path // ""' 2>/dev/null)"

case "$file" in
  *.ex|*.exs|*.heex) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

top="$(cd "$(dirname "$file")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -n "$top" ] || exit 0
fact() { python3 "$(dirname "$0")/project_fact.py" --root "$top" "$@" 2>/dev/null; }
# Run mix only in the session's own repository.
python3 "$(dirname "$0")/project_fact.py" --trusted "$top" 2>/dev/null || exit 0

root="$(fact --path PROJECT_ELIXIR_ROOT)"
if [ -z "$root" ]; then
  d="$(dirname "$file")"
  while :; do
    [ -f "$d/mix.exs" ] && root="$d"
    if [ "$d" = "$top" ] || [ "$d" = "/" ]; then break; fi
    d="$(dirname "$d")"
  done
fi
[ -n "$root" ] && [ -f "$root/mix.exs" ] && [ -f "$root/.formatter.exs" ] || exit 0
case "$file" in "$root"/*) ;; *) exit 0 ;; esac

toolchain="$(fact --path PROJECT_TOOLCHAIN_ENV)"
if [ -n "$toolchain" ] && [ -f "$toolchain" ]; then
  # shellcheck disable=SC1090
  . "$toolchain"
fi
command -v mix >/dev/null 2>&1 || exit 0

emit() {
  # $1 = "block" to hand the reason back as feedback, "" for context only
  if [ "$1" = "block" ]; then
    jq -n --arg r "$2" '{decision: "block", reason: $r}'
  else
    jq -n --arg c "$2" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $c}}'
  fi
}

# Match only mix's own lines that show missing or outdated deps.
unfetched='^(\*\* \(Mix\) .*(Unknown dependency|could not be found|Could not find|is not available|Can.t continue due to errors on dependencies)|Unchecked dependencies)'

session="$(printf '%s' "$payload" | jq -r '.session_id // "nosession"' 2>/dev/null | tr -cd 'A-Za-z0-9_-')"
skipped_once() {
  # $1 = which step could not load, $2 = a note that must still reach the session.
  marker="${TMPDIR:-/tmp}/elixir-format-after-edit.${session:-nosession}.skipped"
  if [ -e "$marker" ]; then
    [ -n "${2:-}" ] && emit "" "$2"
    exit 0
  fi
  : > "$marker"
  emit "" "${2:+$2 }The per-edit format and lint check is not running in this checkout: its Elixir deps are missing or out of date ($1). Run 'mix deps.get' in $root to turn it back on. The push gate and CI still run the full check."
  exit 0
}

before="$(shasum "$file" | cut -d' ' -f1)"
fmt_out="$(cd "$root" && mix format "$file" 2>&1)"
fmt_rc=$?
if [ $fmt_rc -ne 0 ]; then
  if printf '%s' "$fmt_out" | grep -Eq "$unfetched"; then
    skipped_once "mix format could not load them"
  fi
  emit block "mix format failed on $file, which usually means the edit left a syntax error:
$(printf '%s\n' "$fmt_out" | tail -20)"
  exit 0
fi
after="$(shasum "$file" | cut -d' ' -f1)"
note=""
if [ "$before" != "$after" ]; then
  note="mix format rewrote $file after your edit. Re-read it before editing it again."
fi

# Lint only the folders the whole-tree credo run lints.
rel="${file#"$root"/}"
case "$file" in
  *.heex) lint=no ;;
  *) case "$rel" in
       lib/*|src/*|test/*|web/*|apps/*/lib/*|apps/*/src/*|apps/*/test/*|apps/*/web/*) lint=yes ;;
       *) lint=no ;;
     esac
     case "/$rel" in
       */_build/*|*/deps/*|*/node_modules/*|*/test/fixtures/*) lint=no ;;
     esac ;;
esac
# Format only when the project does not use credo.
if [ ! -f "$root/.credo.exs" ] && ! grep -q '"credo"' "$root/mix.lock" 2>/dev/null; then
  lint=no
fi
if [ "$lint" = no ]; then
  [ -n "$note" ] && emit "" "$note"
  exit 0
fi

credo_out="$(cd "$root" && mix credo --strict "$file" 2>&1)"
credo_rc=$?
if [ $credo_rc -ne 0 ]; then
  if printf '%s' "$credo_out" | grep -Eq "$unfetched"; then
    skipped_once "mix credo could not load them" "$note"
  fi
  emit block "${note:+$note
}mix credo --strict reported issues in $file. Fix them now, while the change is fresh:
$(printf '%s\n' "$credo_out" | tail -30)"
  exit 0
fi

[ -n "$note" ] && emit "" "$note"
exit 0
