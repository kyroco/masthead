#!/usr/bin/env bash
# Masthead push check for this repository, written by /masthead:setup.
# The test command is the one line of the sibling file push-check.cmd, run as written.
# Plain run: runs the test command on a clean tree and records which tree it passed on.
# --check: succeeds only when that record names the tree about to be pushed (HEAD).
STATE_DIR="__STATE_DIR__"
set -u
root="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "push-check: not inside a git repository" >&2; exit 1; }
self="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/$(basename "${BASH_SOURCE[0]}")"
cmd_file="${self%.sh}.cmd"
receipt="$root/$STATE_DIR/push-check.json"
tree="$(git -C "$root" rev-parse --verify -q 'HEAD^{tree}' 2>/dev/null)"

if [ "${1:-}" = "--check" ]; then
  [ -n "$tree" ] || { echo "push-check: no commit yet, nothing to check"; exit 1; }
  if [ -f "$receipt" ] && grep -q "\"tree\": \"$tree\"" "$receipt"; then
    exit 0
  fi
  echo "push-check: the tests have not passed on this commit. Run: bash ${self#"$root"/}"
  exit 1
fi

[ -s "$cmd_file" ] || { echo "push-check: no test command in ${cmd_file#"$root"/}; run /masthead:setup to write it" >&2; exit 1; }
if [ -n "$(git -C "$root" status --porcelain)" ]; then
  echo "push-check: commit or stash your changes first, so the record names exactly what was tested" >&2
  exit 1
fi
echo "push-check: running the command in ${cmd_file#"$root"/}"
(cd "$root" && bash "$cmd_file") || { echo "push-check: tests failed, nothing recorded" >&2; exit 1; }
mkdir -p "$(dirname "$receipt")"
printf '{"tree": "%s", "when": "%s"}\n' "$tree" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$receipt"
echo "push-check: tests passed on this commit; record written to $STATE_DIR/push-check.json"
