#!/usr/bin/env bash
# Proves mark-grep records shell searches and ignores non-searches.
HOOK="${GATE_HOOKS_DIR:-$(cd "$(dirname "$0")/.." && pwd)}/engram-protocol.sh"
pass=0; fail=0
run() { # name, expect(yes|no), command
  sid="mgtest-$RANDOM$RANDOM"
  d="${TMPDIR:-/tmp}/claude-engram/$sid"; mkdir -p "$d"
  printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":%s}}' \
    "$sid" "$(printf '%s' "$3" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    | bash "$HOOK" mark-grep >/dev/null 2>&1
  got=no; [ -s "$d/greps.tsv" ] && got=yes
  if [ "$got" = "$2" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "  FAIL: $1 (expected $2, got $got)"; fi
  rm -rf "$d"
}
echo "== should RECORD =="
run "plain grep"        yes 'grep -rn "defp fuse" products/'
run "piped grep"        yes 'cat x.ex | grep foo'
run "rg"                yes 'rg "Engram.Repo" products/'
run "find"              yes 'find . -name "*.ex"'
run "grep after &&"     yes 'cd /tmp && grep -n foo bar.ex'
# shellcheck disable=SC2016 # the command is data, not run here
run "grep in subshell"  yes 'echo $(grep -c foo bar.ex)'
echo "== should IGNORE =="
run "ls"                no  'ls -la .claude/hooks/'
run "git log"           no  'git log --oneline -20'
run "grep as filename"  no  'cat notes-about-grep.md'
run "grep in message"   no  'git commit -m "use grep here"'
run "aws cli"           no  'aws ecs describe-services --cluster engram-prod'
echo; echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
