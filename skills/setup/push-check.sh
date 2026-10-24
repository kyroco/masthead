#!/usr/bin/env bash
# Masthead push check for this repository, written by /masthead:setup.
# Plain run: runs the test command on a clean tree and records which commit it passed on.
# --check: succeeds only when that record names the commit about to be pushed (HEAD).
TEST_COMMAND="__TEST_COMMAND__"
STATE_DIR="__STATE_DIR__"
set -u
root="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "push-check: not inside a git repository" >&2; exit 1; }
receipt="$root/$STATE_DIR/push-check.json"
tree="$(git -C "$root" rev-parse --verify -q 'HEAD^{tree}' 2>/dev/null)"

if [ "${1:-}" = "--check" ]; then
  [ -n "$tree" ] || { echo "push-check: no commit yet, nothing to check"; exit 1; }
  if [ -f "$receipt" ] && grep -q "\"tree\": \"$tree\"" "$receipt"; then
    exit 0
  fi
  echo "push-check: the tests have not passed on this commit. Run: bash .claude/push-check.sh"
  exit 1
fi

if [ -n "$(git -C "$root" status --porcelain)" ]; then
  echo "push-check: commit or stash your changes first, so the record names exactly what was tested" >&2
  exit 1
fi
echo "push-check: running: $TEST_COMMAND"
(cd "$root" && bash -c "$TEST_COMMAND") || { echo "push-check: tests failed, nothing recorded" >&2; exit 1; }
mkdir -p "$(dirname "$receipt")"
printf '{"tree": "%s", "command": "%s", "when": "%s"}\n' "$tree" "$TEST_COMMAND" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$receipt"
echo "push-check: tests passed on this commit; record written to $STATE_DIR/push-check.json"
