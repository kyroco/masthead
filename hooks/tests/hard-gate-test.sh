#!/usr/bin/env bash
# shellcheck disable=SC2016 # the fixtures are shell and JS text, written unexpanded on purpose
# Test for .claude/hooks/hard-gate.sh, the consolidated done gate.
#
# It drives the real script against generated projects rather than a stub,
# because the thing worth testing is the dispatch: which stack gates fire for a
# given set of changed files, and whether a missing toolchain warns or blocks.
# The Elixir case runs a real `mix` on a real project with a real formatting
# violation, so at least one rung is proven to bite rather than merely to be
# reachable.
#
# Usage: bash .claude/hooks/tests/hard-gate-test.sh
# Exit 0 = every assertion passed.

set -uo pipefail

GATE="$(cd "$(dirname "$0")/.." && pwd)/hard-gate.sh"
[ -f "$GATE" ] || { echo "FAIL: no hard-gate.sh at $GATE" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/hard-gate-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

# Run the gate in $1 as the PreToolUse hook sees a `git push` from that folder,
# capturing status and stderr. $2 overrides the command, for the cases that
# prove every other command passes straight through.
# GIT_CEILING_DIRECTORIES stops git's upward walk at the test root. Without it a
# "no git repo" case is only non-git when TMPDIR happens to sit outside a
# checkout, which is true on a laptop and false in a CI lane, where it sits
# inside one. The sibling verdict-gate test failed in exactly that way, on the
# lane and nowhere else, on 2026-09-13.
run_gate() {
  # $1 = the checkout, $2 = the command, $3 = the session's folder (default $1).
  # Facts are read only from the session's own repository, so the session
  # folder decides whether the checkout's settings count.
  cmd="${2:-git push -u origin HEAD}"
  payload="$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":sys.argv[1],"tool_input":{"command":sys.argv[2]}}))' "$1" "$cmd")"
  ( cd "$1" && printf '%s' "$payload" \
      | CLAUDE_PROJECT_DIR="${3:-$1}" GIT_CEILING_DIRECTORIES="$TMP" bash "$GATE" 2>"$TMP/err" ; echo $? > "$TMP/status" )
  STATUS="$(cat "$TMP/status")"
  ERR="$(cat "$TMP/err")"
}

# Run the gate in $1 as the PreToolUse hook sees a GitHub connector call named $2 (issue #27).
run_connector() {
  payload="$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":sys.argv[2],"cwd":sys.argv[1],"tool_input":{"owner":"o","repo":"r","title":"t","head":"b","base":"main","body":"Fixes #27","pullNumber":1}}))' "$1" "$2")"
  ( cd "$1" && printf '%s' "$payload" \
      | CLAUDE_PROJECT_DIR="$1" GIT_CEILING_DIRECTORIES="$TMP" bash "$GATE" 2>"$TMP/err" ; echo $? > "$TMP/status" )
  STATUS="$(cat "$TMP/status")"
  ERR="$(cat "$TMP/err")"
}

ok() {
  if [ "$1" = "$2" ]; then
    pass=$((pass + 1))
    echo "  ok: $3"
  else
    fail=$((fail + 1))
    echo "  FAIL: $3 (expected '$2', got '$1')" >&2
    [ -n "${ERR:-}" ] && echo "        stderr: $(printf '%s' "$ERR" | head -3 | tr '\n' ' ')" >&2
  fi
}

contains() {
  # A here-string, not a pipe: under pipefail grep -q leaves at its first match,
  # printf takes a broken pipe on the rest, and a match is read as a miss.
  if grep -q "$2" <<<"$1"; then
    pass=$((pass + 1))
    echo "  ok: $3"
  else
    fail=$((fail + 1))
    echo "  FAIL: $3 (stderr did not contain '$2')" >&2
    echo "        stderr: $(printf '%s' "$1" | head -5 | tr '\n' ' ')" >&2
  fi
}

newrepo() {
  d="$TMP/$1"
  mkdir -p "$d"
  ( cd "$d" && git init -q . && git config user.email t@t && git config user.name t ) >/dev/null 2>&1
  printf '%s' "$d"
}

echo "1. outside a git repo the gate stands down"
mkdir -p "$TMP/nogit"
run_gate "$TMP/nogit"
ok "$STATUS" "0" "no git repo exits 0"

echo "2. a clean repo has no delta to gate"
d="$(newrepo clean)"
run_gate "$d"
ok "$STATUS" "0" "no changed files exits 0"

echo "3. changed files of no gated extension are none of its business"
d="$(newrepo docsonly)"
echo "# notes" > "$d/README.md"
run_gate "$d"
ok "$STATUS" "0" "a changed .md exits 0"

echo "4. a changed .ex with no mix.exs warns, it does not block"
d="$(newrepo looseex)"
echo 'defmodule A do' > "$d/a.ex"
run_gate "$d"
ok "$STATUS" "0" "no mix.exs exits 0"
contains "$ERR" "no mix.lock mix.exs above them" "it says why it stood down"

echo "5. a changed .tf with no runtime installed blocks"
d="$(newrepo tf)"
echo 'resource "null_resource" "x" {}' > "$d/main.tf"
if command -v tofu >/dev/null 2>&1 || command -v terraform >/dev/null 2>&1; then
  echo "  skip: a terraform runtime is installed on this machine"
else
  run_gate "$d"
  ok "$STATUS" "2" "missing tofu and terraform exits 2"
  contains "$ERR" "cannot be verified" "it says the change cannot be verified"
fi

echo "6. Rust is left to CI's Native job: a changed .rs runs no rung"
d="$(newrepo looserust)"
echo 'fn main( ) {  }' > "$d/main.rs"
run_gate "$d"
ok "$STATUS" "0" "a badly formatted .rs does not block here"

echo "7. a real Elixir project with a formatting violation blocks on mix format"
if [ -f "$HOME/.local/kyroco-toolchain.env" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.local/kyroco-toolchain.env"
fi
if ! command -v mix >/dev/null 2>&1; then
  echo "  skip: mix is not on PATH"
else
  d="$TMP/exproj"
  ( cd "$TMP" && mix new exproj --app exproj ) >/dev/null 2>&1
  ( cd "$d" && git init -q . && git config user.email t@t && git config user.name t && git add -A && git commit -qm base ) >/dev/null 2>&1
  # A violation mix format --check-formatted must catch, in a file the delta
  # scope will see. Badly spaced, but valid Elixir, so compile still succeeds and
  # the format rung is the one that fires.
  printf 'defmodule Exproj.Bad do\n  def go( x ),   do:    x\nend\n' > "$d/lib/bad.ex"
  run_gate "$d"
  ok "$STATUS" "2" "an unformatted changed .ex exits 2"
  contains "$ERR" "mix format" "it names the failing command"
  contains "$ERR" "Run 'mix format'" "it names the fix"

  echo "8. the same project formatted cleanly passes"
  ( cd "$d" && mix format ) >/dev/null 2>&1
  run_gate "$d"
  ok "$STATUS" "0" "a formatted, compiling, tested project exits 0"
fi

echo "8b. the Elixir rung uses the pinned toolchain, not whatever mix the shell has"
# Two fake mix binaries. The one first on PATH is the wrong Elixir and fails
# everything; the right one is reachable only through the toolchain file.
mkdir -p "$TMP/wrongbin" "$TMP/pinnedbin"
printf '#!/bin/sh\necho "WRONG MIX RAN" >&2\nexit 1\n' > "$TMP/wrongbin/mix"
printf '#!/bin/sh\nexit 0\n' > "$TMP/pinnedbin/mix"
chmod +x "$TMP/wrongbin/mix" "$TMP/pinnedbin/mix"
printf 'export PATH="%s:$PATH"\n' "$TMP/pinnedbin" > "$TMP/toolchain.env"
run_pinned() {
  payload="$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":sys.argv[1],"tool_input":{"command":"git push"}}))' "$1")"
  ( cd "$1" && printf '%s' "$payload" \
      | env CLAUDE_PROJECT_DIR="$1" PATH="$TMP/wrongbin:$PATH" PROJECT_TOOLCHAIN_ENV="$TMP/toolchain.env" \
        GIT_CEILING_DIRECTORIES="$TMP" bash "$GATE" 2>"$TMP/err" ; echo $? > "$TMP/status" )
  STATUS="$(cat "$TMP/status")"
  ERR="$(cat "$TMP/err")"
}
# The pin is a fact the checkout states in its .claude/settings.json env. The
# environment also carries it in both runs, to prove a checkout that states no
# pin is not given one from there.
d="$(newrepo pinned)"
mkdir -p "$d/.claude" "$d/lib"
printf '{"env": {"PROJECT_TOOLCHAIN_ENV": "%s"}}\n' "$TMP/toolchain.env" > "$d/.claude/settings.json"
: > "$d/mix.exs"
( cd "$d" && git add -A && git commit -qm "a checkout that pins its toolchain" ) >/dev/null 2>&1
printf 'defmodule A do\nend\n' > "$d/lib/a.ex"
run_pinned "$d"
ok "$STATUS" "0" "in a checkout that names a toolchain the pinned mix ran and every rung passed"

d="$(newrepo notpinned)"
mkdir -p "$d/lib"
: > "$d/mix.exs"
( cd "$d" && git add -A && git commit -qm "some other repository" ) >/dev/null 2>&1
printf 'defmodule A do\nend\n' > "$d/lib/a.ex"
run_pinned "$d"
ok "$STATUS" "2" "in a checkout that names none the pin is not applied and the shell's mix ran"

echo "9. the operator escape stands the gate down"
d="$(newrepo escape)"
echo 'resource "null_resource" "x" {}' > "$d/main.tf"
( cd "$d" && printf '%s' '{"hook_event_name":"PreToolUse","tool_input":{"command":"git push"}}' | MASTHEAD_DONE_GATE=off bash "$GATE" >/dev/null 2>&1 ; echo $? > "$TMP/status" )
ok "$(cat "$TMP/status")" "0" "MASTHEAD_DONE_GATE=off exits 0"

echo "10. a credential compiled into source blocks, in any language"
d="$(newrepo secret-js)"
python3 - "$d/config.js" <<'PYEOF'
import sys
open(sys.argv[1], "w").write(
    "export const client = {\n"
    "  awsKey: \"AKIA" + "Q" * 16 + "\",\n"
    "};\n"
)
PYEOF
run_gate "$d"
ok "$STATUS" "2" "an AWS access key in a changed .js exits 2"
contains "$ERR" "possible secret" "it names what it found"
leaked="$(printf '%s' "$ERR" | grep -c "AKIAQQQQ")"
ok "$leaked" "0" "the refusal does not print the secret itself"

echo "11. a waived placeholder does not block"
d="$(newrepo secret-waived)"
python3 - "$d/config.js" <<'PYEOF'
import sys
open(sys.argv[1], "w").write(
    "export const client = {\n"
    "  awsKey: \"AKIA" + "Q" * 16 + "\", // allow-secret: docs placeholder\n"
    "};\n"
)
PYEOF
run_gate "$d"
ok "$STATUS" "0" "an allow-secret marker on the line exits 0"

echo "12. an interpolated value is not a compiled-in literal"
d="$(newrepo secret-interp)"
printf '%s\n' 'const token = `${process.env.GITHUB_TOKEN}`' > "$d/config.js"
run_gate "$d"
ok "$STATUS" "0" "an interpolated token exits 0"

echo "13. the terraform rungs run in the changed directory, not the repo root"
d="$(newrepo tf-scoped)"
mkdir -p "$d/envs/dev" "$d/envs/untouched"
# Unformatted HCL in the directory that changed, and in one that did not.
printf 'resource "null_resource"   "x" {\n}\n' > "$d/envs/dev/main.tf"
printf 'resource "null_resource"   "y" {\n}\n' > "$d/envs/untouched/main.tf"
( cd "$d" && git add envs/untouched/main.tf && git commit -qm base ) >/dev/null 2>&1
if command -v tofu >/dev/null 2>&1 || command -v terraform >/dev/null 2>&1; then
  run_gate "$d"
  ok "$STATUS" "2" "unformatted HCL in the changed directory exits 2"
  contains "$ERR" "envs/dev" "the block names the directory that changed"
  if printf '%s' "$ERR" | grep -q "envs/untouched"; then
    fail=$((fail + 1))
    echo "  FAIL: the untouched directory was reported (the gate is not delta scoped)" >&2
  else
    pass=$((pass + 1))
    echo "  ok: the untouched directory is not reported"
  fi
else
  echo "  skip: no terraform runtime on this machine"
fi

echo "14. a wholly untracked directory is still read file by file"
# git status --porcelain collapses one to a single "envs/dev/" entry, which has no
# extension, so the gate used to stand down on every brand new directory.
d="$(newrepo untracked-dir)"
mkdir -p "$d/lib/deep"
printf 'defmodule A do\nend\n' > "$d/lib/deep/a.ex"
run_gate "$d"
ok "$STATUS" "0" "no mix.exs, so it warns rather than blocks"
contains "$ERR" "no mix.lock mix.exs above them" "it saw the .ex inside the new directory"

echo "15. Elixir interpolation is not a compiled-in literal"
d="$(newrepo secret-ex-interp)"
mkdir -p "$d/lib"
printf '%s\n' 'session_token: "scoped-token-#{tenant_id}"' > "$d/lib/a.ex"
run_gate "$d"
if printf '%s' "$ERR" | grep -q "possible secret"; then
  fail=$((fail + 1))
  echo "  FAIL: an Elixir interpolation was read as a compiled-in literal" >&2
else
  pass=$((pass + 1))
  echo "  ok: #{...} is treated like \${...}"
fi

echo "16. the waiver counts on the line ABOVE the hit"
# mix format moves a trailing comment inside a keyword list onto its own line, so
# a same-line marker cannot be written in formatted Elixir at all.
d="$(newrepo secret-waiver-above)"
mkdir -p "$d/lib"
{
  printf '%s\n' '      # allow-secret: a fixed string this test asserts on.'
  # allow-secret: the fixture line below is the thing under test.
  printf '%s\n' '      web_identity_token: "signed-test-token",'
} > "$d/lib/a.ex"
run_gate "$d"
if printf '%s' "$ERR" | grep -q "possible secret"; then
  fail=$((fail + 1))
  echo "  FAIL: a waiver on the line above did not count" >&2
else
  pass=$((pass + 1))
  echo "  ok: a waiver on the preceding line waives the hit"
fi

echo "17. and an unwaived literal beside it still blocks"
d="$(newrepo secret-unwaived)"
mkdir -p "$d/lib"
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/lib/a.ex"
run_gate "$d"
ok "$STATUS" "2" "an unwaived credential-shaped literal exits 2"

echo "18. a shell command substitution is not a compiled-in literal"
# Found 2026-09-18: a wrapper reading a token from 1Password at runtime was
# blocked as a shipped secret, because only \${...} counted as computed.
d="$(newrepo secret-cmd-subst)"
printf '%s\n' 'secret="$(op read --no-newline "$ref")"' > "$d/wrap.sh"
run_gate "$d"
ok "$STATUS" "0" "a \$(...) value exits 0"

echo "19. every command but a push or a PR passes straight through"
d="$(newrepo notapush)"
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/a.ex"
run_gate "$d" "git status"
ok "$STATUS" "0" "git status with a secret in the tree exits 0"
run_gate "$d" "gh pr create --fill"
ok "$STATUS" "2" "gh pr create is gated"
run_gate "$d" "git -C $d push"
ok "$STATUS" "2" "git -C dir push is gated"

echo "20. the delta is the branch: a committed change is gated, not only the tree"
d="$(newrepo branchdelta)"
( cd "$d" && echo base > README && git add README && git commit -qm base \
    && git update-ref refs/remotes/origin/main HEAD ) >/dev/null 2>&1
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/a.ex"
( cd "$d" && git add a.ex && git commit -qm leak ) >/dev/null 2>&1
run_gate "$d"
ok "$STATUS" "2" "a clean tree whose branch commits a secret still blocks the push"

echo "21. the push is followed to the checkout it acts on"
d="$(newrepo leaky-wt)"
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/a.ex"
clean="$(newrepo clean-cwd)"
# The command runs from $clean and acts on $d, which is the session's repository
# (in life, a worktree of it); a checkout outside it is covered in 27.
run_gate "$clean" "cd $d && git push" "$d"
ok "$STATUS" "2" "cd DIR && git push gates DIR, not the session folder"
run_gate "$clean" "git -C \"$d\" push" "$d"
ok "$STATUS" "2" "a quoted git -C path is followed"
run_gate "$clean" "git -c core.sshCommand=ssh -C $d push" "$d"
ok "$STATUS" "2" "git -c k=v push is a push"
run_gate "$d" "git --no-pager push"
ok "$STATUS" "2" "git --no-pager push is a push"
run_gate "$d" "scripts/create-pr.sh --fill"
ok "$STATUS" "2" "the repo's create-pr.sh is a PR"
run_gate "$d" "git log --oneline"
ok "$STATUS" "0" "a git command that is not a push passes"

echo "22. a secret one commit added and a later one removed still blocks"
d="$(newrepo secret-history)"
( cd "$d" && echo base > README && git add README && git commit -qm base \
    && git update-ref refs/remotes/origin/main HEAD ) >/dev/null 2>&1
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/a.ex"
( cd "$d" && git add a.ex && git commit -qm leak && echo '# gone' > a.ex && git commit -qam cover ) >/dev/null 2>&1
run_gate "$d"
ok "$STATUS" "2" "the history scan catches it"
contains "$ERR" "history still carries it" "it says why removing it is not enough"

echo "23. each project's rung sees only its own files"
d="$(newrepo tworoots)"
mkdir -p "$d/app/lib" "$d/elsewhere"
: > "$d/app/mix.exs"
# An unformatted .exs with no project above it. Before, the app's mix format was
# handed it too and blocked on a file no project owns.
printf 'x=1\n' > "$d/elsewhere/loose.exs"
printf 'defmodule A do\nend\n' > "$d/app/lib/a.ex"
printf '#!/bin/sh\nfor a in "$@"; do case "$a" in *loose.exs) echo "WRONG FILE $a" >&2; exit 1;; esac; done; exit 0\n' > "$TMP/pinnedbin/mix"
chmod +x "$TMP/pinnedbin/mix"
( cd "$d" && printf '%s' "$(python3 -c 'import json,sys; print(json.dumps({"tool_input":{"command":"git push"},"cwd":sys.argv[1]}))' "$d")" \
    | PATH="$TMP/pinnedbin:$PATH" GIT_CEILING_DIRECTORIES="$TMP" bash "$GATE" 2>"$TMP/err"; echo $? > "$TMP/status" )
STATUS="$(cat "$TMP/status")"; ERR="$(cat "$TMP/err")"
ok "$STATUS" "0" "the app's mix never sees a file outside the app"

echo "24. a push followed by a long heredoc is still a push"
# Found 2026-09-24: the push detector piped the command into
# grep -q under pipefail. grep stopped at the match on line 1, printf took
# SIGPIPE on the rest, the pipeline returned 141, and the gate read "not a
# push". About 100 KB: over a pipe buffer, under Linux's 128 KB limit on one
# argument, which the payload passes through.
d="$(newrepo long-push)"
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/a.ex"
long="git push -u origin HEAD
$(awk 'BEGIN { for (i = 0; i < 1400; i++) printf "filler line %05d of a heredoc long enough to outrun a pipe buffer\n", i }')"
run_gate "$d" "$long"
ok "$STATUS" "2" "a push on line 1 of a 100 KB command is gated"

echo "25. each issuer shape blocks at its length, and one short of it does not"
# The patterns spell out every character class rather than use a {n} count,
# which older mawk cannot read, so each length is checked here.
# $1 = name, $2 = prefix, $3 = class character, $4 = length, $5 = want.
shape() {
  d="$(newrepo "shape-$2-$4")"
  python3 - "$d/config.js" "$2" "$3" "$4" <<'PYEOF'
import sys
path, prefix, ch, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
open(path, "w").write('export const k = "' + prefix + ch * n + '";\n')
PYEOF
  run_gate "$d"
  ok "$STATUS" "$5" "$1 with $4 characters exits $5"
}
shape "a Google API key" AIza Q 35 2
shape "a Google API key" AIza Q 34 0
shape "a GitHub token" ghp_ Q 36 2
shape "a GitHub token" ghp_ Q 35 0
shape "a Slack token" xoxb- 1 10 2
shape "a Slack token" xoxb- 1 9 0

echo "26. an awk that cannot read the secret patterns blocks instead of passing"
# Every other awk call still works; only the secret scan's is broken.
mkdir -p "$TMP/brokenawk"
real_awk="$(command -v awk)"
printf '#!/bin/sh\ncase "$*" in *issuer=*) exit 2;; esac\nexec %s "$@"\n' "$real_awk" > "$TMP/brokenawk/awk"
chmod +x "$TMP/brokenawk/awk"
d="$(newrepo broken-awk)"
printf '{"nothing": "secret here"}\n' > "$d/config.json"
payload="$(python3 -c 'import json,sys; print(json.dumps({"tool_input":{"command":"git push"},"cwd":sys.argv[1]}))' "$d")"
( cd "$d" && printf '%s' "$payload" \
    | CLAUDE_PROJECT_DIR="$d" PATH="$TMP/brokenawk:$PATH" GIT_CEILING_DIRECTORIES="$TMP" bash "$GATE" 2>"$TMP/err"; echo $? > "$TMP/status" )
STATUS="$(cat "$TMP/status")"; ERR="$(cat "$TMP/err")"
ok "$STATUS" "2" "a scan that cannot run exits 2"
contains "$ERR" "secret scan could not run" "it says the scan did not run"

echo "27. the local-tests rung reads the receipt check, and a failing check blocks"
# A stub local-tests.sh stands in for the real one: the rung's job is to call
# --check and act on its answer, not to run tests.
d="$(newrepo localtests)"
mkdir -p "$d/scripts" "$d/.claude"
echo '{"env": {"PROJECT_PUSH_CHECK": "scripts/local-tests.sh"}}' > "$d/.claude/settings.json"
cat > "$d/scripts/local-tests.sh" <<'EOF'
#!/usr/bin/env bash
[ "$1" = --check ] || exit 9
cat "$(dirname "$0")/verdict"
exit "$(cat "$(dirname "$0")/code")"
EOF
echo "# notes" > "$d/README.md"
echo "local-tests: the receipt is for another commit." > "$d/scripts/verdict"
echo 1 > "$d/scripts/code"
run_gate "$d"
ok "$STATUS" "2" "a failing receipt check exits 2"
contains "$ERR" "local tests have not passed" "it says the local tests have not passed"
contains "$ERR" "receipt is for another commit" "it passes on the check's reason"
run_gate "$d" "gh pr create --fill"
ok "$STATUS" "2" "opening a PR is gated the same way"
run_connector "$d" "mcp__claude_ai_GitHub__create_pull_request"
ok "$STATUS" "2" "opening a PR through a GitHub connector is gated the same way"
contains "$ERR" "local tests have not passed" "the connector refusal says the local tests have not passed"
run_connector "$d" "mcp__claude_ai_GitHub__pull_request_read"
ok "$STATUS" "0" "reading a PR through a GitHub connector is not gated"
run_gate "$d" "git push origin --delete old-branch"
ok "$STATUS" "0" "deleting a remote branch pushes no work and is not gated"
run_gate "$d" "git push origin :old-branch"
ok "$STATUS" "0" "the colon spelling of a deletion is not gated either"
run_gate "$d" "gh pr create -d --fill"
ok "$STATUS" "2" "gh's -d (draft) is not a deletion and is still gated"
run_gate "$d" "git branch -d old && git push"
ok "$STATUS" "2" "a -d on another command does not excuse the push after it"
run_gate "$d" "git push -d origin old && git push origin HEAD"
ok "$STATUS" "2" "a deletion beside a real push does not excuse the real push"
# A checkout outside the session's repository names a check script too. The
# gate must not run it: that would run a stranger's code from a hook.
: > "$TMP/stranger-ran"; rm -f "$TMP/stranger-ran"
printf '#!/usr/bin/env bash\ntouch "%s"\nexit 1\n' "$TMP/stranger-ran" > "$d/scripts/local-tests.sh"
run_gate "$d" "git push" "$TMP"
[ -e "$TMP/stranger-ran" ] && ran=yes || ran=no
ok "$ran" "no" "a checkout outside the session's repository does not get its check script run"
contains "$ERR" "not this session's repository" "and it says the checks were not run there"
cat > "$d/scripts/local-tests.sh" <<'EOF'
#!/usr/bin/env bash
[ "$1" = --check ] || exit 9
cat "$(dirname "$0")/verdict"
exit "$(cat "$(dirname "$0")/code")"
EOF
echo 0 > "$d/scripts/code"
run_gate "$d"
ok "$STATUS" "0" "a passing receipt check lets the push through"
run_gate "$d" "git status"
ok "$STATUS" "0" "a command that is not a push never reaches the rung"

echo "28. a push of anything but HEAD is refused, since the receipt is for HEAD"
( cd "$d" && git add -A && git commit -qm one && git checkout -qb other \
    && echo more >> README.md && git commit -qam two && git checkout -q - \
    && echo pending > notes.md ) >/dev/null 2>&1
run_gate "$d" "git push origin HEAD"
ok "$STATUS" "0" "pushing HEAD with a passing check goes through"
run_gate "$d" "git push -u origin $(cd "$d" && git branch --show-current)"
ok "$STATUS" "0" "pushing the current branch by name goes through"
run_gate "$d" "git push origin other"
ok "$STATUS" "2" "pushing another branch is refused"
contains "$ERR" "not HEAD" "it says the push is not HEAD"
run_gate "$d" "git push origin other:refs/heads/x"
ok "$STATUS" "2" "pushing another commit to a new name is refused"
run_gate "$d" "git push --all origin"
ok "$STATUS" "2" "pushing every branch is refused"

echo "29. a shell redirect after the push is not read as a branch"
# Found 2026-11-11: `git push -u origin BRANCH 2>&1 | tail -3` was refused as
# sending '2>&1', because every word after the remote was read as a refspec.
# It refused 18 pushes across 17 of 24 pull requests.
cur="$(cd "$d" && git branch --show-current)"
run_gate "$d" "git push -u origin $cur 2>&1 | tail -3"
ok "$STATUS" "0" "2>&1 and a pipe after the branch still push the branch"
run_gate "$d" "git push -q origin $cur 2>/dev/null"
ok "$STATUS" "0" "2>/dev/null after the branch still pushes the branch"
for redirect in "> push.log" ">push.log" ">> push.log" "&> push.log" "&>push.log" \
    "< /dev/null" "</dev/null" "2> err.log" ">&2" "2>&1 >/dev/null"; do
  run_gate "$d" "git push origin $cur $redirect"
  ok "$STATUS" "0" "a push of the branch followed by '$redirect' goes through"
done
run_gate "$d" "git push 2>&1 origin $cur"
ok "$STATUS" "0" "a redirect before the remote is dropped too"
run_gate "$d" "git push origin $cur>push.log"
ok "$STATUS" "0" "a redirect written against the branch name ends the name there"
# A push that really names another branch is still refused, and the refusal
# names the branch, not the redirect.
run_gate "$d" "git push -u origin other 2>&1 | tail -3"
ok "$STATUS" "2" "another branch with 2>&1 and a pipe is still refused"
contains "$ERR" "sends 'other'" "the refusal names the branch, not the redirect"
run_gate "$d" "git push origin $cur other > push.log"
ok "$STATUS" "2" "a second refspec naming another branch is still refused"
run_gate "$d" "git push origin other>push.log"
ok "$STATUS" "2" "another branch with a redirect written against it is still refused"
contains "$ERR" "sends 'other'" "and the refusal names that branch"
run_gate "$d" "git push origin '>other'"
ok "$STATUS" "2" "a quoted word that starts with > is a refspec, not a redirect"
run_gate "$d" "git push origin $cur 2>&1 other"
ok "$STATUS" "2" "a branch named after a redirect is still read"
# Round 1 finding F1: only the plain digits 0 to 9 are a file number to the
# shell. A branch named with another script's digit is a branch.
( cd "$d" && git branch "٣" other && git branch "²" other ) >/dev/null 2>&1
for name in "٣" "²" "１"; do
  run_gate "$d" "git push origin $name>x"
  ok "$STATUS" "2" "a branch named $name right against a redirect is still read as a branch"
  contains "$ERR" "sends '$name'" "and the refusal names it"
done
run_gate "$d" "git push origin $cur ٣> x"
ok "$STATUS" "2" "the same with a second refspec and a space after the redirect"
run_gate "$d" "git push origin $cur 2>x"
ok "$STATUS" "0" "a plain digit right against a redirect is still a file number"
# Round 1 finding F8: a push whose words are split by a line continuation, or by
# a ; or | inside quotes, is one push to the shell, and the branch it names counts.
run_gate "$d" "git push \\
  origin other"
ok "$STATUS" "2" "a push of another branch carried over two lines is refused"
contains "$ERR" "sends 'other'" "and the refusal names the branch"
while IFS= read -r pushing; do
  run_gate "$d" "$pushing"
  ok "$STATUS" "2" "a push of another branch is refused: $pushing"
  contains "$ERR" "sends 'other'" "and the refusal names the branch"
done <<'EOF'
git push -o "note=a;b" origin other
git push -o "a|b" origin other
git push -o 'a && b' origin other
git push -o 'a || b' origin other
EOF
run_gate "$d" "git push \\
  origin $cur"
ok "$STATUS" "0" "a push of the checked-out branch carried over two lines goes through"
run_gate "$d" "git push -o \"note=a;b\" origin $cur"
ok "$STATUS" "0" "a push of the checked-out branch with a ; inside quotes goes through"
# The cut that does not read quotes is still made too, so what it caught is still caught.
run_gate "$d" "bash -c \"git fetch; git push origin other\""
ok "$STATUS" "2" "a push of another branch inside a quoted command line is still refused"
run_gate "$d" "cat > notes.txt <<EOF
it's a note
EOF
git push origin other
echo 'done'"
ok "$STATUS" "2" "a push of another branch after a here-document with an apostrophe is still refused"

echo "30. reading create-pr.sh is not opening a PR, and running it still is"
# Found 2026-11-11: `sed -n 1,30p scripts/kyroco/create-pr.sh | grep '^#'` ran
# the whole gate and cost one worker 265 seconds, because any command that
# named the file counted as a run of it.
d="$(newrepo reads-create-pr)"
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/a.ex"
# The secret in the tree blocks any command the gate takes for a PR, so exit 0
# here means the gate stood aside and exit 2 means it ran.
while IFS= read -r reading; do
  run_gate "$d" "$reading"
  ok "$STATUS" "0" "a read is not gated: $reading"
done <<'EOF'
sed -n 1,30p scripts/kyroco/create-pr.sh | grep '^#'
cat scripts/create-pr.sh
ls -la scripts/create-pr.sh
grep -n receipt scripts/kyroco/create-pr.sh
head -20 scripts/create-pr.sh 2>/dev/null
cd scripts && wc -l create-pr.sh
chmod +x scripts/create-pr.sh
git log --oneline -3 -- scripts/create-pr.sh
git diff main -- scripts/kyroco/create-pr.sh
git add scripts/create-pr.sh && git commit -m "Say in create-pr.sh what it checks" -- scripts/create-pr.sh
EOF
while IFS= read -r running; do
  run_gate "$d" "$running"
  ok "$STATUS" "2" "a run is still gated: $running"
done <<'EOF'
scripts/create-pr.sh --fill
bash scripts/kyroco/create-pr.sh
./create-pr.sh
cd scripts && ./create-pr.sh --fill
FOO=1 scripts/create-pr.sh
env FOO=1 bash scripts/create-pr.sh
time ./scripts/create-pr.sh
op run -- scripts/create-pr.sh
just pr scripts/create-pr.sh
sh -c "scripts/create-pr.sh --fill"
cat scripts/create-pr.sh | bash
ls scripts/create-pr.sh | xargs bash
chmod +x scripts/create-pr.sh && scripts/create-pr.sh
sed -n 1p scripts/create-pr.sh; (./scripts/create-pr.sh)
cat scripts/create-pr.sh & ./scripts/create-pr.sh
echo "$(bash scripts/create-pr.sh)"
echo `bash scripts/create-pr.sh`
diff <(bash scripts/create-pr.sh) expected.txt
find . -name create-pr.sh -exec bash {} \;
git -c alias.pr='!scripts/create-pr.sh' pr
git bisect run scripts/create-pr.sh
cat "scripts/create-pr.sh
EOF
# Round 1 finding F2: a run of the script through standard input still needs the
# test receipt. The receipt rung looked for the name only in the words left
# after redirects were dropped, and the name sat in a dropped redirect.
d="$(newrepo stdin-create-pr)"
mkdir -p "$d/scripts" "$d/.claude"
echo '{"env": {"PROJECT_PUSH_CHECK": "scripts/local-tests.sh"}}' > "$d/.claude/settings.json"
printf '#!/usr/bin/env bash\n[ "$1" = --check ] || exit 9\necho "local-tests: no receipt for this commit."\nexit 1\n' > "$d/scripts/local-tests.sh"
echo "# notes" > "$d/README.md"
while IFS= read -r running; do
  run_gate "$d" "$running"
  ok "$STATUS" "2" "a run with no receipt is refused: $running"
  contains "$ERR" "local tests have not passed" "and the refusal is the receipt's"
done <<'EOF'
bash scripts/create-pr.sh
bash < scripts/create-pr.sh
bash -s -- --fill < scripts/create-pr.sh
sh <scripts/create-pr.sh
bash 0<scripts/create-pr.sh
bash <<< "$(cat scripts/create-pr.sh)"
cat scripts/create-pr.sh | bash
EOF
run_gate "$d" "cat scripts/create-pr.sh"
ok "$STATUS" "0" "a read of the script in that checkout asks for no receipt"
# Round 1 finding F3: a |, ;, && or & inside quotes is part of a pattern, not the
# end of a command, so a grep or sed that carries one is still only a read.
d="$(newrepo quoted-reads)"
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/a.ex"
while IFS= read -r reading; do
  run_gate "$d" "$reading"
  ok "$STATUS" "0" "a read is not gated: $reading"
done <<'EOF'
grep -nE 'receipt|gh pr' scripts/create-pr.sh
sed -n '1,30p;/main/p' scripts/create-pr.sh
grep -n 'a && b' scripts/create-pr.sh
grep -n '\$(' scripts/create-pr.sh
grep -n '&' scripts/create-pr.sh
grep -n "a | b" scripts/create-pr.sh
grep -n 'a `b` c' scripts/create-pr.sh
grep -n \| scripts/create-pr.sh
EOF
run_gate "$d" "cat scripts/create-pr.sh \\
  | head -5"
ok "$STATUS" "0" "a read carried over two lines with a backslash is not gated"
# What quotes do not hide: a command inside double quotes still runs, and a
# separator outside the quotes still ends the command.
while IFS= read -r running; do
  run_gate "$d" "$running"
  ok "$STATUS" "2" "a run is still gated: $running"
done <<'EOF'
grep -n "$(bash scripts/create-pr.sh)" README.md
grep -n "`bash scripts/create-pr.sh`" README.md
cat 'a;b' ; scripts/create-pr.sh
grep -n 'a | b' README.md | bash scripts/create-pr.sh
cat 'a&b' & scripts/create-pr.sh
cat scripts/create-pr.sh 'unclosed
cat <<EOF > scripts/create-pr.sh
EOF
run_gate "$d" "cat scripts/create-pr.sh \\
  | bash"
ok "$STATUS" "2" "a pipe into a shell carried over two lines is still gated"
# Round 1 finding F7: a NAME=value before a file command can hand it a program
# to run (git diff runs GIT_EXTERNAL_DIFF), so a command with one is not a read.
while IFS= read -r running; do
  run_gate "$d" "$running"
  ok "$STATUS" "2" "a run is still gated: $running"
done <<'EOF'
GIT_EXTERNAL_DIFF=scripts/create-pr.sh git diff
GIT_EXTERNAL_DIFF=scripts/create-pr.sh git diff -- README.md
GIT_EDITOR=scripts/create-pr.sh git commit
PAGER=scripts/create-pr.sh git log
GIT_PAGER="bash scripts/create-pr.sh" git show
LESSOPEN="|scripts/create-pr.sh %s" cat README.md
cd scripts && GIT_EXTERNAL_DIFF=./create-pr.sh git diff
EOF
# Round 1 finding F9: a file command with an option or a script that runs a
# program is not a read. rg --pre, sort --compress-program and a pager run the
# program they are given, and GNU sed runs one with its e command or the e flag.
while IFS= read -r running; do
  run_gate "$d" "$running"
  ok "$STATUS" "2" "a run is still gated: $running"
done <<'EOF'
rg --pre scripts/create-pr.sh x README.md
rg --pre=scripts/create-pr.sh x README.md
sort --compress-program=scripts/create-pr.sh README.md
sort --compress-program scripts/create-pr.sh README.md
bat --pager scripts/create-pr.sh README.md
gh alias set --shell pr scripts/create-pr.sh
sed -n '1e bash scripts/create-pr.sh' README.md
sed e scripts/create-pr.sh
sed 's/.*/bash &/e' scripts/create-pr.sh
sed -n -e 1p -e '1e true' scripts/create-pr.sh
sed -n '/x/{e;}' scripts/create-pr.sh
sed -f run.sed scripts/create-pr.sh
sed --file=run.sed scripts/create-pr.sh
sed -n '1w scripts/create-pr.sh' README.md
EOF
# The sed scripts a read is made of still pass.
while IFS= read -r reading; do
  run_gate "$d" "$reading"
  ok "$STATUS" "0" "a read is not gated: $reading"
done <<'EOF'
sed -n 1,30p scripts/create-pr.sh
sed -n '10,$p' scripts/create-pr.sh
sed -n '/receipt/,/fi/p' scripts/create-pr.sh
sed -n '/^#/!p' scripts/create-pr.sh
sed -n -e 5p -e 10p scripts/create-pr.sh
sed -E -n '/main|base/p' scripts/create-pr.sh
sed 10q scripts/create-pr.sh
sed -n '$=' scripts/create-pr.sh
sed 's/old/new/g' scripts/create-pr.sh
sed -i '' 's|a/b|c/d|' scripts/create-pr.sh
sed -i.bak -e 's/a/b/2' scripts/create-pr.sh
EOF

# A stand-in for mix that counts its calls, for the cases that ask whether the
# slow Elixir rung ran at all. It exits with the code in $TMP/mixcode.
mkdir -p "$TMP/countbin"
# When $TMP/mixhook exists, `mix compile` runs it once first: a change that lands
# while the slow rung is running.
printf '#!/bin/sh\necho "$*" >> "%s"\nif [ "$1" = compile ] && [ -x "%s" ]; then "%s"; rm -f "%s"; fi\nexit "$(cat "%s" 2>/dev/null || echo 0)"\n' \
  "$TMP/mixlog" "$TMP/mixhook" "$TMP/mixhook" "$TMP/mixhook" "$TMP/mixcode" > "$TMP/countbin/mix"
chmod +x "$TMP/countbin/mix"
# $1 = the checkout, $2 = the command (default: a plain push of HEAD), $3 = one
# more NAME=value for the gate's environment. MIXRUNS is how many times mix ran.
run_counted() {
  : > "$TMP/mixlog"
  payload="$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":sys.argv[1],"tool_input":{"command":sys.argv[2]}}))' "$1" "${2:-git push -u origin HEAD}")"
  ( cd "$1" && printf '%s' "$payload" \
      | env CLAUDE_PROJECT_DIR="$1" PATH="$TMP/countbin:$PATH" GIT_CEILING_DIRECTORIES="$TMP" ${3:+"$3"} \
        bash "${GATE_UNDER_TEST:-$GATE}" 2>"$TMP/err" ; echo $? > "$TMP/status" )
  STATUS="$(cat "$TMP/status")"
  ERR="$(cat "$TMP/err")"
  MIXRUNS="$(wc -l < "$TMP/mixlog" | tr -d ' ')"
}
ran() {
  # $1 = yes or no, $2 = what the case shows.
  if [ "$MIXRUNS" -gt 0 ]; then got=yes; else got=no; fi
  ok "$got" "$1" "$2"
}
# A checkout with an Elixir change on a branch off origin/main, and a push check
# whose answer is the code in $TMP/check-code, outside the checkout, so changing
# the answer leaves the working tree clean.
quick_repo() {
  d="$(newrepo "$1")"
  mkdir -p "$d/scripts" "$d/.claude" "$d/lib"
  printf '{"env": {"PROJECT_PUSH_CHECK": "scripts/local-tests.sh", "PROJECT_TOOLCHAIN_ENV": "%s"}}\n' "$TMP/quick-toolchain.env" > "$d/.claude/settings.json"
  echo 'export QUICK_TOOLCHAIN=1' > "$TMP/quick-toolchain.env"
  printf '#!/usr/bin/env bash\n[ "$1" = --check ] || exit 9\necho "local-tests: the stub says so."\nexit "$(cat "%s")"\n' "$TMP/check-code" > "$d/scripts/local-tests.sh"
  : > "$d/mix.exs"
  printf 'deps/\n_build/\n.claude/worktrees/\n' > "$d/.gitignore"
  ( cd "$d" && git add -A && git commit -qm base && git update-ref refs/remotes/origin/main HEAD ) >/dev/null 2>&1
  printf 'defmodule A do\nend\n' > "$d/lib/a.ex"
  ( cd "$d" && git add -A && git commit -qm "an Elixir change" ) >/dev/null 2>&1
  echo 0 > "$TMP/check-code"
  echo 0 > "$TMP/mixcode"
}

echo "31. the quick checks run first, and a refusal from one stops before the slow ones"
# Measured 2026-11-11: the receipt check ran last, so a refused push still cost
# the full wait for format, compile and lint (a median of 184 seconds).
quick_repo quick-first
echo 1 > "$TMP/check-code"
run_counted "$d"
ok "$STATUS" "2" "a missing test receipt refuses the push"
contains "$ERR" "local tests have not passed" "it says the local tests have not passed"
ran no "and the Elixir rung did not run first"
contains "$ERR" "have not run yet" "it says the slower checks have not run yet"
run_counted "$d" "git push origin other-branch"
ok "$STATUS" "2" "a push of another branch is refused"
contains "$ERR" "not HEAD" "it says the push is not HEAD"
ran no "and the Elixir rung did not run first"
echo 0 > "$TMP/check-code"
# allow-secret: the fixture line below is the thing under test.
printf '%s\n' '      web_identity_token: "signed-test-token",' > "$d/lib/b.ex"
run_counted "$d"
ok "$STATUS" "2" "a secret refuses the push"
contains "$ERR" "possible secret" "it names what it found"
ran no "and the Elixir rung did not run first"
echo 1 > "$TMP/check-code"
run_counted "$d"
contains "$ERR" "local tests have not passed" "with both quick checks failing, the receipt is reported"
contains "$ERR" "possible secret" "and so is the secret, in the same refusal"
echo 0 > "$TMP/check-code"
rm -f "$d/lib/b.ex"
echo 1 > "$TMP/mixcode"
run_counted "$d"
ok "$STATUS" "2" "with both quick checks passing, a failing Elixir rung still refuses the push"
contains "$ERR" "mix compile" "and it names the failing command"
echo 0 > "$TMP/mixcode"
run_counted "$d"
ok "$STATUS" "0" "with every check passing the push goes through"
ran yes "and the Elixir rung ran"

echo "32. a pass is remembered, so the slow checks do not run twice on the same commit"
# Measured 2026-11-11: the gate reran format, compile and lint on every push and
# every PR create, 67 times for a median of 184 seconds, even when the same
# commit had passed minutes before.
quick_repo remembered
record="$d/.git/masthead-push-gate-pass"
run_counted "$d"
ok "$STATUS" "0" "the first push of a commit passes"
ran yes "and it runs the Elixir rung"
[ -f "$record" ] && wrote=yes || wrote=no
ok "$wrote" "yes" "the pass is written into the checkout's git directory"
ok "$(cd "$d" && git status --porcelain --untracked-files=all | wc -l | tr -d ' ')" "0" "so the record is never a file git could commit"
run_counted "$d"
ok "$STATUS" "0" "the same commit pushed again passes"
ran no "without running the Elixir rung again"
contains "$ERR" "not run again" "and it says the earlier pass was used"
run_counted "$d" "gh pr create --fill"
ok "$STATUS" "0" "opening the PR on that commit passes"
ran no "without running the Elixir rung again"
# The quick checks are not part of what is remembered.
echo 1 > "$TMP/check-code"
run_counted "$d"
ok "$STATUS" "2" "a remembered pass does not excuse a missing test receipt"
contains "$ERR" "local tests have not passed" "it says the local tests have not passed"
echo 0 > "$TMP/check-code"
run_counted "$d" "git push origin no-such-branch"
ok "$STATUS" "2" "nor a push of another branch"
run_counted "$d" "" "PATH=$TMP/brokenawk:$TMP/countbin:$PATH"
ok "$STATUS" "2" "and the secret scan still runs: one that cannot run still refuses"
contains "$ERR" "secret scan could not run" "it says the scan did not run"
run_counted "$d"
ran no "after those refusals the pass still stands for the same commit"

echo "33. every way a remembered pass could be stale runs the slow checks again"
git_in() { ( cd "$d" && git "$@" ) >/dev/null 2>&1; }
# Each case starts from a remembered pass and ends on one, so the next case
# proves its own change and nothing left over from the one before.
remembered() {
  run_counted "$d"
  ran no "$1"
}
printf 'defmodule B do\nend\n' > "$d/lib/b.ex"
git_in add -A && git_in commit -qm "a second change"
run_counted "$d"
ran yes "a new commit runs them"
remembered "and that commit is then remembered"
printf 'defmodule B do\n  def b, do: 1\nend\n' > "$d/lib/b.ex"
git_in commit -qa --amend --no-edit
run_counted "$d"
ran yes "an amended commit runs them"
remembered "and the amended commit is then remembered"
git_in commit -q --amend -m "the same files under a new message"
remembered "an amend that changes only the message keeps the pass, since the files are the same"
echo '# an edit' >> "$d/lib/a.ex"
run_counted "$d"
ran yes "an uncommitted edit runs them"
run_counted "$d"
ran yes "and a pass on a tree with an uncommitted edit is not remembered"
git_in add lib/a.ex
run_counted "$d"
ran yes "a staged edit runs them"
git_in reset -q HEAD lib/a.ex && git_in checkout -- lib/a.ex
remembered "taking the edit back returns to the remembered commit"
echo 'notes' > "$d/notes.txt"
run_counted "$d"
ran yes "an untracked file runs them"
run_counted "$d"
ran yes "and a pass on a tree with an untracked file is not remembered"
rm -f "$d/notes.txt"
remembered "removing the file returns to the remembered commit"
# Round 1 finding F4: the stack rungs read files git ignores too (installed
# packages, build output), so a change in one makes the remembered pass stale.
mkdir -p "$d/deps/dep/lib" "$d/_build"
echo 'one' > "$d/deps/dep/lib/dep.ex"
ok "$(cd "$d" && git status --porcelain --untracked-files=all | wc -l | tr -d ' ')" "0" "git status does not list a file under an ignored folder"
run_counted "$d"
ran yes "but a new file git ignores runs them"
remembered "and the pass is then remembered with that file in place"
echo 'two, and longer' > "$d/deps/dep/lib/dep.ex"
run_counted "$d"
ran yes "an ignored file with new contents runs them"
remembered "and is then remembered"
touch -t 202001010000 "$d/deps/dep/lib/dep.ex"
run_counted "$d"
ran yes "an ignored file with the same size and a new time stamp runs them"
remembered "and is then remembered"
echo 'built' > "$d/_build/out.beam"
run_counted "$d"
ran yes "a new file in a second ignored folder runs them"
remembered "and is then remembered"
rm -f "$d/deps/dep/lib/dep.ex"
run_counted "$d"
ran yes "a removed ignored file runs them"
remembered "and is then remembered"
# A folder git ignores that is a git checkout of its own, as a package fetched
# from git is: git lists it as one entry, so its files are walked one by one.
mkdir -p "$d/deps/fetched/lib"
( cd "$d/deps/fetched" && git init -q . ) >/dev/null 2>&1
echo 'one' > "$d/deps/fetched/lib/f.ex"
run_counted "$d"
ran yes "a new ignored folder that is its own git checkout runs them"
remembered "and is then remembered"
echo 'two, and longer' > "$d/deps/fetched/lib/f.ex"
run_counted "$d"
ran yes "a changed file inside that folder runs them"
remembered "and is then remembered"
# A linked worktree inside an ignored folder is another checkout, with its own
# files and its own gate. It is not walked: a main checkout can hold dozens.
git_in worktree add -q "$d/.claude/worktrees/side" -b side HEAD
run_counted "$d"
ran yes "a new linked worktree in an ignored folder runs them once"
remembered "and is then remembered"
echo '# a change in the other checkout' >> "$d/.claude/worktrees/side/lib/a.ex"
remembered "a change inside the linked worktree leaves this checkout's pass standing"
git_in update-index --assume-unchanged lib/a.ex
echo '# hidden from git status' >> "$d/lib/a.ex"
ok "$(cd "$d" && git status --porcelain | wc -l | tr -d ' ')" "0" "git status calls a file marked assume-unchanged clean"
run_counted "$d"
ran yes "but an edit hidden that way still runs them"
git_in update-index --no-assume-unchanged lib/a.ex && git_in checkout -- lib/a.ex
remembered "unmarking the file returns to the remembered commit"
git_in update-index --skip-worktree lib/a.ex
echo '# hidden from git status' >> "$d/lib/a.ex"
run_counted "$d"
ran yes "an edit hidden with skip-worktree runs them"
git_in update-index --no-skip-worktree lib/a.ex && git_in checkout -- lib/a.ex
remembered "unmarking the file returns to the remembered commit"
git_in update-ref refs/remotes/origin/main HEAD~1
run_counted "$d"
ran yes "a moved merge base with origin/main runs them"
remembered "and the new base is then remembered"
echo 'export QUICK_TOOLCHAIN=2' > "$TMP/quick-toolchain.env"
run_counted "$d"
ran yes "a changed toolchain file runs them"
remembered "and the new toolchain is then remembered"
# The gate script: a copy with the same bytes is the same gate, one more line is not.
mkdir -p "$TMP/gatecopy"
cp "$GATE" "$(dirname "$GATE")/project_fact.py" "$TMP/gatecopy/"
GATE_UNDER_TEST="$TMP/gatecopy/hard-gate.sh"
remembered "the same gate script from another folder still matches"
echo '# one more line, as a plugin update would bring' >> "$TMP/gatecopy/hard-gate.sh"
run_counted "$d"
ran yes "a changed gate script runs them"
remembered "and the pass is then remembered for the new script"
echo '# one more line' >> "$TMP/gatecopy/project_fact.py"
run_counted "$d"
ran yes "a changed fact reader beside the gate runs them"
unset GATE_UNDER_TEST
run_counted "$d"
ran yes "and the record the changed script wrote does not count for this one"
# The environment. A variable that can point git somewhere else switches the
# reuse off; it cannot point the gate at another record.
for setting in "GIT_DIR=$d/.git" "GIT_WORK_TREE=$d" "GIT_INDEX_FILE=$d/.git/index" \
    "GIT_CONFIG_GLOBAL=/dev/null" "GIT_CONFIG_COUNT=0" "GIT_A_NAME_NOBODY_KNOWS=1"; do
  run_counted "$d" "" "$setting"
  ran yes "${setting%%=*} in the gate's environment switches the reuse off"
done
run_counted "$d" "" "GIT_EDITOR=true"
ran no "GIT_EDITOR, which moves nothing, leaves the reuse on"
ok "$(grep -o 'MASTHEAD_[A-Z_]*' "$GATE" | sort -u | tr '\n' ' ')" "MASTHEAD_DONE_GATE " "the gate reads no switch but the one that turns the whole gate off"
cp "$record" "$TMP/record-elsewhere"
rm -f "$record"
for setting in "MASTHEAD_PUSH_GATE_PASS=$TMP/record-elsewhere" "MASTHEAD_PASS_RECORD=$TMP/record-elsewhere" "PROJECT_PUSH_GATE_PASS=$TMP/record-elsewhere"; do
  run_counted "$d" "" "$setting"
  ran yes "${setting%%=*} does not point the gate at a record kept somewhere else"
  rm -f "$record"
done
run_counted "$d"
ran yes "with the record gone the slow checks run"
# A refusal is never remembered.
printf 'defmodule C do\nend\n' > "$d/lib/c.ex"
git_in add -A && git_in commit -qm "a third change"
echo 1 > "$TMP/mixcode"
run_counted "$d"
ok "$STATUS" "2" "a failing Elixir rung refuses the push"
echo 0 > "$TMP/mixcode"
run_counted "$d"
ran yes "and that refusal is not remembered as a pass"
# A commit that lands while the slow checks run: part of them saw the old files.
printf '#!/bin/sh\ncd "%s" && echo "# landed mid-run" >> lib/c.ex && git commit -qam "landed while the gate ran"\n' "$d" > "$TMP/mixhook"
chmod +x "$TMP/mixhook"
git_in commit -q --allow-empty --amend -m "a third change, reworded" && echo '# again' >> "$d/lib/c.ex" && git_in commit -qam "a fourth change"
started_on="$(cd "$d" && git rev-parse 'HEAD^{tree}')"
run_counted "$d"
ok "$STATUS" "0" "a run that a commit lands in the middle of still passes"
ok "$(grep -c "tree=$started_on " "$record")" "0" "it is not remembered for the commit it started on, which part of it never saw"
run_counted "$d"
ran yes "and it is not remembered for the commit that landed"
# An edit made and taken back while they run leaves the tree clean, so only the
# stat of the file shows it; an untracked file left behind does show.
printf '#!/bin/sh\necho scratch > "%s/left-behind.txt"\n' "$d" > "$TMP/mixhook"
chmod +x "$TMP/mixhook"
echo '# a fifth' >> "$d/lib/c.ex" && git_in commit -qam "a fifth change"
run_counted "$d"
rm -f "$d/left-behind.txt"
run_counted "$d"
ran yes "a run that leaves a new file behind is not remembered"
# Each worktree keeps its own record.
remembered "the main checkout has a remembered pass"
git_in worktree add -q "$TMP/remembered-worktree" -b second-checkout HEAD
run_counted "$TMP/remembered-worktree"
ok "$STATUS" "0" "a second worktree at the same commit passes"
ran yes "and runs the slow checks itself: the first worktree's record is not its own"
run_counted "$TMP/remembered-worktree"
ran no "then it remembers its own pass"
ok "$(cd "$TMP/remembered-worktree" && git rev-parse --git-path masthead-push-gate-pass | grep -c '/worktrees/')" "1" "in its own git directory"
# Round 1 finding F5: a submodule keeps an index of its own, where a file can be
# hidden from git status out of this checkout's sight. A checkout that has one
# never reuses a pass.
quick_repo with-submodule
mkdir -p "$d/vendor/dep/lib"
( cd "$d/vendor/dep" && git init -q . && git config user.email t@t && git config user.name t \
    && printf 'defmodule Dep do\nend\n' > lib/dep.ex && git add -A && git commit -qm "the dependency" ) >/dev/null 2>&1
git_in add vendor/dep && git_in commit -qm "a submodule"
ok "$(cd "$d" && git ls-files -s vendor/dep | cut -c1-6)" "160000" "the checkout holds a submodule"
run_counted "$d"
ok "$STATUS" "0" "the first push of a checkout with a submodule passes"
( cd "$d/vendor/dep" && git update-index --assume-unchanged lib/dep.ex ) >/dev/null 2>&1
echo '# hidden from git status' >> "$d/vendor/dep/lib/dep.ex"
ok "$(cd "$d" && git status --porcelain --ignore-submodules=none | wc -l | tr -d ' ')" "0" "git status calls an edit hidden inside the submodule clean"
run_counted "$d"
ran yes "but an edit hidden inside a submodule still runs them"
( cd "$d/vendor/dep" && git update-index --no-assume-unchanged lib/dep.ex && git checkout -- lib/dep.ex ) >/dev/null 2>&1
run_counted "$d"
run_counted "$d"
ran yes "a checkout with a submodule runs them every time"
# With no origin/main there is no merge base, so nothing is remembered.
d="$(newrepo no-base)"
mkdir -p "$d/lib"
: > "$d/mix.exs"
git_in add -A && git_in commit -qm base
printf 'defmodule A do\nend\n' > "$d/lib/a.ex"
run_counted "$d"
run_counted "$d"
ran yes "a checkout with no origin/main runs the slow checks every time"

echo "22. a tracked package.json root runs its test script on push"
d="$(newrepo node-tracked)"
mkdir -p "$d/web"
printf '%s\n' '{"name":"w","scripts":{"test":"touch ran-here"}}' > "$d/web/package.json"
( cd "$d" && git add web/package.json && git commit -qm base ) >/dev/null 2>&1
echo 'const a = 1;' > "$d/web/a.js"
run_gate "$d"
if [ -e "$d/web/ran-here" ]; then pass=$((pass + 1)); echo "  ok: the tracked root's test script ran"; else fail=$((fail + 1)); echo "  FAIL: the tracked root's test script did not run (stderr: $(printf '%s' "$ERR" | head -3 | tr '\n' ' '))" >&2; fi

echo "23. an untracked folder's package.json is not a root, so its test script never runs"
d="$(newrepo node-untracked)"
( cd "$d" && echo "# notes" > README.md && git add README.md && git commit -qm base ) >/dev/null 2>&1
mkdir -p "$d/scratch"
printf '%s\n' '{"name":"s","scripts":{"test":"touch ran-here"}}' > "$d/scratch/package.json"
echo 'const a = 1;' > "$d/scratch/a.js"
run_gate "$d"
if [ -e "$d/scratch/ran-here" ]; then fail=$((fail + 1)); echo "  FAIL: an untracked folder's test script ran on push" >&2; else pass=$((pass + 1)); echo "  ok: the untracked folder's test script did not run"; fi
contains "$ERR" "no package.json above them" "it says the node rung found no tracked root"

echo "24. a repo whose settings still name the removed check pushes, and the gate never mentions it"
d="$(newrepo old-setting)"
mkdir -p "$d/.claude"
printf '{"env":{"%s":"bad.yaml"}}\n' "PROJECT_ABIL""ITIES" > "$d/.claude/settings.json"
echo 'lines: [' > "$d/bad.yaml"
run_gate "$d"
ok "$STATUS" "0" "the old setting does not stop a push"
ok "$(printf '%s' "$ERR" | grep -ci "abil""ities")" "0" "the gate says nothing about it"

echo ""
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ] || exit 1
