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
  if printf '%s' "$1" | grep -q "$2"; then
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

echo ""
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ] || exit 1
