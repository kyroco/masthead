#!/usr/bin/env bash
# Proves gate-discovery judges every searchable rg, grep, Grep and Glob, reads
# the pattern out of a shell command correctly, leaves alone what is not a
# codebase search, and nudges once on an allowed search without deciding.
#
# The real judge asks the code index, so the hook runs from a scratch copy with a stub
# judge beside it. The stub answers SEARCHABLE only for the names below and logs
# every pattern it is handed, so each case also proves WHICH pattern the gate
# extracted, not only whether it refused.
#
#   bash .claude/hooks/proof/gate-discovery-bash-selftest.sh
set -uo pipefail
HOOKS="${GATE_HOOKS_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$HOOKS/engram-protocol.sh" "$HOOKS/shell-search-pattern.py" "$WORK/"
cat > "$WORK/korium-index-judge.py" <<'PY'
#!/usr/bin/env python3
import json, os, sys
req = json.load(sys.stdin)
with open(os.environ["JUDGE_LOG"], "a") as f:
    f.write(req["tool"] + "\t" + req["pattern"] + "\t" + req["path"] + "\n")
symbols = {"def fuse_scores", "fuse_scores", "handle_call", "def fuse",
           "def (a|b)", "defmodule X", "fuse_scores$", "workflow_call"}
if req["pattern"] == "judge_is_down":
    print("UNKNOWN")
else:
    print("SEARCHABLE" if req["pattern"] in symbols else "NOT_SEARCHABLE")
PY
chmod +x "$WORK/korium-index-judge.py"
export JUDGE_LOG="$WORK/judge.log"

pass=0; fail=0
ok()  { pass=$((pass + 1)); printf 'ok   %-60s %s\n' "$1" "$2"; }
bad() { fail=$((fail + 1)); printf 'FAIL %-60s %s\n' "$1" "$2" >&2; }

# A code_locate answer recorded through the real marker, mark-codesearch.
# $2: hits | empty ; $3: fresh | stale ; $4: the query (default fuse_scores)
record_search() {
  local sid="$1" results='[]' stale=false query="${4:-fuse_scores}"
  [ "$2" = hits ] && results='[{"rel_path":"lib/x.ex","start_line":1,"end_line":9}]'
  [ "$3" = stale ] && stale=true
  jq -n --arg s "$sid" --argjson r "$results" --argjson st "$stale" --arg q "$query" '{session_id:$s,
    tool_name:"mcp__claude_ai_korium__code_locate", tool_input:{query:$q},
    tool_response:[{type:"text", text:({results:$r, indexed_git_sha:"abc",
      staleness:{stale:$st}} | tojson)}]}' \
    | bash "$WORK/engram-protocol.sh" mark-codesearch >/dev/null 2>&1
}

# One gate call. Prints deny, nudge (context, no decision) or allow (nothing).
gate() {
  local sid="$1" tool="$2" input="$3" out
  out="$(jq -n --arg s "$sid" --arg t "$tool" --argjson i "$input" \
    '{session_id:$s, tool_name:$t, tool_input:$i}' \
    | bash "$WORK/engram-protocol.sh" gate-discovery 2>/dev/null)"
  if printf '%s' "$out" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1; then
    echo deny
  elif printf '%s' "$out" | jq -e '.hookSpecificOutput.additionalContext and (.hookSpecificOutput | has("permissionDecision") | not)' >/dev/null 2>&1; then
    echo nudge
  elif [ -z "$out" ]; then
    echo allow
  else
    echo "other: $out"
  fi
}

# name, want (deny|nudge|allow), judged pattern ("-" = judge not asked), tool,
# input json, [setup: hits-fresh | hits-stale | empty-fresh | empty-stale]
run() {
  local name="$1" want="$2" want_pat="$3" tool="$4" input="$5" setup="${6:-}"
  local sid="gdtest-$RANDOM$RANDOM" got judged
  : > "$JUDGE_LOG"
  [ -n "$setup" ] && record_search "$sid" "${setup%-*}" "${setup#*-}"
  got="$(gate "$sid" "$tool" "$input")"
  judged="$(cut -f2 "$JUDGE_LOG" | head -1)"; [ -n "$judged" ] || judged="-"
  if [ "$got" = "$want" ] && [ "$judged" = "$want_pat" ]; then
    ok "$name" "$got, judged [$judged]"
  else
    bad "$name" "got $got judged [$judged], want $want judged [$want_pat]"
  fi
  rm -rf "${TMPDIR:-/tmp}/claude-engram/$sid"
}
sh() { jq -n --arg c "$1" '{command:$c}'; }

echo "== the cases the task names =="
run "Bash rg for a function name is refused" deny "def fuse_scores" Bash \
  "$(sh 'rg -n "def fuse_scores" products/apps')"
run "Bash rg for a YAML key is refused (the index holds YAML)" deny "workflow_call" Bash \
  "$(sh 'rg -n workflow_call .github/workflows')"
run "Bash rg for a value passes, with the nudge" nudge "runs-on: ubuntu" Bash \
  "$(sh 'rg -n "runs-on: ubuntu" .github/workflows')"
run "a piped grep -q on command output passes, unjudged" allow "-" Bash \
  "$(sh 'git log --oneline | grep -q fuse_scores')"

echo "== every search is judged; stale is not a pass =="
run "still refused after a stale code_locate" deny "fuse_scores" Bash \
  "$(sh 'rg fuse_scores products/')" empty-stale
run "passes after a fresh code_locate found nothing" allow "fuse_scores" Bash \
  "$(sh 'rg fuse_scores products/')" empty-fresh
run "passes after a fresh code_locate found it (callers)" allow "fuse_scores" Bash \
  "$(sh 'rg fuse_scores products/')" hits-fresh
sid="gdtest-other-$RANDOM"; : > "$JUDGE_LOG"
record_search "$sid" empty fresh "test user call"
got="$(gate "$sid" Bash "$(sh 'rg handle_call products/')")"
[ "$got" = deny ] && ok "a lookup of another name does not unlock it" "$got" \
  || bad "a lookup of another name does not unlock it" "$got"
rm -rf "${TMPDIR:-/tmp}/claude-engram/$sid"
sid="gdtest-cli-$RANDOM"; : > "$JUDGE_LOG"
jq -n --arg s "$sid" '{session_id:$s, tool_name:"Bash",
  tool_input:{command:"korium-cli search handle_call"}}' \
  | bash "$WORK/engram-protocol.sh" mark-codesearch >/dev/null 2>&1
got="$(gate "$sid" Bash "$(sh 'rg handle_call products/')")"
[ "$got" = allow ] && ok "a korium-cli search counts as the lookup" "$got" \
  || bad "a korium-cli search counts as the lookup" "$got"
rm -rf "${TMPDIR:-/tmp}/claude-engram/$sid"

echo "== a judge that is down =="
# Since 2026-10-09 a judge that cannot be read refuses (the way through is a
# fresh lookup), so the second search is denied; it must still cost no second
# judge call.
sid="gdtest-down-$RANDOM"; : > "$JUDGE_LOG"
gate "$sid" Bash "$(sh 'rg judge_is_down lib/')" >/dev/null
got="$(gate "$sid" Bash "$(sh 'rg fuse_scores lib/')")"
calls="$(grep -c . "$JUDGE_LOG")"
if [ "$got" = deny ] && [ "$calls" = 1 ]; then
  ok "a judge that is down refuses, and is not asked again for five minutes" "$got, $calls call"
else
  bad "a judge that is down refuses, and is not asked again for five minutes" "$got, $calls calls"
fi
rm -rf "${TMPDIR:-/tmp}/claude-engram/$sid"

echo "== the nudge =="
sid="gdtest-nudge-$RANDOM"; : > "$JUDGE_LOG"
first="$(gate "$sid" Bash "$(sh 'rg -n TODO docs/')")"
second="$(gate "$sid" Bash "$(sh 'rg -n FIXME docs/')")"
if [ "$first" = nudge ] && [ "$second" = allow ]; then
  ok "nudges on the first allowed search only, with no decision" "$first then $second"
else
  bad "nudges on the first allowed search only, with no decision" "$first then $second"
fi
rm -rf "${TMPDIR:-/tmp}/claude-engram/$sid"

echo "== one model call per distinct search =="
sid="gdtest-cache-$RANDOM"; : > "$JUDGE_LOG"
gate "$sid" Bash "$(sh 'rg fuse_scores products/')" >/dev/null
again="$(gate "$sid" Bash "$(sh 'rg fuse_scores products/')")"
calls="$(grep -c . "$JUDGE_LOG")"
if [ "$again" = deny ] && [ "$calls" = 1 ]; then
  ok "a repeated search reads the cached verdict" "deny, $calls judge call"
else
  bad "a repeated search reads the cached verdict" "$again, $calls judge calls"
fi
rm -rf "${TMPDIR:-/tmp}/claude-engram/$sid"

echo "== how the pattern is found =="
run "grep -e value is the pattern" deny "fuse_scores" Bash "$(sh 'grep -rn -e fuse_scores products/')"
run "--regexp= value is the pattern" deny "fuse_scores" Bash "$(sh 'rg --regexp=fuse_scores products/')"
run "grep -r takes no value" deny "def fuse" Bash "$(sh 'grep -r "def fuse" products/')"
run "grep -E takes no value" deny "def (a|b)" Bash "$(sh 'grep -E "def (a|b)" lib/x.ex')"
run "a grouped -nC 3 takes 3" deny "handle_call" Bash "$(sh 'rg -nC 3 handle_call products/')"
run "a grouped -nt takes the type" deny "defmodule X" Bash "$(sh "rg -nt elixir 'defmodule X' .")"
run "option values are not the pattern" deny "handle_call" Bash \
  "$(sh 'rg -t elixir -g "*.ex" -C 3 handle_call products/')"
run "a pattern ending in \$ keeps it" deny "fuse_scores\$" Bash "$(sh "rg 'fuse_scores\$' lib")"
run "a quoted || is a pattern, not an operator" nudge "||" Bash "$(sh "rg -F '||' lib")"
run "rg --color takes its value" deny "fuse_scores" Bash "$(sh 'rg --color never fuse_scores src')"
run "a backslash reaches the judge unchanged" nudge 'def\s+fuse' Bash "$(sh "rg 'def\\s+fuse' lib")"
run "grep -f reads patterns from a file, nothing to judge" allow "-" Bash "$(sh 'grep -f pats.txt src/')"

echo "== where a search can sit =="
run "after cd &&" deny "handle_call" Bash "$(sh 'cd products && rg handle_call apps/')"
run "on the second line" deny "handle_call" Bash "$(sh $'cd products\nrg handle_call apps/')"
run "inside \$( )" deny "fuse_scores" Bash "$(sh 'n=$(rg -c fuse_scores products/); echo $n')"
run "inside \"\$( )\"" deny "fuse_scores" Bash "$(sh 'echo "$(rg -c fuse_scores products/)"')"
run "inside backticks" deny "fuse_scores" Bash "$(sh 'n=`rg -c fuse_scores products/`')"
run "after time" deny "fuse_scores" Bash "$(sh 'time rg fuse_scores products/')"
run "after env" deny "fuse_scores" Bash "$(sh 'env rg fuse_scores products/')"
run "after an assignment" deny "fuse_scores" Bash "$(sh 'LC_ALL=C rg fuse_scores products/')"
run "in a for loop" deny "fuse_scores" Bash "$(sh 'for d in a b; do rg fuse_scores $d; done')"
run "after xargs -n 1" deny "fuse_scores" Bash "$(sh 'ls | xargs -n 1 rg fuse_scores')"
run "after xargs with several options" deny "fuse_scores" Bash "$(sh 'ls | xargs -I{} -n 1 -P 4 rg fuse_scores {}')"
run "after if" deny "fuse_scores" Bash "$(sh 'if rg -q fuse_scores lib; then echo y; fi')"
run "after timeout" deny "fuse_scores" Bash "$(sh 'timeout 5 rg fuse_scores lib')"
run "git grep" deny "fuse_scores" Bash "$(sh 'git grep -n fuse_scores')"
run "a full path to rg" deny "fuse_scores" Bash "$(sh '/opt/homebrew/bin/rg fuse_scores products/')"
run "a # inside a word is not a comment" deny "handle_call" Bash \
  "$(sh 'git log --format=%h#%s -1; rg handle_call lib')"
run "a redirection before the pattern" deny "fuse_scores" Bash "$(sh 'rg 2>/dev/null fuse_scores products/')"
run "a spaced redirection before the pattern" deny "fuse_scores" Bash "$(sh 'rg 2> /dev/null fuse_scores products/')"
run "2>&1 after the search" deny "fuse_scores" Bash "$(sh 'rg fuse_scores products/ 2>&1 | head')"

echo "== what is not a codebase search =="
run "a command that is not a search" allow "-" Bash "$(sh 'ls -la products/apps')"
run "grep named in a commit message" allow "-" Bash "$(sh 'git commit -m "grep fuse_scores"')"
run "a grep in a subshell after a pipe" allow "-" Bash "$(sh 'cat x | (grep fuse_scores)')"
run "rg --files lists files" allow "-" Bash "$(sh 'rg --files products/')"
run "a heredoc body is text" allow "-" Bash \
  "$(sh $'cat <<EOF > /tmp/x\nfoo; grep defmodule Engram.Foo\nEOF')"
run "an unclosed quote fails open" allow "-" Bash "$(sh 'rg "fuse_scores products/')"

echo "== unchanged =="
run "the Grep tool still refuses" deny "fuse_scores" Grep '{"pattern":"fuse_scores"}'
MASTHEAD_CODE_GATE=off run "the operator escape still passes" allow "-" Bash "$(sh 'rg fuse_scores products/')"

echo "== the file filter reaches the judge =="
sid="gdtest-filter-$RANDOM"; : > "$JUDGE_LOG"
gate "$sid" Bash "$(sh "rg -g '*.tf' handle_call infra/")" >/dev/null
judged_path="$(cut -f3 "$JUDGE_LOG" | head -1)"
if [ "$judged_path" = "infra/ (files: *.tf)" ]; then
  ok "-g reaches the judge with the path" "[$judged_path]"
else
  bad "-g reaches the judge with the path" "[$judged_path]"
fi
rm -rf "${TMPDIR:-/tmp}/claude-engram/$sid"

echo; echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
