#!/usr/bin/env bash
# run.sh: run one Masthead hook by name, unless the install option that governs it is off.
# Options arrive as CLAUDE_PLUGIN_OPTION_<KEY>; an unset option keeps the hook on, so a copy of
# these files outside a plugin behaves as it always did.
name="${1:-}"
[ -n "$name" ] || exit 0
shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[ -f "$here/$name" ] || exit 0
off() { case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in false|0|no|off) return 0 ;; *) return 1 ;; esac; }
case "$name" in
  engram-protocol.sh|capture-finding-reminder.py|korium-index-on-stop.sh)
    # The Korium memory gates: only with a connected Korium. The plugin's default is off.
    off "${CLAUDE_PLUGIN_OPTION_KORIUM:-${MASTHEAD_KORIUM:-on}}" && exit 0 ;;
  commit-attribution-gate.py)
    off "${CLAUDE_PLUGIN_OPTION_STRICT_COMMITS:-on}" && exit 0 ;;
esac
case "$name" in
  *.py) exec python3 "$here/$name" "$@" ;;
  *.sh) exec bash "$here/$name" "$@" ;;
  *) exit 0 ;;
esac
