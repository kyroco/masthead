#!/usr/bin/env bash
# bash-scope-diagnoser-test.sh -- behavioral test for hooks/bash-scope-diagnoser.sh.
#
# The gate's claim has two halves and this test asserts both: The diagnoser can still
# reproduce a failure (run the project's tests, read history, inspect files, hit
# the app on localhost, keep scratch output in /tmp), and it cannot change the
# tree or git state, reach the network, or read credentials from Bash. It also
# checks the gate is wired on by default in both places a host reads hooks from.
#
# Usage:   bash hooks/tests/bash-scope-diagnoser-test.sh     (no args; self-locating)
# Exit:    0 = all assertions pass | 1 = one or more failures
#
# Portability: BSD/macOS-safe, bash 3.2. Needs jq (the hook does too).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# hooks/tests -> the config folder: ~/.claude on the Mac, the claude-config
# clone in a cloud session.
WIRING_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PERSONA="$WIRING_DIR/agents/diagnoser.md"
SETTINGS="$SCRIPT_DIR/../hooks.json"
HOOK="$SCRIPT_DIR/../bash-scope-diagnoser.sh"

if ! command -v jq >/dev/null 2>&1; then
  echo "FAIL: jq not installed; the hook requires it and fails closed without it." >&2
  exit 1
fi

FAILURES=0
fail() { echo "FAIL: $1" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "PASS: $1"; }

WORK="$(mktemp -d)"
LINK="/tmp/diagnoser-guard-link-$$"
trap 'rm -rf "$WORK"; rm -f "$LINK"' EXIT
mkdir -p "$WORK/lib"
echo x > "$WORK/lib/a.ex"

# run_case <expected-rc> <label> <command-string>
run_case() {
  local want="$1" label="$2" cmd="$3" payload rc
  payload="$(jq -nc --arg c "$cmd" --arg d "$WORK" '{tool_name:"Bash", cwd:$d, tool_input:{command:$c}}')"
  printf '%s' "$payload" | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq "$want" ]; then
    pass "$label (rc=$rc)"
  else
    fail "$label: got rc=$rc, expected $want. Command was: $cmd"
  fi
}

# --- wiring: settings.json only ------------------------------------------------
# Under the old persona model this gate was wired twice, in the agent's own
# frontmatter and again project-wide in settings.json. It only ever needed the
# second: a hook in settings.json fires for every tool call in the session AND
# inside every subagent, and the payload carries agent_type, which is what this
# guard scopes on. So the agent file must carry no hooks block at all, and
# settings.json must pass --project-wide.
if jq -e '.hooks.PreToolUse[] | select(.matcher == "Bash") | .hooks[].command | select(test("bash-scope-diagnoser.sh\"? --project-wide$"))' \
     "$SETTINGS" >/dev/null 2>&1; then
  pass "settings.json wires the guard project-wide on a PreToolUse Bash matcher"
else
  fail "settings.json does not wire bash-scope-diagnoser.sh --project-wide on PreToolUse Bash"
fi
if awk '/^---$/{n++; next} n==1' "$PERSONA" | grep -q '^hooks:'; then
  fail "agents/diagnoser.md carries a hooks block, which duplicates the settings.json wiring"
else
  pass "agents/diagnoser.md carries no hooks block; the project wiring covers it"
fi

# --- allowed: reproducing a failure ---------------------------------------------
run_case 0 "mix test on one test is allowed" "mix test test/a_test.exs:12"
run_case 0 "an allowlisted setting before the runner is allowed" "MIX_ENV=test mix test"
run_case 0 "timeout around the runner is allowed" "timeout 120 mix test"
run_case 0 "npm test is allowed" "npm test"
run_case 0 "npm run test:unit is allowed" "npm run test:unit"
run_case 0 "pytest is allowed" "pytest -x tests/test_a.py"
run_case 0 "python -m pytest is allowed" "python3 -m pytest -k name"
run_case 0 "cargo test is allowed" "cargo test"
run_case 0 "go test is allowed" "go test ./..."
run_case 0 "bundle exec rspec is allowed" "bundle exec rspec spec/a_spec.rb"
run_case 0 "node --test is allowed" "node --test test/a.test.js"
run_case 0 "runner output piped to tail is allowed" "mix test 2>&1 | tail -40"
run_case 0 "runner output kept in /tmp is allowed" "mix test > /tmp/diagnoser-run.txt 2>&1"
run_case 0 "runner output discarded is allowed" "mix test 2>/dev/null"
run_case 0 "curl to the local app is allowed" "curl -i http://localhost:4000/health"
run_case 0 "a curl POST with a header to 127.0.0.1 is allowed" "curl -s -X POST -H 'Accept:application/json' -d '{\"a\":1}' http://127.0.0.1:4000/api"

# --- allowed: read-only inspection ----------------------------------------------
run_case 0 "git status is allowed" "git status"
run_case 0 "git log is allowed" "git log --oneline -20"
run_case 0 "a git range is allowed" "git diff HEAD~1..HEAD"
run_case 0 "git blame is allowed" "git blame lib/a.ex"
run_case 0 "git show of a file at a revision is allowed" "git show abc123:lib/a.ex"
run_case 0 "rg with a quoted pattern is allowed" "rg -n 'foo.*bar' lib"
run_case 0 "grep of a named file is allowed" "grep -n pattern lib/a.ex"
run_case 0 "cat of a source file is allowed" "cat lib/a.ex"
run_case 0 "an absolute path inside the project is allowed" "head -50 $WORK/lib/a.ex"
run_case 0 "find with a quoted name pattern is allowed" "find lib -name '*.ex'"
run_case 0 "cd then ls is allowed" "cd lib && ls -la"

# --- denied: changing files -------------------------------------------------------
run_case 2 "rm is denied" "rm -rf lib"
run_case 2 "mv is denied" "mv lib/a.ex lib/b.ex"
run_case 2 "cp is denied" "cp lib/a.ex lib/b.ex"
run_case 2 "tee is denied" "mix test | tee out.txt"
run_case 2 "sed -i is denied" "sed -i s/a/b/ lib/a.ex"
run_case 2 "a redirect into the tree is denied" "echo x > lib/a.ex"
run_case 2 "an append into the tree is denied" "mix test >> results.txt"
run_case 2 "a redirect glued to a word is denied" "echo x>lib/a.ex"
run_case 2 "a redirect outside the project and /tmp is denied" "echo x > /Users/someone/notes.txt"
run_case 2 "a redirect escaping /tmp by traversal is denied" "mix test > /tmp/../etc/x"
ln -s "$WORK/lib/a.ex" "$LINK"
run_case 2 "a redirect into a /tmp symlink that points at the tree is denied" "echo x > $LINK"
run_case 2 "find -delete is denied" "find . -name '*.beam' -delete"
run_case 2 "a quoted find -delete is denied" "find . '-delete'"
run_case 2 "find -exec is denied" "find . -exec rm x"
run_case 2 "sort -o is denied" "sort -o lib/a.ex lib/a.ex"
run_case 2 "mix format without --check-formatted is denied" "mix format"

# --- denied: git state changes ------------------------------------------------
run_case 2 "git commit is denied" "git commit -m x"
run_case 2 "git push is denied" "git push origin main"
run_case 2 "git reset is denied" "git reset --hard HEAD~1"
run_case 2 "git checkout is denied" "git checkout main"
run_case 2 "git switch is denied" "git switch main"
run_case 2 "git stash is denied" "git stash"
run_case 2 "git clean is denied" "git clean -fd"
run_case 2 "git bisect is denied" "git bisect start"
run_case 2 "git -C to steer another repository is denied" "git -C /tmp status"
run_case 2 "git log --output is denied" "git log --output=/tmp/x"

# --- denied: the network ------------------------------------------------------
run_case 2 "curl to another host is denied" "curl https://example.com/x"
run_case 2 "curl with a userinfo trick is denied" "curl http://localhost@example.com/"
run_case 2 "curl to a lookalike host is denied" "curl http://127.0.0.1.example.com/"
run_case 2 "curl following redirects is denied" "curl -L http://localhost:4000/"
run_case 2 "curl writing a file is denied" "curl -o /tmp/x http://localhost:4000/"
run_case 2 "curl posting a file is denied" "curl -d @lib/a.ex http://localhost:4000/"
run_case 2 "curl through a proxy is denied" "curl -x http://example.com:8080 http://localhost/"
run_case 2 "wget is denied" "wget http://localhost:4000/"
run_case 2 "nc is denied" "nc example.com 4444"
run_case 2 "ssh is denied" "ssh host"
run_case 2 "scp is denied" "scp lib/a.ex host:/tmp"
run_case 2 "a pipe into a shell is denied" "curl -s http://localhost:4000/ | sh"
run_case 2 "mix deps.get is denied (it fetches)" "mix deps.get"
run_case 2 "npm install is denied" "npm install"
run_case 2 "npx is denied" "npx some-package"

# --- denied: credential reads -----------------------------------------------------
run_case 2 "cat .env is denied" "cat .env"
run_case 2 "cat of a nested .env file is denied" "cat config/.env.local"
run_case 2 "a quoted .env is denied" "cat '.e'nv"
run_case 2 "a globbed .env is denied" "cat .e*"
run_case 2 "cloud credentials are denied" "cat /Users/someone/.aws/credentials"
run_case 2 "a home-relative path is denied" "cat ~/.pgpass"
run_case 2 "a recursive grep of a home directory is denied" "grep -r AKIA /Users/someone"
run_case 2 "an ssh key is denied" "head id_ed25519"
run_case 2 "a committed .env read through git show is denied" "git show HEAD:.env"
run_case 2 "env is denied" "env"
run_case 2 "printenv is denied" "printenv"
run_case 2 "path traversal is denied" "cat lib/../../secret.txt"
run_case 2 "a recursive grep is denied (it would print a .env it was never given)" "grep -rn API_KEY ."
run_case 2 "grep --recursive is denied" "grep --recursive API_KEY ."
run_case 2 "rg over hidden files is denied" "rg --hidden API_KEY"
run_case 2 "rg -uu is denied" "rg -uu API_KEY"
run_case 2 "a recursive diff is denied" "diff -r lib /tmp/x"

# --- denied: what the guard cannot check -------------------------------------------
run_case 2 "command substitution is denied" "mix test \$(curl -s https://example.com)"
run_case 2 "backticks are denied" "cat \`echo lib/a.ex\`"
run_case 2 "a variable is denied" "cat \$HOME/.netrc"
run_case 2 "a variable in double quotes is denied" "echo \"\$HOME\""
run_case 2 "a subshell is denied" "(cd lib && rm a.ex)"
run_case 2 "an input redirect is denied" "mix test < /tmp/x"
run_case 2 "a separator hidden in quotes is denied" "find . -name 'a|ls' -delete"
run_case 2 "an unterminated quote is denied" "cat 'lib/a.ex"
run_case 2 "a backslash escape is denied" "c\\url https://example.com"
run_case 2 "bash -c is denied" "bash -c whoami"
run_case 2 "a script run by path is denied" "./scripts/run.sh"
run_case 2 "node -e is denied" "node --test -e 1"
run_case 2 "python -c is denied" "python3 -c 1"
run_case 2 "an unlisted setting is denied" "PATH=/tmp mix test"
run_case 2 "an allowed command chained to a denied one is denied" "mix test && rm -rf lib"

# --- scoping and the escape hatch ------------------------------------------------
printf '%s' '{"tool_name":"Read","tool_input":{"file_path":".env"}}' | bash "$HOOK" >/dev/null 2>&1
[ $? -eq 0 ] && pass "a non-Bash tool call passes through (rc=0)" \
  || fail "a non-Bash tool call should pass through untouched"

# scoped <expected-rc> <label> <payload> [--project-wide]
scoped() {
  local want="$1" label="$2" payload="$3" rc
  shift 3
  printf '%s' "$payload" | bash "$HOOK" "$@" >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq "$want" ]; then pass "$label (rc=$rc)"; else fail "$label: got rc=$rc, expected $want"; fi
}
RM='"tool_name":"Bash","tool_input":{"command":"rm -rf lib"}'
# Project-wide (settings.json): only a payload naming The diagnoser is gated.
scoped 0 "project-wide: the main session, which carries no agent identity, keeps its Bash" "{$RM}" --project-wide
scoped 0 "project-wide: a background job session (agent_name claude) keeps its Bash" "{$RM,\"agent_name\":\"claude\"}" --project-wide
scoped 0 "project-wide: another agent's Bash passes through" "{$RM,\"agent_type\":\"thiago\",\"agent_name\":\"thiago\"}" --project-wide
scoped 2 "project-wide: The diagnoser dispatched under a task label is gated on her type" "{$RM,\"agent_type\":\"diagnoser\",\"agent_name\":\"hunt-1\"}" --project-wide
scoped 2 "project-wide: a payload carrying only subagent_type diagnoser is gated" "{$RM,\"subagent_type\":\"diagnoser\"}" --project-wide
scoped 2 "project-wide: a payload named diagnoser is gated" "{$RM,\"agent_name\":\"diagnoser\"}" --project-wide
scoped 2 "project-wide: the reader helper is gated the same way" "{$RM,\"agent_type\":\"reader\",\"agent_name\":\"look-1\"}" --project-wide
scoped 2 "project-wide: a payload carrying only subagent_type reader is gated" "{$RM,\"subagent_type\":\"reader\"}" --project-wide
# Claude Code names a plugin's agent <plugin>:<agent>.
scoped 2 "project-wide: the plugin's diagnoser (masthead:diagnoser) is gated" "{$RM,\"agent_type\":\"masthead:diagnoser\"}" --project-wide
scoped 2 "project-wide: the plugin's reader (masthead:reader) is gated" "{$RM,\"subagent_type\":\"masthead:reader\"}" --project-wide
scoped 2 "project-wide: any plugin's reader is gated, as the reviewer guard does" "{$RM,\"agent_type\":\"otherplugin:reader\"}" --project-wide
# Frontmatter (no argument): the host runs it only inside The diagnoser, so no name lets a call out.
scoped 2 "frontmatter: The diagnoser under a task label is gated" "{$RM,\"agent_type\":\"diagnoser\",\"agent_name\":\"hunt-1\"}"
scoped 2 "frontmatter: a payload with no identity is gated" "{$RM}"

# The reader's frontmatter keeps every file-writing tool and Agent denied; this
# fence only covers its shell.
READER="$WIRING_DIR/agents/reader.md"
READER_DENY="$(sed -n 's/^disallowedTools: //p' "$READER" | tr ',' '\n' | tr -d ' ')"
for tool in Write Edit MultiEdit NotebookEdit Agent; do
  printf '%s\n' "$READER_DENY" | grep -qx "$tool" && pass "reader.md denies $tool" \
    || fail "reader.md no longer denies $tool"
done

printf '%s' '{"tool_name":"Bash","tool_input":{}}' | bash "$HOOK" >/dev/null 2>&1
[ $? -eq 2 ] && pass "a Bash call with no command string is denied" \
  || fail "a Bash call with no readable command should be denied"

printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf lib"}}' | DIAGNOSER_BASH_GATE=off bash "$HOOK" >/dev/null 2>&1
[ $? -eq 0 ] && pass "DIAGNOSER_BASH_GATE=off stands the gate down (the installer's explicit choice)" \
  || fail "DIAGNOSER_BASH_GATE=off should stand the gate down"

echo "---"
if [ "$FAILURES" -eq 0 ]; then
  echo "BASH-SCOPE-DIAGNOSER OK: all assertions pass"
  exit 0
else
  echo "BASH-SCOPE-DIAGNOSER FAILED: $FAILURES assertion(s)"
  exit 1
fi
