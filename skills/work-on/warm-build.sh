#!/usr/bin/env bash
# Build the repo once for a foreman's run, and hand that build to each worker.
#
#   warm-build.sh build          the foreman, from any checkout of the repo
#   warm-build.sh clone <tree>   a worker, from inside its own fresh worktree
#   warm-build.sh end            the foreman, when the run ends
#
# build: runs the command the repo names as PROJECT_WARM_BUILD (the env block
# of the main checkout's .claude/settings.json) in a worktree of its own at
# origin/main, <main checkout>/.claude/worktrees/masthead-warm-<commit>. The
# command's output goes to <tree>.log, never to the screen; <tree>.ready marks
# a finished build. Prints the tree's path. A tree already built for this
# commit is reused. A new tree is first seeded from the newest ready one, so
# the command only rebuilds what changed. A tree is never rebuilt in place,
# because a worker may be cloning it; the two newest are kept and older ones
# removed.
#
# clone: clones the warm tree's build output into this worktree with an APFS
# clone (cp -c), which takes no extra disk until a file changes. What it
# clones is PROJECT_WARM_PATHS (space separated, relative to the top of the
# checkout, globs allowed) or, when the repo names none, every path git
# ignores in the warm tree. Nothing under .claude/ is cloned, and a path this
# worktree already has is kept.
#
# Exit 0: done. Exit 3: nothing to use, so the worker builds cold as before:
# no command named, the tree is not ready, it belongs to another repository,
# it is on another disk, where cp -c would silently fall back to a full copy,
# or (off macOS) the disk cannot clone files at all. Exit 1: the warm-up command failed; the log's last lines are printed.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
fact_py="$here/../../hooks/project_fact.py"
mode="${1:-}"

top="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "not in a git checkout" >&2; exit 3; }
common="$(git rev-parse --path-format=absolute --git-common-dir)"
main="$(dirname "$common")"
warm_dir="$main/.claude/worktrees"

# A fact from the main checkout's settings. Skills run through the Bash tool,
# where Claude Code sets no CLAUDE_PROJECT_DIR, so the checkout this shell is
# in is the session's (project_fact.py --tracker does the same).
fact() { CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$top}" python3 "$fact_py" --root "$top" "$1" 2>/dev/null; }

device() { python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_dev)' "$1"; }

# Whether folder $1 can hold a copy-on-write clone. On macOS cp -c never
# fails (it falls back to a full copy), so the same-disk check is the guard
# there. Elsewhere, try cp --reflink=always on a small file: a disk that cannot
# clone (ext4, for one) refuses it.
can_clone() {
  [ "$(uname)" = Darwin ] && return 0
  local probe="$1/.masthead-clone-probe.$$" rc
  echo probe > "$probe" 2>/dev/null || return 1
  cp --reflink=always "$probe" "$probe.c" 2>/dev/null; rc=$?
  rm -f "$probe" "$probe.c"
  return $rc
}

# Clone build output from tree $1 into tree $2.
clone_into() {
  local from="$1" to="$2" paths p n=0 kept=0 failed=0 t0
  t0="$(date +%s)"
  paths="$(fact PROJECT_WARM_PATHS)"
  if [ -n "$paths" ]; then
    paths="$(cd "$from" && for p in $paths; do [ -e "$p" ] && printf '%s\n' "$p"; done)"
  else
    paths="$(git -C "$from" ls-files --others --ignored --exclude-standard --directory)"
  fi
  while IFS= read -r p; do
    p="${p%/}"
    [ -n "$p" ] || continue
    case "$p" in .claude|.claude/*|/*|*..*) continue ;; esac
    if [ -e "$to/$p" ] || [ -L "$to/$p" ]; then kept=$((kept + 1)); continue; fi
    mkdir -p "$to/$(dirname "$p")"
    if [ "$(uname)" = Darwin ]; then
      cp -Rc "$from/$p" "$to/$p" 2>/dev/null
    else
      cp -R --reflink=always "$from/$p" "$to/$p" 2>/dev/null
    fi
    if [ $? -eq 0 ]; then n=$((n + 1)); else rm -rf "${to:?}/$p"; failed=$((failed + 1)); fi
  done <<< "$paths"
  echo "cloned $n paths from $from in $(( $(date +%s) - t0 )) s; left $kept already there; $failed could not be cloned"
}

case "$mode" in
build)
  cmd="$(fact PROJECT_WARM_BUILD)"
  if [ -z "$cmd" ]; then
    echo "this repo names no PROJECT_WARM_BUILD; workers build cold"
    exit 3
  fi
  git -C "$main" fetch -q origin main 2>/dev/null
  sha="$(git -C "$main" rev-parse --short=12 origin/main 2>/dev/null)" || { echo "no origin/main" >&2; exit 1; }
  tree="$warm_dir/masthead-warm-$sha"
  if [ -f "$tree.ready" ] && [ -d "$tree" ]; then echo "$tree"; exit 0; fi
  # A tree with no marker is a build that failed or was cut short: start it again.
  [ -e "$tree" ] && { git -C "$main" worktree remove --force "$tree" 2>/dev/null || rm -rf "$tree"; }
  rm -f "$tree.log" "$tree.ready"
  mkdir -p "$warm_dir"
  git -C "$main" worktree prune
  git -C "$main" worktree add -q --detach "$tree" "$sha" >/dev/null 2>&1 || { echo "could not make $tree" >&2; exit 1; }
  last="$(ls -t "$warm_dir"/masthead-warm-*.ready 2>/dev/null | head -1)"
  [ -n "$last" ] && [ -d "${last%.ready}" ] && can_clone "$tree" && clone_into "${last%.ready}" "$tree" > "$tree.log"
  if ! ( cd "$tree" && bash -c "$cmd" ) >> "$tree.log" 2>&1; then
    echo "the warm-up command failed; workers build cold. Last lines of $tree.log:" >&2
    tail -20 "$tree.log" >&2
    exit 1
  fi
  touch "$tree.ready"
  # Keep the two newest ready trees; remove the rest.
  ls -t "$warm_dir"/masthead-warm-*.ready 2>/dev/null | tail -n +3 | while IFS= read -r old; do
    git -C "$main" worktree remove --force "${old%.ready}" 2>/dev/null || rm -rf "${old%.ready}"
    rm -f "$old" "${old%.ready}.log"
  done
  git -C "$main" worktree prune
  echo "$tree"
  ;;
clone)
  from="${2:-}"
  [ -n "$from" ] && from="$(cd "$from" 2>/dev/null && pwd -P)"
  if [ -z "$from" ] || [ ! -f "$from.ready" ]; then
    echo "no ready warm tree at ${2:-<none>}; build cold"
    exit 3
  fi
  if [ "$(git -C "$from" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" != "$common" ]; then
    echo "$from is not a worktree of this repository; build cold"
    exit 3
  fi
  if [ "$(device "$from")" != "$(device "$top")" ]; then
    echo "$from is on another disk, where a clone would be a full copy; build cold"
    exit 3
  fi
  if ! can_clone "$top"; then
    echo "this disk cannot clone files, so a copy would cost the full size; build cold"
    exit 3
  fi
  clone_into "$from" "$top"
  ;;
end)
  for r in "$warm_dir"/masthead-warm-*; do
    [ -e "$r" ] || continue
    case "$r" in *.ready|*.log) rm -f "$r"; continue ;; esac
    git -C "$main" worktree remove --force "$r" 2>/dev/null || rm -rf "$r"
  done
  git -C "$main" worktree prune
  echo "removed the warm trees"
  ;;
*)
  echo "usage: warm-build.sh build | clone <warm tree> | end" >&2
  exit 2
  ;;
esac
