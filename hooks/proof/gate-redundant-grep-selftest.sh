#!/usr/bin/env bash
# Proves gate-redundant-grep refuses only a real search that repeats a fresh
# code index answer, and leaves alone shell commands that are not searches.
#
# Before October 3, 2026 the gate compared the WHOLE shell command against the
# recent index queries, so `mix test`, `git commit` and `date` were refused
# whenever a long word of a query appeared anywhere in them (390 of 682 failed
# calls across the Flyer milestone 1 sessions).
#
#   bash ~/.claude/hooks/proof/gate-redundant-grep-selftest.sh
set -uo pipefail
HOOKS="${GATE_HOOKS_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$HOOKS/engram-protocol.sh" "$HOOKS/shell-search-pattern.py" "$WORK/"

pass=0; fail=0
ok()  { pass=$((pass + 1)); printf 'ok   %-62s %s\n' "$1" "$2"; }
bad() { fail=$((fail + 1)); printf 'FAIL %-62s %s\n' "$1" "$2" >&2; }

# A fresh code_locate answer with hits, recorded through the real marker.
record_search() {
  jq -n --arg s "$1" --arg q "$2" '{session_id:$s,
    tool_name:"mcp__claude_ai_korium__code_locate", tool_input:{query:$q},
    tool_response:[{type:"text", text:({results:[{rel_path:"lib/x.ex",start_line:1,end_line:9}],
      indexed_git_sha:"abc", staleness:{stale:false}} | tojson)}]}' \
    | bash "$WORK/engram-protocol.sh" mark-codesearch >/dev/null 2>&1
}

gate() {
  local out
  out="$(jq -n --arg s "$1" --arg t "$2" --argjson i "$3" \
    '{session_id:$s, tool_name:$t, tool_input:$i}' \
    | bash "$WORK/engram-protocol.sh" gate-redundant-grep 2>/dev/null)"
  if printf '%s' "$out" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1; then
    echo deny
  else
    echo allow
  fi
}

expect() {
  local name="$1" want="$2" sid="$3" tool="$4" input="$5" got
  got="$(gate "$sid" "$tool" "$input")"
  [ "$got" = "$want" ] && ok "$name" "$got" || bad "$name" "want $want, got $got"
}

sid="redundant-selftest-$$"
record_search "$sid" "container_skipped extract job skips a container"

expect "mix test naming a query word is not a search" allow "$sid" Bash \
  '{"command":"mix test test/container_skipped_test.exs"}'
expect "git commit naming a query word is not a search" allow "$sid" Bash \
  '{"command":"git commit -m \"skip the container_skipped case\""}'
expect "gh issue create with a query word in its body" allow "$sid" Bash \
  '{"command":"gh issue create -t \"a container\" -b \"container_skipped\""}'
expect "grep after a pipe reads output, not the tree" allow "$sid" Bash \
  '{"command":"git status | grep container_skipped"}'
expect "rg for the same name as a fresh answer" deny "$sid" Bash \
  '{"command":"rg -n container_skipped products/"}'
expect "the same rg a second time goes through" allow "$sid" Bash \
  '{"command":"rg -n container_skipped products/"}'
expect "cd then rg for the same name" deny "$sid" Bash \
  '{"command":"cd /tmp && rg -n \"extract job skips\" ."}'
expect "rg for an unrelated name" allow "$sid" Bash \
  '{"command":"rg -n fuse_scores products/"}'
expect "Grep tool for the same name" deny "$sid" Grep \
  '{"pattern":"skips a container"}'

rm -rf "${TMPDIR:-/tmp}"/claude-hooks-"$sid"* 2>/dev/null
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
