#!/usr/bin/env bash
# Tests for scope-gate.py: the edit check refuses what it claims to refuse and
# stands aside when there is no scope file, and the before-and-after check puts
# back whatever a call did to the protected files, however the command was
# spelled. Bash cases really run, in a throwaway git repository, between the
# hook's two halves, the way Claude Code runs them.
#
# Run from anywhere: bash .claude/hooks/tests/scope-gate-test.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/scope-gate-test.XXXXXX")" && pwd)"
trap 'rm -rf "$T"' EXIT
export TMPDIR="$T/tmp"
unset CLAUDE_PLUGIN_DATA
mkdir -p "$TMPDIR"
# The gate guards its own file, the runner beside it and the user settings.
# A copy in a throwaway user folder is what runs, so these cases
# never touch the real ~/.claude.
U="$T/userconfig"
mkdir -p "$U/hooks"
cp "$HERE/../scope-gate.py" "$U/hooks/scope-gate.py"
cp "$HERE/../project_fact.py" "$U/hooks/project_fact.py"
echo '# runner' > "$U/hooks/run.sh"
echo '{"hooks": {}}' > "$U/settings.json"
export CLAUDE_CONFIG_DIR="$U"
GATE="$U/hooks/scope-gate.py"

pass=0
failures=0
ok() { echo "ok   - $1"; pass=$((pass + 1)); }
bad() { echo "FAIL - $1"; failures=$((failures + 1)); }

run() {
  # $1 = expected (deny|allow), $2 = label, $3 = payload JSON
  out="$(printf '%s' "$3" | python3 "$GATE")"
  if printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then got=deny; else got=allow; fi
  if [ "$got" = "$1" ]; then ok "$2 ($got)"; else bad "$2: expected $1, got $got ${out}"; fi
}
edit() { jq -n --arg p "$1" --arg c "${2:-$R}" '{tool_name: "Edit", tool_input: {file_path: $p}, cwd: $c, session_id: "s", tool_use_id: "e"}'; }
write() { jq -n --arg p "$1" --arg c "${2:-$R}" '{tool_name: "Write", tool_input: {file_path: $p, content: "x"}, cwd: $c, session_id: "s", tool_use_id: "w"}'; }

call() {
  # $1 = expected (restored|untouched), $2 = label, $3 = command, $4 = cwd (default $R)
  # Runs the before half, the command itself, then the after half, and checks
  # that every protected file matches what it held before the call.
  local dir="${4:-$R}" id="c$RANDOM$RANDOM" payload out
  payload="$(jq -n --arg k "$3" --arg c "$dir" --arg id "$id" \
    '{tool_name: "Bash", tool_input: {command: $k}, cwd: $c, session_id: "s", tool_use_id: $id}')"
  printf '%s' "$payload" | python3 "$GATE" >/dev/null
  (cd "$dir" && bash -c "$3") >/dev/null 2>&1
  out="$(printf '%s' "$payload" | python3 "$GATE" post)"
  local intact=yes
  for f in "${WATCH[@]}"; do
    cmp -s "$f" "$T/golden/$(printf '%s' "$f" | shasum | cut -c1-12)" || intact=no
  done
  if [ "$1" = restored ]; then
    printf '%s' "$out" | grep -q '"decision": "block"' && [ "$intact" = yes ] \
      && ok "$2 (restored)" || bad "$2: expected restore, intact=$intact out=$out"
  else
    [ -z "$out" ] && [ "$intact" = yes ] && ok "$2 (untouched)" || bad "$2: expected no change, intact=$intact out=$out"
  fi
}
golden() {
  # Record the files `call` compares against.
  mkdir -p "$T/golden"
  WATCH=("$@")
  for f in "$@"; do cp "$f" "$T/golden/$(printf '%s' "$f" | shasum | cut -c1-12)"; done
}
g() { git -C "$R" -c user.name=t -c user.email=t@example.com "$@" >/dev/null 2>&1; }

# ---------------------------------------------------------------- the checkout
R="$T/repo"
mkdir -p "$R"
git init -q "$R"
mkdir -p "$R/.claude/state" "$R/.claude/hooks" "$R/products/apps/salon_web/lib/deep" "$R/products/apps/engram_core/lib" "$R/docs/ux"
cp "$GATE" "$R/.claude/hooks/scope-gate.py"
echo '{"hooks": {}}' > "$R/.claude/settings.json"
printf '.claude/state/\n' > "$R/.gitignore"
g add -A && g commit -qm init
# Facts are read from the session's own repository, so pin it to this one; its
# settings state no PROJECT_STATE_DIR, so the default folder is in play.
export CLAUDE_PROJECT_DIR="$R"

run allow "no scope file: anything goes"               "$(edit "$R/products/apps/engram_core/lib/a.ex")"
run allow "creating the scope file when absent"       "$(write "$R/.claude/state/scope.json")"

cat > "$R/.claude/state/scope.json" <<'JSON'
{
  "task": "front desk list",
  "allowed_paths": ["products/apps/salon_web/**", "docs/ux/front-desk-*"],
  "forbidden_paths": ["products/apps/salon_web/lib/router.ex"]
}
JSON

# ---------------------------------------------------------------- edit tools
run allow "inside an allowed ** path"                  "$(edit "$R/products/apps/salon_web/lib/deep/a.ex")"
run allow "inside an allowed single-folder glob"       "$(edit "$R/docs/ux/front-desk-lists-ux.md")"
run deny  "* does not cross folders"                   "$(edit "$R/docs/ux/front-desk-old/x.md")"
run deny  "outside every allowed path"                 "$(edit "$R/products/apps/engram_core/lib/a.ex")"
run deny  "forbidden wins over allowed"                "$(edit "$R/products/apps/salon_web/lib/router.ex")"
run allow "relative path resolved against cwd"         "$(edit "lib/deep/b.ex" "$R/products/apps/salon_web")"
run deny  "relative path outside scope"                "$(edit "lib/a.ex" "$R/products/apps/engram_core")"
run deny  "editing the existing scope file"            "$(edit "$R/.claude/state/scope.json")"
run deny  "overwriting the existing scope file"        "$(write "$R/.claude/state/scope.json")"
run allow "a file outside the checkout"                "$(edit "$T/scratch/notes.md")"
run deny  "a top-level name starting with two dots"    "$(write "$R/..notes.md")"
run deny  "edit through a symlink to the scope file"   "$(ln -sfn "$R/.claude/state" "$R/products/apps/salon_web/k" && edit "$R/products/apps/salon_web/k/scope.json")"
run deny  "edit through a symlink to a forbidden file" "$(: > "$R/products/apps/salon_web/lib/router.ex" && ln -sf "$R/products/apps/salon_web/lib/router.ex" "$R/products/apps/salon_web/lib/deep/r.ex" && edit "$R/products/apps/salon_web/lib/deep/r.ex")"
run deny  "forbidden file in other letter case"        "$(edit "$R/products/apps/salon_web/lib/Router.ex")"
run deny  "scope file in other letter case"            "$(write "$R/.claude/state/Scope.json")"
run deny  "edit tool on the gate script"               "$(edit "$R/.claude/hooks/scope-gate.py")"
rm -f "$R/products/apps/salon_web/k" "$R/products/apps/salon_web/lib/deep/r.ex"

# Reviewers write their findings to a gitignored folder in every task; a link out of that
# folder is still the product.
# The link case uses the fully resolved checkout path: under a temp folder that
# is itself a link (/var on macOS), the gate sees two roots, and the second
# refuses for a reason unrelated to the review folder.
mkdir -p "$R/.claude/state/review"
RP="$(cd "$R" && pwd -P)"
run allow "a reviewer's findings file"                 "$(write "$R/.claude/state/review/findings-reviewer-contract.json")"
run deny  "a review folder link into product code"     "$(ln -sfn "$RP/products/apps/engram_core/lib" "$RP/.claude/state/review/lnk" && write "$RP/.claude/state/review/lnk/a.ex")"
run deny  "a review folder link out of the checkout"   "$(mkdir -p "$T/outside" && ln -sfn "$T/outside" "$RP/.claude/state/review/out" && write "$RP/.claude/state/review/out/a.ex")"
run deny  "the scope file beside the review folder"    "$(write "$R/.claude/state/scope.json")"
rm -f "$R/.claude/state/review/lnk" "$R/.claude/state/review/out"
run deny  "a folder named like the review folder"      "$(mkdir -p "$R/.claude/state/reviewx" && write "$R/.claude/state/reviewx/a.ex")"
# The per-commit review is gone, so its folder is no longer exempt.
run deny  "the retired commit review folder"          "$(mkdir -p "$R/.claude/state/commit-review" && write "$R/.claude/state/commit-review/brief.md")"

# A dependency's own .git folder does not hide the checkout's scope.
mkdir -p "$R/products/deps/muex/.git" "$R/products/deps/muex/lib"
run deny  "nested repo inside a scoped checkout"       "$(edit "$R/products/deps/muex/lib/m.ex")"

# ---------------------------------------------------------------- bash, before and after
golden "$R/.claude/state/scope.json" "$R/.claude/hooks/scope-gate.py" "$R/.claude/settings.json"

call restored  "rm the scope file"                     'rm .claude/state/scope.json'
call restored  "rm -rf the scope folder"               'rm -rf .claude/state'
call restored  "git clean of ignored files"            'git clean -fdX'
call restored  "a spelling the old text check missed"  'rm .claude//settings.json'
call restored  "a redirect over the settings"          'echo "{}" > .claude/settings.json'
call restored  "emptying the gate script"              ': > .claude/hooks/scope-gate.py'
call restored  "replacing the settings with a symlink" 'rm .claude/settings.json && ln -s /etc/hosts .claude/settings.json'
call restored  "rm from a subfolder, by relative path" 'rm ../../../.claude/state/scope.json' "$R/products/apps/salon_web"
call restored  "a failing command still gets checked"  'rm .claude/state/scope.json; false'
call untouched "reading the scope file"                'jq . .claude/state/scope.json 2>&1'
call untouched "a read piped to python"                'cat .claude/state/scope.json | python3 -m json.tool'
call untouched "listing hooks with stderr merged"      'ls .claude/hooks 2>&1'
call untouched "the word clean in a message"           'echo "git clean up the docs"'
call untouched "an ordinary product write"             'echo x > products/apps/salon_web/lib/deep/c.ex'

# A hard link made now and written through later is caught at the later call.
call untouched "making a hard link changes nothing yet" 'ln .claude/settings.json products/apps/salon_web/s.json'
payload="$(jq -n --arg p "$R/products/apps/salon_web/s.json" '{tool_name: "Write", tool_input: {file_path: $p}, cwd: "'"$R"'", session_id: "s", tool_use_id: "hl"}')"
printf '%s' "$payload" | python3 "$GATE" >/dev/null
echo '{"hooks": "gone"}' > "$R/products/apps/salon_web/s.json"
out="$(printf '%s' "$payload" | python3 "$GATE" post)"
cmp -s "$R/.claude/settings.json" "$T/golden/$(printf '%s' "$R/.claude/settings.json" | shasum | cut -c1-12)" \
  && printf '%s' "$out" | grep -q '"decision": "block"' && ok "write through a hard link (restored)" \
  || bad "write through a hard link: settings not restored: $out"
rm -f "$R/products/apps/salon_web/s.json"
# Last in this block: it sweeps every untracked file away.
call restored  "git stash --all"                       'git -c user.name=t -c user.email=t@example.com stash push --all -q'

# The user-level files: the settings that wire the gate and the
# runner that calls it sit outside every checkout, and are guarded the same way
# while a scope is set. The gate's own file is not tested here: a command that
# empties the running gate also empties the half that would restore it.
golden "$U/settings.json" "$U/hooks/run.sh"
call restored  "a redirect over the user settings"      "echo '{}' > $U/settings.json"
call restored  "emptying the user-level runner"         ": > $U/hooks/run.sh"
run deny  "an edit to the user settings"               "$(edit "$U/settings.json")"
run deny  "an edit to the user-level gate"             "$(edit "$GATE")"
# The same edit made from outside the repository (cwd /tmp) is still refused:
# the session's own folder has the scope file.
export CLAUDE_PROJECT_DIR="$R"
run deny  "an edit to the user settings from outside the repo" "$(edit "$U/settings.json" "$T/scratch")"
unset CLAUDE_PROJECT_DIR

# A worktree inside the main checkout, as this repo keeps them, is its own
# checkout: the main checkout's scope does not govern it, and its own scope file
# is protected even from a command run in the main checkout.
W="$R/.claude/worktrees/other"
mkdir -p "$W/products" "$R/.git/worktrees/other"
echo "gitdir: $R/.git/worktrees/other" > "$W/.git"
echo "$W/.git" > "$R/.git/worktrees/other/gitdir"
run allow "nested worktree without its own scope"      "$(edit "$W/products/a.ex" "$W")"
mkdir -p "$W/.claude/state" "$W/src"
echo '{"allowed_paths": ["src/**"]}' > "$W/.claude/state/scope.json"
run allow "nested worktree: inside its own scope"      "$(edit "$W/src/a.ex" "$W")"
run deny  "nested worktree: outside its own scope"     "$(edit "$W/README.md" "$W")"
golden "$W/.claude/state/scope.json" "$R/.claude/state/scope.json"
call restored  "main checkout removing a worktree's scope" "rm $W/.claude/state/scope.json"

# Even a scope that allows everything protects the gate and its wiring, unless
# the user names the exact file, and never the scope file itself.
V="$T/wt"
mkdir -p "$V/.claude/state" "$V/src" "$V/.claude/hooks"
echo "gitdir: $R/.git/worktrees/wt" > "$V/.git"
echo '{"hooks": {}}' > "$V/.claude/settings.json"
echo '{"allowed_paths": ["**"], "forbidden_paths": ["src/secret.ex"]}' > "$V/.claude/state/scope.json"
run allow "allow-all scope: an ordinary file"          "$(edit "$V/src/a.ex" "$V")"
run deny  "forbidden file spelled with a long s"       "$(edit "$V/src/ſecret.ex" "$V")"
run deny  "allow-all scope: the gate script"           "$(edit "$V/.claude/hooks/scope-gate.py" "$V")"
run deny  "allow-all scope: the settings file"         "$(edit "$V/.claude/settings.json" "$V")"
echo '{"allowed_paths": ["**", ".claude/settings.json", ".claude/state/scope.json"]}' > "$V/.claude/state/scope.json"
run allow "settings named exactly by the user"           "$(edit "$V/.claude/settings.json" "$V")"
run deny  "naming the scope file does not free it"     "$(edit "$V/.claude/state/scope.json" "$V")"
golden "$V/.claude/state/scope.json"
call untouched "bash change to settings the user named"  'echo "{\"hooks\": 1}" > .claude/settings.json' "$V"

# A folder written with a trailing slash means everything under it.
echo '{"allowed_paths": ["src/"]}' > "$V/.claude/state/scope.json"
run allow "trailing-slash folder covers its files"     "$(edit "$V/src/deeper/a.ex" "$V")"

# A broken scope file is not the same as no scope file.
echo '{"allowed_paths": ["**"], "forbidden_paths": "src/a.ex"}' > "$V/.claude/state/scope.json"
run deny  "forbidden_paths as text, not a list"        "$(edit "$V/src/a.ex" "$V")"
echo '{not json' > "$V/.claude/state/scope.json"
run deny  "unparseable scope file refuses every edit"  "$(edit "$V/src/a.ex" "$V")"
golden "$V/.claude/state/scope.json"
call restored  "unparseable scope file is still protected" 'rm .claude/state/scope.json' "$V"

# THE STATE FOLDER IS THE REPO'S CHOICE. A repo whose settings state
# PROJECT_STATE_DIR keeps its scope file there, and the default path is not read.
K="$T/own-state"
mkdir -p "$K"
git init -q "$K"
mkdir -p "$K/.kyroco" "$K/.claude/state" "$K/src"
echo '{"hooks": {}, "env": {"PROJECT_STATE_DIR": ".kyroco"}}' > "$K/.claude/settings.json"
echo x > "$K/src/a.ex"; echo x > "$K/src/b.ex"
echo '{"allowed_paths": ["src/a.ex"]}' > "$K/.kyroco/scope.json"
echo '{"allowed_paths": ["**"]}' > "$K/.claude/state/scope.json"
git -C "$K" -c user.name=t -c user.email=t@example.com add -A >/dev/null 2>&1
git -C "$K" -c user.name=t -c user.email=t@example.com commit -qm init >/dev/null 2>&1
export CLAUDE_PROJECT_DIR="$K"
run allow "a repo's own state folder: an edit its scope allows"      "$(edit "$K/src/a.ex" "$K")"
run deny  "a repo's own state folder: an edit outside its scope"     "$(edit "$K/src/b.ex" "$K")"
run deny  "a repo's own state folder: its scope file is protected"   "$(edit "$K/.kyroco/scope.json" "$K")"
export CLAUDE_PROJECT_DIR="$R"

# ------------------------------------------------------- private state folder
# Snapshots hold copies of the user's settings and name the paths to write back,
# so the folder must be private, and one that is not ours must not be trusted.
mode_of() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }
SNAP_PAYLOAD="$(jq -n --arg c "$R" '{tool_name: "Bash", tool_input: {command: "true"}, cwd: $c, session_id: "s", tool_use_id: "modes"}')"
umask 022
printf '%s' "$SNAP_PAYLOAD" | python3 "$GATE" >/dev/null
SROOT="$TMPDIR/masthead-$(id -u)"
SSNAP="$(find "$SROOT" -name 's-modes.json' 2>/dev/null | head -1)"
[ -d "$SROOT" ] && [ "$(mode_of "$SROOT")" = 700 ] && ok "state root is mode 700" || bad "state root mode: $(mode_of "$SROOT" 2>&1)"
[ -n "$SSNAP" ] && [ "$(mode_of "$(dirname "$SSNAP")")" = 700 ] && ok "snapshot folder is mode 700" || bad "snapshot folder missing or not 700"
[ -n "$SSNAP" ] && [ "$(mode_of "$SSNAP")" = 600 ] && ok "snapshot file is mode 600" || bad "snapshot file missing or not 600: $SSNAP"
umask 077

# A state root that is a symlink (stands in for a folder someone else made first)
# is refused: a snapshot planted in it must not be written back.
EVIL="$T/evil"; VICTIM="$T/victim"
mkdir -p "$EVIL/scope-gate" "$EVIL/claude-scope-gate" "$VICTIM" "$T/tmp2"
chmod 777 "$EVIL" "$EVIL/scope-gate" "$EVIL/claude-scope-gate"
ln -s "$EVIL" "$T/tmp2/masthead-$(id -u)"
mkdir -p "$T/tmp2/claude-scope-gate"
PLANT="$(jq -n --arg r "$VICTIM" '{($r): {exempt: [], files: {"pwned.txt": ["file", "cHduZWQK"]}}}')"
for d in "$EVIL/scope-gate" "$EVIL/claude-scope-gate" "$T/tmp2/claude-scope-gate"; do printf '%s' "$PLANT" > "$d/s-sym.json"; done
sym_payload="$(jq -n --arg c "$R" '{tool_name: "Bash", tool_input: {command: "true"}, cwd: $c, session_id: "s", tool_use_id: "sym"}')"
out="$(printf '%s' "$sym_payload" | TMPDIR="$T/tmp2" python3 "$GATE" post)"
[ ! -e "$VICTIM/pwned.txt" ] && ok "a snapshot in a symlinked state folder is not written back" \
  || bad "post wrote $VICTIM/pwned.txt from a planted snapshot"
printf '%s' "$sym_payload" | TMPDIR="$T/tmp2" python3 "$GATE" >/dev/null
[ -z "$(find "$EVIL" -name '*.json' -newer "$VICTIM" 2>/dev/null | grep -v 's-sym.json')" ] \
  && ok "the before half writes no snapshot into a symlinked state folder" \
  || bad "the before half wrote a snapshot into the symlinked folder"

echo
echo "$pass passed, $failures failed"
[ "$failures" -eq 0 ]
