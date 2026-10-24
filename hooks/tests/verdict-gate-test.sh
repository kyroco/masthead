#!/usr/bin/env bash
# Test for hooks/verdict-discipline.sh. Proves the gate BLOCKS what it claims to
# block, and skips only what it claims to skip. Self-contained: builds throwaway git
# repos under a temp dir, runs the gate inside them, asserts the exit code.
#
# Run from anywhere: bash .claude/hooks/tests/verdict-gate-test.sh
# Requires bash 3.2+, git, awk, grep (the gate's own requirement set).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GATE="$HERE/../verdict-gate.sh"
TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/verdict-discipline-test.XXXXXX")"
trap 'rm -rf "$TMPROOT"' EXIT

pass=0
failures=0

new_repo() {
  # $1 = case name; echoes the repo path
  repo="$TMPROOT/$1"
  mkdir -p "$repo"
  git -C "$repo" init -q
  git -C "$repo" config user.email t@example.com
  git -C "$repo" config user.name t
  printf 'seed\n' > "$repo/seed.txt"
  git -C "$repo" add -A
  git -C "$repo" commit -qm seed
  echo "$repo"
}

# assert_exit <expected> <label> <cwd> [env assignments...]
assert_exit() {
  expected="$1"; label="$2"; cwd="$3"; shift 3
  ( cd "$cwd" && env "$@" bash "$GATE" ) >/dev/null 2>&1
  actual=$?
  if [ "$actual" -eq "$expected" ]; then
    echo "ok   - $label (exit $actual)"
    pass=$((pass + 1))
  else
    echo "FAIL - $label: expected exit $expected, got $actual"
    failures=$((failures + 1))
  fi
}

good_case_file() {
  cat > "$1" <<'MD'
# Case file

## Evidence
1. Reproduced the 500 on POST /orders with an empty cart.
2. Traced the same failure in the worker retry path.

## Verdict
Null cart total dereferenced at lib/orders/checkout.ex:142.
MD
}

# 1. out of domain: no case file changed -> skip
repo="$(new_repo no-case-file)"
printf 'unrelated\n' > "$repo/README.md"
assert_exit 0 "no case file changed skips" "$repo"

# 2. compliant case file -> pass
repo="$(new_repo good)"
good_case_file "$repo/last-case-file.md"
assert_exit 0 "two observations plus a file:line verdict passes" "$repo"

# 3. one observation -> BLOCK
repo="$(new_repo one-observation)"
cat > "$repo/last-case-file.md" <<'MD'
## Evidence
1. Reproduced the 500 on POST /orders with an empty cart.

## Verdict
Null cart total dereferenced at lib/orders/checkout.ex:142.
MD
assert_exit 2 "one numbered observation blocks" "$repo"

# 4. verdict with no file:line -> BLOCK
repo="$(new_repo unlocated-verdict)"
cat > "$repo/last-case-file.md" <<'MD'
## Evidence
1. Reproduced the 500 on POST /orders with an empty cart.
2. Traced the same failure in the worker retry path.

## Verdict
Something in the checkout code dereferences a null total.
MD
assert_exit 2 "verdict without a file:line blocks" "$repo"

# 5. no Verdict section at all -> BLOCK (fail closed, not silently pass)
repo="$(new_repo no-verdict-section)"
cat > "$repo/last-case-file.md" <<'MD'
## Evidence
1. Reproduced the 500 on POST /orders with an empty cart.
2. Traced the same failure in the worker retry path.
MD
assert_exit 2 "missing Verdict section blocks" "$repo"

# 6. run from a SUBDIRECTORY: the gate must still find and judge the case file.
#    (The pre-fix gate resolved git-root-relative paths against cwd and silently
#    skipped here, which was a fail-open.)
repo="$(new_repo subdir-cwd)"
mkdir -p "$repo/apps/web"
cat > "$repo/last-case-file.md" <<'MD'
## Evidence
1. Only one observation.

## Verdict
Nothing located.
MD
assert_exit 2 "bad case file still blocks when run from a subdirectory" "$repo/apps/web"

# 7. deleted case file -> out of domain, skip
repo="$(new_repo deleted)"
good_case_file "$repo/last-case-file.md"
git -C "$repo" add -A
git -C "$repo" commit -qm "add case file"
rm "$repo/last-case-file.md"
assert_exit 0 "deleted case file skips" "$repo"

# 8. custom case-file path via CASE_FILE_GLOB
repo="$(new_repo custom-glob)"
mkdir -p "$repo/docs"
cat > "$repo/docs/hunt.md" <<'MD'
## Evidence
1. Only one observation.

## Verdict
lib/x.ex:9 something.
MD
assert_exit 2 "CASE_FILE_GLOB path is gated" "$repo" CASE_FILE_GLOB=docs/hunt.md

# 9. the retired RADIA_CASE_GLOB alias is ignored, so only the default glob is read
assert_exit 0 "retired RADIA_CASE_GLOB alias is ignored" "$repo" RADIA_CASE_GLOB=docs/hunt.md

# 10 and 11. A tree that is genuinely OUTSIDE any git repository.
#
# GIT_CEILING_DIRECTORIES is load bearing. These cases used a plain mktemp
# directory and assumed it sat outside a repository, which is true when TMPDIR is
# /var/folders and false in a CI lane, where TMPDIR is inside the checkout. There
# git walked up, found the enclosing repository, and read ITS changed files, so
# "no case file" saw one and case 11 failed on the lane and nowhere else.
# Measured 2026-09-13 by running this file with TMPDIR set inside the worktree.
CEILING="$TMPROOT"

# 10. non-git tree with a bad case file -> BLOCK (no delta-scope, but not fail-open)
nogit="$TMPROOT/nogit"
mkdir -p "$nogit"
cat > "$nogit/last-case-file.md" <<'MD'
## Evidence
1. Only one observation.

## Verdict
Nothing located.
MD
assert_exit 2 "non-git tree with a bad case file blocks" "$nogit" GIT_CEILING_DIRECTORIES="$CEILING"

# 11. non-git tree with no case file -> skip
mkdir -p "$TMPROOT/nogit-empty"
assert_exit 0 "non-git tree with no case file skips" "$TMPROOT/nogit-empty" GIT_CEILING_DIRECTORIES="$CEILING"

echo
echo "$pass passed, $failures failed"
[ "$failures" -eq 0 ] || exit 1
