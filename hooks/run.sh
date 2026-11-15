#!/usr/bin/env bash
# run.sh: run one Masthead hook by name, unless the install option that governs it is off.
# Options arrive as CLAUDE_PLUGIN_OPTION_<KEY>; an unset option keeps the hook on, so a copy of
# these files outside a plugin behaves as it always did.
name="${1:-}"
[ -n "$name" ] || exit 0
shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[ -f "$here/$name" ] || exit 0
# An off switch the repository's own files set is ignored, so a cloned repository cannot switch a check off:
# its settings.json, and a settings.local.json git tracks (MAST-38). project_fact.py reads both files, in
# the order Claude Code applies them, so a hook's facts and this list come from the one reader.
proj="${CLAUDE_PROJECT_DIR:-}"
if [ -n "$proj" ]; then
  for key in $(python3 -I "$here/project_fact.py" --repo-switch-keys 2>/dev/null); do
    case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac
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
