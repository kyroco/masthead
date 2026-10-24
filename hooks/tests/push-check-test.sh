#!/usr/bin/env bash
# push-check-test.sh: the setup-written push check reads its command from a sibling file, so quotes and $( ) survive,
# and its record names the exact tree the tests passed on.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../../skills/setup/push-check.sh"
pass=0; fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL  $1" >&2; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export GIT_CEILING_DIRECTORIES="$T"
d="$T/repo"; mkdir -p "$d/.claude"
sed 's|__STATE_DIR__|.claude/state|' "$SRC" > "$d/.claude/push-check.sh"
# The command carries double quotes, a $( ) and a dollar sign, none of which may break or expand early.
printf '%s\n' 'mkdir -p .claude/state && echo "ok $(printf x) $HOME" > .claude/state/ran && test "$(cat .claude/state/ran)" = "ok x $HOME"' > "$d/.claude/push-check.cmd"
printf '%s\n' '.claude/state/' > "$d/.gitignore"
( cd "$d" && git init -q . && git config user.email t@t && git config user.name t && echo a > a.txt && git add -A && git commit -qm one ) >/dev/null 2>&1

( cd "$d" && bash .claude/push-check.sh --check >/dev/null 2>&1 ) && bad "--check should fail before any run" || ok
( cd "$d" && bash .claude/push-check.sh >/dev/null 2>&1 ) && ok || bad "a passing command should record the tree"
[ -f "$d/.claude/state/push-check.json" ] && ok || bad "no record written"
[ -f "$d/.claude/state/ran" ] && ok || bad "the command did not run as written"
( cd "$d" && bash .claude/push-check.sh --check >/dev/null 2>&1 ) && ok || bad "--check should pass on the tested tree"
( cd "$d" && echo b > a.txt && git commit -qam two >/dev/null 2>&1 && bash .claude/push-check.sh --check >/dev/null 2>&1 ) && bad "--check should fail on a commit the tests did not run on" || ok
( cd "$d" && git reset -q --hard HEAD~1 && bash .claude/push-check.sh --check >/dev/null 2>&1 ) && ok || bad "--check should pass again on the tested tree"
( cd "$d" && echo b > a.txt && bash .claude/push-check.sh >/dev/null 2>&1 ) && bad "a dirty tree should be refused" || ok
( cd "$d" && git checkout -q a.txt && printf '%s\n' 'false' > .claude/push-check.cmd && git commit -qam cmd >/dev/null 2>&1 && rm -f .claude/state/push-check.json && bash .claude/push-check.sh >/dev/null 2>&1 ) && bad "a failing command should not record" || ok
[ ! -f "$d/.claude/state/push-check.json" ] && ok || bad "a failing command wrote a record"
( cd "$d" && git rm -q .claude/push-check.cmd && git commit -qm nocmd >/dev/null 2>&1 && bash .claude/push-check.sh >/dev/null 2>&1 ) && bad "a missing command file should be refused, not run as empty" || ok

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
