#!/usr/bin/env bash
# warm-build-test.sh: the foreman builds one warm tree from the command the repo
# names as PROJECT_WARM_BUILD, and a worker clones its build output into a
# fresh worktree; a repo that names no command, a tree that is not ready, or a
# tree from another repository leaves the worker to build cold.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../../skills/work-on/warm-build.sh"
pass=0; fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL  $1" >&2; }
T="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$T"' EXIT
export GIT_CEILING_DIRECTORIES="$T"
unset CLAUDE_PROJECT_DIR PROJECT_WARM_BUILD PROJECT_WARM_PATHS
g() { git -c user.email=t@t -c user.name=t "$@"; }

# A repo with an origin, a build folder git ignores, and a second ignored folder.
git init -q --bare -b main "$T/origin.git"
d="$T/repo"
g clone -q "$T/origin.git" "$d" 2>/dev/null
mkdir -p "$d/.claude"
printf 'build/\ncache/\n.claude/worktrees/\n.claude/settings.local.json\n' > "$d/.gitignore"
echo a > "$d/a.txt"
( cd "$d" && g add -A && g commit -qm one && g push -q origin HEAD:main ) >/dev/null 2>&1

warm() { ( cd "$1" && bash "$SRC" "${@:2}" ); }

# 1. No command named: the foreman builds nothing and says workers build cold.
out="$(warm "$d" build 2>&1)"; rc=$?
[ "$rc" -eq 3 ] && ok || bad "no PROJECT_WARM_BUILD should exit 3, got $rc: $out"
ls "$d/.claude/worktrees" 2>/dev/null | grep -q masthead-warm && bad "a warm tree was made with no command" || ok

# 2. A command named: one warm tree at origin/main, built, marked ready, its output in a log.
printf '{"env": {"PROJECT_WARM_BUILD": "mkdir -p build cache && echo built >> build/out && echo c > cache/c && echo ran >> %s/runs"}}\n' "$T" > "$d/.claude/settings.json"
w1="$(warm "$d" build 2>/dev/null)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "build should pass, got $rc"
case "$w1" in "$d/.claude/worktrees/masthead-warm-"*) ok ;; *) bad "warm tree not under .claude/worktrees: $w1" ;; esac
[ -f "$w1/build/out" ] && ok || bad "the command did not run in the warm tree"
[ -f "$w1.ready" ] && ok || bad "no ready marker beside the warm tree"
[ -f "$w1.log" ] && ok || bad "no log beside the warm tree"
[ "$(git -C "$w1" rev-parse HEAD)" = "$(git -C "$d" rev-parse origin/main)" ] && ok || bad "warm tree is not at origin/main"

# 3. Asked again with main unchanged, it reuses the tree and runs nothing.
w1b="$(warm "$d" build 2>/dev/null)"
[ "$w1b" = "$w1" ] && ok || bad "same main should reuse the same tree"
[ "$(wc -l < "$T/runs" | tr -d ' ')" = 1 ] && ok || bad "the command ran again for an unchanged main"

# 4. A worker's worktree clones every ignored path from the warm tree.
( cd "$d" && g worktree add -q --detach "$d/.claude/worktrees/w1" HEAD ) >/dev/null 2>&1
wt="$d/.claude/worktrees/w1"
out="$(warm "$wt" clone "$w1" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "clone should pass, got $rc: $out"
[ "$(cat "$wt/build/out" 2>/dev/null)" = built ] && ok || bad "build/ was not cloned"
[ -f "$wt/cache/c" ] && ok || bad "cache/ was not cloned"
[ -z "$(git -C "$wt" status --porcelain)" ] && ok || bad "the clone left the worktree dirty"

# 5. A path the worktree already has is kept, never overwritten.
( cd "$d" && g worktree add -q --detach "$d/.claude/worktrees/w2" HEAD ) >/dev/null 2>&1
wt2="$d/.claude/worktrees/w2"
mkdir -p "$wt2/build" && echo mine > "$wt2/build/out"
warm "$wt2" clone "$w1" >/dev/null 2>&1
[ "$(cat "$wt2/build/out")" = mine ] && ok || bad "a path the worktree already had was overwritten"
[ -f "$wt2/cache/c" ] && ok || bad "the other paths should still be cloned"

# 6. PROJECT_WARM_PATHS narrows what is cloned.
printf '{"env": {"PROJECT_WARM_BUILD": "mkdir -p build cache && echo built >> build/out && echo c > cache/c && echo ran >> %s/runs", "PROJECT_WARM_PATHS": "build"}}\n' "$T" > "$d/.claude/settings.json"
( cd "$d" && g worktree add -q --detach "$d/.claude/worktrees/w3" HEAD ) >/dev/null 2>&1
wt3="$d/.claude/worktrees/w3"
warm "$wt3" clone "$w1" >/dev/null 2>&1
[ -f "$wt3/build/out" ] && ok || bad "a named path was not cloned"
[ ! -e "$wt3/cache" ] && ok || bad "a path not named was cloned"

# 7. A tree with no ready marker is not cloned: the worker builds cold.
mv "$w1.ready" "$w1.ready.off"
( cd "$d" && g worktree add -q --detach "$d/.claude/worktrees/w4" HEAD ) >/dev/null 2>&1
out="$(warm "$d/.claude/worktrees/w4" clone "$w1" 2>&1)"; rc=$?
[ "$rc" -eq 3 ] && ok || bad "a tree that is not ready should exit 3, got $rc: $out"
[ ! -e "$d/.claude/worktrees/w4/build" ] && ok || bad "a tree that is not ready was cloned"
mv "$w1.ready.off" "$w1.ready"

# 8. A warm tree from another repository is refused.
o="$T/other"; g init -q "$o"; mkdir -p "$o/build"; echo x > "$o/build/out"; touch "$o.ready"
out="$(warm "$d/.claude/worktrees/w4" clone "$o" 2>&1)"; rc=$?
[ "$rc" -eq 3 ] && ok || bad "a tree from another repository should exit 3, got $rc: $out"
[ ! -e "$d/.claude/worktrees/w4/build" ] && ok || bad "a tree from another repository was cloned"

# 9. Nothing under .claude/ is ever cloned, even when git ignores it.
mkdir -p "$w1/.claude" && echo '{}' > "$w1/.claude/settings.local.json"
printf '{"env": {"PROJECT_WARM_BUILD": "mkdir -p build cache && echo built >> build/out && echo c > cache/c && echo ran >> %s/runs"}}\n' "$T" > "$d/.claude/settings.json"
warm "$d/.claude/worktrees/w4" clone "$w1" >/dev/null 2>&1
[ ! -e "$d/.claude/worktrees/w4/.claude/settings.local.json" ] && ok || bad "a file under .claude/ was cloned"
[ -f "$d/.claude/worktrees/w4/build/out" ] && ok || bad "build/ should be cloned beside the skipped .claude file"

# 10. Main moves: a new tree, seeded from the last one, so the command finds the old output.
echo b > "$d/a.txt"; ( cd "$d" && g commit -qam two && g push -q origin HEAD:main ) >/dev/null 2>&1
w2="$(warm "$d" build 2>/dev/null)"; rc=$?
[ "$rc" -eq 0 ] && [ "$w2" != "$w1" ] && ok || bad "a moved main should make a new tree, got $rc $w2"
[ "$(wc -l < "$w2/build/out" | tr -d ' ')" = 2 ] && ok || bad "the new tree was not seeded from the last one"
[ -d "$w1" ] && ok || bad "the previous tree should be kept while workers may still clone it"

# 11. A third tree removes the oldest, keeping two.
echo c > "$d/a.txt"; ( cd "$d" && g commit -qam three && g push -q origin HEAD:main ) >/dev/null 2>&1
w3="$(warm "$d" build 2>/dev/null)"
[ ! -e "$w1" ] && [ ! -e "$w1.ready" ] && [ ! -e "$w1.log" ] && ok || bad "the oldest tree was not removed"
[ -d "$w2" ] && [ -d "$w3" ] && ok || bad "the two newest trees should stay"
git -C "$d" worktree list | grep -q "$w1" && bad "git still lists the removed tree" || ok

# 12. A failing command leaves no ready marker and exits 1.
echo d > "$d/a.txt"; ( cd "$d" && g commit -qam four && g push -q origin HEAD:main ) >/dev/null 2>&1
printf '{"env": {"PROJECT_WARM_BUILD": "echo broken; exit 7"}}\n' > "$d/.claude/settings.json"
out="$(warm "$d" build 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && ok || bad "a failing command should exit 1, got $rc"
printf '%s' "$out" | grep -q broken && ok || bad "a failure should show the log's last lines"
ls "$d/.claude/worktrees/" | grep -q "masthead-warm-$(git -C "$d" rev-parse --short=12 origin/main).ready" && bad "a failed build was marked ready" || ok

# 13. end removes every warm tree.
warm "$d" end >/dev/null 2>&1
ls "$d/.claude/worktrees/" | grep -q masthead-warm && bad "end left a warm tree" || ok
git -C "$d" worktree list | grep -q masthead-warm && bad "git still lists a warm tree after end" || ok

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
