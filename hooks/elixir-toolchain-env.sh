#!/usr/bin/env bash
# elixir-toolchain-env.sh: SessionStart and CwdChanged hook that adds a line to CLAUDE_ENV_FILE loading the checkout's pinned Elixir toolchain file for every Bash command; prints nothing and always exits 0.

set -uo pipefail

payload="$(cat)"
[ -n "${CLAUDE_ENV_FILE:-}" ] || exit 0

cwd=""
if command -v jq >/dev/null 2>&1; then
  cwd="$(printf '%s' "$payload" | jq -r '.cwd // ""' 2>/dev/null)"
fi
[ -n "$cwd" ] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

# Walk up to the checkout and ask which toolchain it pins.
d="$cwd"
while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -e "$d/.git" ]; do
  d="$(dirname "$d")"
done
[ -e "$d/.git" ] || exit 0
toolchain="$(python3 "$(dirname "$0")/project_fact.py" --root "$d" --path PROJECT_TOOLCHAIN_ENV 2>/dev/null)"
[ -n "$toolchain" ] && [ -f "$toolchain" ] || exit 0
# In a worktree, a toolchain file inside it is branch content: never load it from there.
if [ -f "$d/.git" ]; then
  case "$(cd "$(dirname "$toolchain")" 2>/dev/null && pwd -P)/" in "$(cd "$d" && pwd -P)/"*) exit 0 ;; esac
fi

line=". \"$toolchain\""
grep -qxF "$line" "$CLAUDE_ENV_FILE" 2>/dev/null || printf '%s\n' "$line" >> "$CLAUDE_ENV_FILE"
exit 0
