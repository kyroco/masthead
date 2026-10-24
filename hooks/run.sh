#!/usr/bin/env bash
# run.sh: run one Masthead hook by name, unless the install option that governs it is off.
# Options arrive as CLAUDE_PLUGIN_OPTION_<KEY>; an unset option keeps the hook on, so a copy of
# these files outside a plugin behaves as it always did.
name="${1:-}"
[ -n "$name" ] || exit 0
shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[ -f "$here/$name" ] || exit 0
# An off switch the project's own settings env block sets is ignored, so a cloned repository cannot switch a check off.
proj="${CLAUDE_PROJECT_DIR:-}"
if [ -n "$proj" ] && [ -f "$proj/.claude/settings.json" ]; then
  for key in $(python3 -I -c 'import json, sys
try:
    env = json.load(open(sys.argv[1])).get("env") or {}
except Exception:
    env = {}
print(" ".join(k for k in env if k.startswith(("MASTHEAD_", "CLAUDE_PLUGIN_OPTION_")) or k.endswith("_GATE")))' "$proj/.claude/settings.json" 2>/dev/null); do
    unset "$key"
  done
fi
off() { case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in false|0|no|off) return 0 ;; *) return 1 ;; esac; }
korium_off() { off "${CLAUDE_PLUGIN_OPTION_KORIUM:-${MASTHEAD_KORIUM:-on}}"; }
index_off() { off "${CLAUDE_PLUGIN_OPTION_CODE_INDEX:-${MASTHEAD_CODE_INDEX:-on}}"; }
case "$name" in
  engram-protocol.sh)
    # The Korium memory gates: only with a connected Korium. The plugin's default is off.
    korium_off && exit 0
    # The code index gates send search names to korium-cli, so they need the code index option too.
    case "${1:-}" in gate-discovery|gate-redundant-grep|gate-span-read) index_off && exit 0 ;; esac ;;
  capture-finding-reminder.py)
    korium_off && exit 0 ;;
  korium-index-on-stop.sh)
    korium_off && exit 0
    index_off && exit 0 ;;
  commit-attribution-gate.py)
    off "${CLAUDE_PLUGIN_OPTION_STRICT_COMMITS:-on}" && exit 0 ;;
esac
case "$name" in
  *.py) exec python3 "$here/$name" "$@" ;;
  *.sh) exec bash "$here/$name" "$@" ;;
  *) exit 0 ;;
esac
