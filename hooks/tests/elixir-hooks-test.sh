#!/usr/bin/env bash
# Tests for elixir-toolchain-env.sh and elixir-format-after-edit.sh.
#
# Both run against stand-ins, so the result is the same on any machine: each
# hook's toolchain file puts a stub `mix` first on PATH. The stub records every
# call and behaves as STUB_FORMAT and STUB_CREDO say. A live check that Claude
# Code applies the environment file to later Bash commands, after a `cd`, and in
# a subagent was run on 2026-09-13 with `claude -p` and is recorded in the PR;
# it needs a real session, so it is not repeated here.
#
# Run from anywhere: bash .claude/hooks/tests/elixir-hooks-test.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENVHOOK="$HERE/../elixir-toolchain-env.sh"
FMT="$HERE/../elixir-format-after-edit.sh"
# cd + pwd normalizes the path (TMPDIR often ends in a slash), so the paths the
# stub records and the paths this test expects are spelled the same way.
T="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/elixir-hooks-test.XXXXXX")" && pwd)"
trap 'rm -rf "$T"' EXIT

pass=0
failures=0
ok() { echo "ok   - $1"; pass=$((pass + 1)); }
bad() { echo "FAIL - $1"; failures=$((failures + 1)); }

# ---------------------------------------------------------------- the stub mix
mkdir -p "$T/bin"
cat > "$T/bin/mix" <<'STUB'
#!/usr/bin/env bash
echo "$(pwd) $*" >> "$STUB_LOG"
case "$1" in
  format)
    case "${STUB_FORMAT:-ok}" in
      rewrite) echo "# formatted" >> "$2" ;;
      syntax) echo "** (SyntaxError) lib/a.ex:3: unexpected token: end" >&2; exit 1 ;;
      # A syntax error prints the source around it; this line of product code
      # happens to contain words from a missing-deps message.
      snippet) printf '%s\n' '** (SyntaxError) invalid syntax found on lib/a.ex:3:' \
                 '    error: unexpected token: )' '    │' \
                 '  3 │   raise("account could not be found"))' >&2; exit 1 ;;
      nodeps) echo "** (Mix) Unknown dependency :phoenix given to :import_deps" >&2; exit 1 ;;
      stale) printf '%s\n' 'Unchecked dependencies for environment dev:' \
               '* muex (Hex package)' '  the dependency does not match the requirement' \
               "** (Mix) Can't continue due to errors on dependencies" >&2; exit 1 ;;
    esac ;;
  credo)
    case "${STUB_CREDO:-ok}" in
      issues) echo "┃ [R] ↗ Modules should have a @moduledoc tag." ; echo "    lib/a.ex:1:11 #(X)"; exit 4 ;;
      nodeps) echo '** (Mix) The task "credo" could not be found' >&2; exit 1 ;;
    esac ;;
esac
exit 0
STUB
chmod +x "$T/bin/mix"
printf 'export PATH="%s:$PATH"\n' "$T/bin" > "$T/stub-toolchain.env"
export STUB_LOG="$T/mix.log"

# ---------------------------------------------------------------- environment hook
# A checkout that names a toolchain in its settings (Kyroco) and one that names
# none (any other repo). The facts live in each checkout's .claude/settings.json
# env, read by project_fact.py beside the hooks.
mkdir -p "$T/ours/.git" "$T/ours/.claude" "$T/ours/products" "$T/theirs/.git"

envhook() {
  # $1 = env file ("" for unset), $2 = cwd, $3 = the toolchain file ours names.
  # The session is ours. The same fact is also put in this process's
  # environment, to prove a checkout that names none is not given it from there.
  jq -n --arg t "$3" '{env: {PROJECT_TOOLCHAIN_ENV: $t}}' > "$T/ours/.claude/settings.json"
  jq -n --arg c "$2" '{hook_event_name: "SessionStart", cwd: $c}' \
    | env -u CLAUDE_ENV_FILE CLAUDE_PROJECT_DIR="$T/ours" ${1:+CLAUDE_ENV_FILE="$1"} PROJECT_TOOLCHAIN_ENV="$3" bash "$ENVHOOK"
}

E="$T/env-ours"
out="$(envhook "$E" "$T/ours/products" "$T/stub-toolchain.env")"
[ -z "$out" ] && ok "env: prints nothing" || bad "env: printed: $out"
got="$(env -i HOME="$HOME" PATH="/usr/bin:/bin" bash -c ". \"$E\" && command -v mix")"
[ "$got" = "$T/bin/mix" ] && ok "env: a later command resolves the pinned mix" \
  || bad "env: later command resolved '$got', not $T/bin/mix"
envhook "$E" "$T/ours/products" "$T/stub-toolchain.env" >/dev/null
[ "$(grep -c . "$E")" = 1 ] && ok "env: running again adds no second line" || bad "env: lines: $(cat "$E")"

E="$T/env-theirs"
envhook "$E" "$T/theirs" "$T/stub-toolchain.env" >/dev/null
[ ! -s "$E" ] && ok "env: a repo that names no toolchain is left alone" || bad "env: wrote into another repo's session: $(cat "$E")"

# A clone the session changes into that DOES name a toolchain file: its file is
# not sourced, because a fact names code to run and only the session's own
# repository is trusted.
mkdir -p "$T/clone/.git" "$T/clone/.claude"
echo 'echo pwned' > "$T/clone/evil.env"
jq -n --arg t "$T/clone/evil.env" '{env: {PROJECT_TOOLCHAIN_ENV: $t}}' > "$T/clone/.claude/settings.json"
E="$T/env-clone"
envhook "$E" "$T/clone" "$T/stub-toolchain.env" >/dev/null
[ ! -s "$E" ] && ok "env: a clone outside the session's repo is not sourced" \
  || bad "env: sourced a file a stranger's settings named: $(cat "$E")"

E="$T/env-none"
envhook "$E" "$T/ours" "$T/absent.env" >/dev/null
[ ! -s "$E" ] && ok "env: no toolchain file, nothing written" || bad "env: wrote without a toolchain: $(cat "$E")"

# A worktree whose own settings name no toolchain (a branch cut before the repo
# stated its facts) takes its main checkout's. The main's settings file is left
# uncommitted, so the worktree has none of its own.
git init -q "$T/main"
( cd "$T/main" && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m base \
    && git worktree add -q "$T/wt" -b old ) >/dev/null 2>&1
mkdir -p "$T/main/.claude"
jq -n --arg t "$T/stub-toolchain.env" '{env: {PROJECT_TOOLCHAIN_ENV: $t}}' > "$T/main/.claude/settings.json"
E="$T/env-wt"
jq -n --arg c "$T/wt" '{hook_event_name: "SessionStart", cwd: $c}' \
  | env CLAUDE_PROJECT_DIR="$T/main" CLAUDE_ENV_FILE="$E" bash "$ENVHOOK"
[ -f "$T/wt/.git" ] && grep -q "stub-toolchain.env" "$E" 2>/dev/null \
  && ok "env: a worktree with no facts of its own takes its main checkout's" \
  || bad "env: the worktree was not pinned from its main checkout: $(cat "$E" 2>/dev/null)"

# A stranger folder with a planted .git file naming that worktree's record, and
# settings naming a file of its own. The record points back only at the real
# worktree, so the folder is not the session's repository and nothing is sourced.
mkdir -p "$T/planted/.claude"
cp "$T/wt/.git" "$T/planted/.git"
echo 'echo pwned' > "$T/planted/evil.env"
jq -n --arg t "$T/planted/evil.env" '{env: {PROJECT_TOOLCHAIN_ENV: $t}}' > "$T/planted/.claude/settings.json"
E="$T/env-planted"
jq -n --arg c "$T/planted" '{hook_event_name: "CwdChanged", cwd: $c}' \
  | env CLAUDE_PROJECT_DIR="$T/main" CLAUDE_ENV_FILE="$E" bash "$ENVHOOK"
[ ! -s "$E" ] && ok "env: a planted .git file does not make a folder part of the session's repo" \
  || bad "env: sourced a file named by a folder with a planted .git: $(cat "$E")"

# A worktree of a hostile branch: its own settings name a script inside the
# worktree. A worktree's working tree is branch content, so it supplies no fact
# of its own, and a toolchain path that lands inside the worktree is not loaded.
( cd "$T/main" && git worktree add -q "$T/wt-hostile" -b hostile ) >/dev/null 2>&1
mkdir -p "$T/wt-hostile/.claude"
echo 'echo pwned' > "$T/wt-hostile/evil.env"
jq -n --arg t "$T/wt-hostile/evil.env" '{env: {PROJECT_TOOLCHAIN_ENV: $t}}' > "$T/wt-hostile/.claude/settings.json"
E="$T/env-hostile"
jq -n --arg c "$T/wt-hostile" '{hook_event_name: "CwdChanged", cwd: $c}' \
  | env CLAUDE_PROJECT_DIR="$T/main" CLAUDE_ENV_FILE="$E" bash "$ENVHOOK"
grep -q "evil.env" "$E" 2>/dev/null \
  && bad "env: a worktree's own settings got a script from its branch sourced" \
  || ok "env: a worktree's own settings never name the toolchain the hook loads"
got="$(env CLAUDE_PROJECT_DIR="$T/main" python3 "$HERE/../project_fact.py" --root "$T/wt-hostile" PROJECT_TOOLCHAIN_ENV 2>/dev/null)"
case "$got" in *evil.env*) bad "fact: a worktree's own settings answered a fact: $got" ;; *) ok "fact: a worktree's own settings answer no fact" ;; esac
# The main checkout's fact may be relative; in a worktree it would resolve to
# branch content, so the hook leaves it alone there.
jq -n '{env: {PROJECT_TOOLCHAIN_ENV: "tools/env.sh"}}' > "$T/main/.claude/settings.json"
mkdir -p "$T/wt-hostile/tools" && echo 'echo pwned' > "$T/wt-hostile/tools/env.sh"
E="$T/env-hostile-rel"
jq -n --arg c "$T/wt-hostile" '{hook_event_name: "CwdChanged", cwd: $c}' \
  | env CLAUDE_PROJECT_DIR="$T/main" CLAUDE_ENV_FILE="$E" bash "$ENVHOOK"
grep -q "tools/env.sh" "$E" 2>/dev/null \
  && bad "env: a relative toolchain path was loaded from a worktree's branch content" \
  || ok "env: a toolchain path inside a worktree is not loaded"
jq -n --arg t "$T/stub-toolchain.env" '{env: {PROJECT_TOOLCHAIN_ENV: $t}}' > "$T/main/.claude/settings.json"

# The same stranger folder with .git as a symlink to the real worktree's .git.
rm -f "$T/planted/.git"
ln -s "$T/wt/.git" "$T/planted/.git"
E="$T/env-linked"
jq -n --arg c "$T/planted" '{hook_event_name: "CwdChanged", cwd: $c}' \
  | env CLAUDE_PROJECT_DIR="$T/main" CLAUDE_ENV_FILE="$E" bash "$ENVHOOK"
[ ! -s "$E" ] && ok "env: a symlinked .git does not make a folder part of the session's repo" \
  || bad "env: sourced a file named by a folder whose .git is a symlink: $(cat "$E")"

# A session started in a subfolder of its checkout is still that checkout's.
mkdir -p "$T/main/products"
E="$T/env-sub"
jq -n --arg c "$T/main" '{hook_event_name: "SessionStart", cwd: $c}' \
  | env CLAUDE_PROJECT_DIR="$T/main/products" CLAUDE_ENV_FILE="$E" bash "$ENVHOOK"
grep -q "stub-toolchain.env" "$E" 2>/dev/null && ok "env: a session started in a subfolder still gets the pin" \
  || bad "env: a session started in a subfolder lost the pin: $(cat "$E" 2>/dev/null)"

out="$(envhook "" "$T/ours" "$T/stub-toolchain.env")"
[ -z "$out" ] && ok "env: no CLAUDE_ENV_FILE, stands aside" || bad "env: printed without an env file: $out"

# ---------------------------------------------------------------- format hook
# A Kyroco-shaped checkout: an umbrella under products/, credo, and the
# toolchain named in its settings. The Elixir root is found, not named.
mkdir -p "$T/repo/products/apps/x/lib" "$T/repo/products/apps/x/assets" "$T/repo/.claude"
git init -q "$T/repo"
: > "$T/repo/products/mix.exs"
: > "$T/repo/products/.formatter.exs"
: > "$T/repo/products/.credo.exs"
jq -n --arg t "$T/stub-toolchain.env" '{env: {PROJECT_TOOLCHAIN_ENV: $t}}' > "$T/repo/.claude/settings.json"

fmt() {
  # $1 = file, then env assignments; prints the hook's stdout. SESSION names the
  # session, so the once-per-session notice can be tested; its marker lands in $T.
  f="$1"; shift
  jq -n --arg p "$f" --arg s "${SESSION:-s1}" '{tool_name: "Edit", tool_input: {file_path: $p}, session_id: $s}' \
    | env CLAUDE_PROJECT_DIR="$T/repo" TMPDIR="$T" "$@" bash "$FMT"
}
expect() {
  # $1 = label, $2 = what (silent|block|context), $3 = output
  case "$2" in
    silent) [ -z "$3" ] && ok "format: $1" || bad "format: $1: expected no output, got: $3" ;;
    block) printf '%s' "$3" | grep -q '"decision": "block"' && ok "format: $1" || bad "format: $1: expected a block, got: $3" ;;
    context) printf '%s' "$3" | grep -q '"additionalContext"' && ! printf '%s' "$3" | grep -q '"decision"' \
               && ok "format: $1" || bad "format: $1: expected context only, got: $3" ;;
  esac
}

src="$T/repo/products/apps/x/lib/a.ex"
echo 'defmodule A do end' > "$src"

: > "$STUB_LOG"
expect "clean file says nothing" silent "$(fmt "$src")"
grep -q "^$T/repo/products format $src" "$STUB_LOG" && ok "format: runs from the products root on the one file" \
  || bad "format: wrong directory or target: $(cat "$STUB_LOG")"
grep -q "credo --strict $src" "$STUB_LOG" && ok "format: runs credo --strict on the one file" \
  || bad "format: credo not run on the file: $(cat "$STUB_LOG")"

expect "rewritten file asks for a re-read" context "$(fmt "$src" STUB_FORMAT=rewrite)"
expect "syntax error comes back as feedback" block "$(fmt "$src" STUB_FORMAT=syntax)"
SESSION=s5
out="$(fmt "$src" STUB_FORMAT=snippet)"
expect "syntax error quoting 'could not be found' is still a syntax error" block "$out"
expect "and it does not use up the missing-deps notice" context "$(fmt "$src" STUB_FORMAT=nodeps)"
SESSION=s1
expect "credo issues come back as feedback" block "$(fmt "$src" STUB_CREDO=issues)"
SESSION=s2
expect "unfetched deps: said once" context "$(fmt "$src" STUB_FORMAT=nodeps)"
expect "unfetched deps: then silent" silent "$(fmt "$src" STUB_FORMAT=nodeps)"
SESSION=s6
expect "deps behind mix.lock: said once" context "$(fmt "$src" STUB_FORMAT=stale)"
SESSION=s3
expect "missing credo task: said once" context "$(fmt "$src" STUB_CREDO=nodeps)"
expect "missing credo task: then silent" silent "$(fmt "$src" STUB_CREDO=nodeps)"
out="$(fmt "$src" STUB_FORMAT=rewrite STUB_CREDO=nodeps)"
expect "missing credo after a rewrite keeps the re-read note" context "$out"
[ "$(printf '%s' "$out" | jq -s length)" = 1 ] && ok "format: one JSON object, not two" \
  || bad "format: printed more than one JSON object: $out"
SESSION=s4
out="$(fmt "$src" STUB_FORMAT=rewrite STUB_CREDO=nodeps)"
printf '%s' "$out" | grep -q 'Re-read' && printf '%s' "$out" | grep -q 'not running' \
  && ok "format: first skip carries both the note and the notice" || bad "format: first skip lost a message: $out"
SESSION=s1

# Credo lints only what .credo.exs includes and does not exclude; the rest is
# formatted only.
mkdir -p "$T/repo/products/apps/x/priv/repo/migrations" "$T/repo/products/config" \
  "$T/repo/products/apps/x/test/fixtures/lib"
for f in apps/x/priv/repo/migrations/1_add.exs config/config.exs apps/x/test/fixtures/lib/bad.ex; do
  echo 'x' > "$T/repo/products/$f"
  : > "$STUB_LOG"
  expect "$f is formatted" silent "$(fmt "$T/repo/products/$f" STUB_CREDO=issues)"
  grep -q credo "$STUB_LOG" && bad "format: credo ran on $f" || ok "format: no credo on $f"
done
echo 'x' > "$T/repo/products/apps/x/test/a_test.exs"
expect "a test file is linted" block "$(fmt "$T/repo/products/apps/x/test/a_test.exs" STUB_CREDO=issues)"

heex="$T/repo/products/apps/x/lib/a.html.heex"
echo '<div></div>' > "$heex"
: > "$STUB_LOG"
expect "heex is formatted, not linted" silent "$(fmt "$heex")"
grep -q credo "$STUB_LOG" && bad "format: credo ran on a heex file" || ok "format: no credo on heex"

other="$T/repo/products/apps/x/assets/app.js"
echo 'x' > "$other"
: > "$STUB_LOG"
expect "non-Elixir file is ignored" silent "$(fmt "$other")"
[ -s "$STUB_LOG" ] && bad "format: mix ran for a non-Elixir file" || ok "format: mix never ran for it"

outside="$T/elsewhere/lib/b.ex"
mkdir -p "$(dirname "$outside")"; echo 'x' > "$outside"
expect "Elixir outside any checkout is ignored" silent "$(fmt "$outside")"

stray="$T/repo/tools/b.ex"
mkdir -p "$(dirname "$stray")"; echo 'x' > "$stray"
: > "$STUB_LOG"
expect "Elixir in the checkout but outside the mix project is ignored" silent "$(fmt "$stray")"
[ -s "$STUB_LOG" ] && bad "format: mix ran outside the mix project" || ok "format: mix never ran for it"

# An edit in a checkout that is not the session's repository runs no mix at all:
# mix format reads that checkout's own mix.exs and .formatter.exs.
: > "$STUB_LOG"
expect "an edit outside the session's repo is left alone" silent "$(fmt "$src" CLAUDE_PROJECT_DIR="$T/ours")"
[ -s "$STUB_LOG" ] && bad "format: mix ran in a checkout outside the session's repo" \
  || ok "format: mix never ran outside the session's repo"

# A Vitalaize-shaped checkout: mix.exs at the top, no settings, no credo. The
# stub toolchain is on PATH directly, since this repo names none.
mkdir -p "$T/vit/lib"
git init -q "$T/vit"
: > "$T/vit/mix.exs"
: > "$T/vit/.formatter.exs"
echo 'defmodule V do end' > "$T/vit/lib/v.ex"
: > "$STUB_LOG"
expect "a repo with mix.exs at the top is formatted" silent "$(fmt "$T/vit/lib/v.ex" CLAUDE_PROJECT_DIR="$T/vit" PATH="$T/bin:$PATH")"
grep -q "^$T/vit format $T/vit/lib/v.ex" "$STUB_LOG" && ok "format: runs from that repo's top" \
  || bad "format: wrong directory or target in the top-level repo: $(cat "$STUB_LOG")"
grep -q credo "$STUB_LOG" && bad "format: credo ran in a repo that does not use it" \
  || ok "format: no credo where the repo does not use it"

echo
echo "$pass passed, $failures failed"
[ "$failures" -eq 0 ]
