#!/usr/bin/env bash
# Stop hook: keep the Korium code index current by running korium-cli index in the background for the session's checkout.
# Runs one index at a time per checkout and logs to korium-index-stop.log in the git folder.
# Kill switch: MASTHEAD_INDEX_ON_STOP=off, or git config korium.indexOnStop false.
set -u

case "${MASTHEAD_INDEX_ON_STOP:-}" in off|0|false|no) exit 0 ;; esac

root="${CLAUDE_PROJECT_DIR:-}"
[ -n "$root" ] || exit 0
[ -d "$root/.git" ] || [ -f "$root/.git" ] || exit 0
command -v korium-cli >/dev/null 2>&1 || exit 0

case "$(git -C "$root" config --get korium.indexOnStop 2>/dev/null || echo true)" in
  false|off|0|no) exit 0 ;;
esac

# The checkout's own git folder, so two worktrees on two branches each index.
git_dir="$(git -C "$root" rev-parse --absolute-git-dir 2>/dev/null)" || exit 0
pidfile="$git_dir/korium-index-stop.pid"
if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; then
  exit 0
fi

(
  cd "$root" || exit 0
  exec korium-cli index --from-hook --no-wait </dev/null >"$git_dir/korium-index-stop.log" 2>&1
) &
echo $! > "$pidfile"

exit 0
