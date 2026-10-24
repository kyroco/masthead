#!/usr/bin/env bash
# run-sh-test.sh: the install options decide which hooks run.sh starts, and an unset option keeps a hook on.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN="$HERE/../run.sh"
pass=0; fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL  $1" >&2; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export TMPDIR="$T"
export CLAUDE_PLUGIN_ROOT="$(cd "$HERE/../.." && pwd)"
edit='{"session_id":"run-sh-test","cwd":"'"$T"'","tool_name":"Edit","tool_input":{"file_path":"'"$T"'/a.py"}}'
fetch='{"session_id":"run-sh-test","tool_name":"WebFetch","tool_input":{"url":"https://pastebin.com/raw/x"}}'
commit='{"session_id":"run-sh-test","tool_name":"Bash","tool_input":{"command":"git commit -m \"x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\""}}'

decision() { printf '%s' "$1" | grep -q '"permissionDecision": *"deny"' && echo deny || echo allow; }

# The Korium gates: off by default in the plugin, on when the option says so, on when nothing says.
out="$(printf '%s' "$edit" | CLAUDE_PLUGIN_OPTION_KORIUM=false bash "$RUN" engram-protocol.sh gate-edit 2>&1)"
[ "$(decision "$out")" = allow ] && ok || bad "korium off: gate-edit should stand aside, got: $out"
out="$(printf '%s' "$edit" | CLAUDE_PLUGIN_OPTION_KORIUM=true bash "$RUN" engram-protocol.sh gate-edit 2>&1)"
[ "$(decision "$out")" = deny ] && ok || bad "korium on: gate-edit should refuse the first edit, got: $out"
out="$(printf '%s' "$edit" | env -u CLAUDE_PLUGIN_OPTION_KORIUM bash "$RUN" engram-protocol.sh gate-edit 2>&1)"
[ "$(decision "$out")" = deny ] && ok || bad "korium unset: gate-edit should run as it always did, got: $out"

# The commit gate: on by default, off when the option says so.
out="$(printf '%s' "$commit" | env -u CLAUDE_PLUGIN_OPTION_STRICT_COMMITS bash "$RUN" commit-attribution-gate.py 2>&1)"
[ "$(decision "$out")" = deny ] && ok || bad "strict commits unset: an AI co-author line should be refused, got: $out"
out="$(printf '%s' "$commit" | CLAUDE_PLUGIN_OPTION_STRICT_COMMITS=false bash "$RUN" commit-attribution-gate.py 2>&1)"
[ "$(decision "$out")" = allow ] && ok || bad "strict commits off: the gate should stand aside, got: $out"

# A safety gate has no option and always runs.
out="$(printf '%s' "$fetch" | CLAUDE_PLUGIN_OPTION_KORIUM=false CLAUDE_PLUGIN_OPTION_STRICT_COMMITS=false bash "$RUN" untrusted-domain-deny.py 2>&1)"
[ "$(decision "$out")" = deny ] && ok || bad "a paste site should be refused whatever the options say, got: $out"

# With Korium on but no korium-cli on the machine, the code index gate stands aside.
grep_call='{"session_id":"run-sh-test","cwd":"'"$T"'","tool_name":"Grep","tool_input":{"pattern":"SomeModuleName","path":"'"$T"'"}}'
mkdir -p "$T/emptybin"
out="$(printf '%s' "$grep_call" | env PATH="$T/emptybin:/usr/bin:/bin" HOME="$T" CLAUDE_PLUGIN_OPTION_KORIUM=true bash "$RUN" engram-protocol.sh gate-discovery 2>&1)"
[ "$(decision "$out")" = allow ] && ok || bad "no korium-cli: the code gate should stand aside, got: $out"

# An unknown hook name is a no-op, and no name at all is a no-op.
printf '%s' "$edit" | bash "$RUN" no-such-hook.py >/dev/null 2>&1 && ok || bad "an unknown hook name should exit 0"
printf '%s' "$edit" | bash "$RUN" >/dev/null 2>&1 && ok || bad "no hook name should exit 0"

# An off switch that the project's own settings env block sets is ignored (a cloned repo cannot switch a check off).
mkdir -p "$T/proj/.claude"
printf '%s\n' '{"env":{"CLAUDE_PLUGIN_OPTION_STRICT_COMMITS":"false","MASTHEAD_DONE_GATE":"off"}}' > "$T/proj/.claude/settings.json"
out="$(printf '%s' "$commit" | CLAUDE_PROJECT_DIR="$T/proj" CLAUDE_PLUGIN_OPTION_STRICT_COMMITS=false bash "$RUN" commit-attribution-gate.py 2>&1)"
[ "$(decision "$out")" = deny ] && ok || bad "an off switch set by the project's settings env should be ignored, got: $out"
out="$(printf '%s' "$commit" | CLAUDE_PROJECT_DIR="$T/other" CLAUDE_PLUGIN_OPTION_STRICT_COMMITS=false bash "$RUN" commit-attribution-gate.py 2>&1)"
[ "$(decision "$out")" = allow ] && ok || bad "an off switch the project does not set still counts, got: $out"

# The code index is its own option: with Korium on and the index off, the code gates and the index refresh stand aside.
mkdir -p "$T/stubbin"
printf '#!/bin/sh\ntouch "%s/korium-cli-ran"\necho "[]"\n' "$T" > "$T/stubbin/korium-cli"; chmod +x "$T/stubbin/korium-cli"
out="$(printf '%s' "$grep_call" | env PATH="$T/stubbin:$PATH" HOME="$T" CLAUDE_PLUGIN_OPTION_KORIUM=true CLAUDE_PLUGIN_OPTION_CODE_INDEX=false bash "$RUN" engram-protocol.sh gate-discovery 2>&1)"
[ "$(decision "$out")" = allow ] && [ ! -e "$T/korium-cli-ran" ] && ok || bad "code index off: gate-discovery should stand aside and never call korium-cli, got: $out"
out="$(printf '%s' "$grep_call" | env PATH="$T/stubbin:$PATH" HOME="$T" CLAUDE_PLUGIN_OPTION_KORIUM=true CLAUDE_PLUGIN_OPTION_CODE_INDEX=false bash "$RUN" engram-protocol.sh gate-redundant-grep 2>&1)"
[ "$(decision "$out")" = allow ] && ok || bad "code index off: gate-redundant-grep should stand aside, got: $out"
stop='{"session_id":"run-sh-test","cwd":"'"$T"'","hook_event_name":"Stop"}'
mkdir -p "$T/repo" && ( cd "$T/repo" && git init -q . ) >/dev/null 2>&1
out="$(printf '%s' "$stop" | env PATH="$T/stubbin:$PATH" CLAUDE_PROJECT_DIR="$T/repo" CLAUDE_PLUGIN_OPTION_KORIUM=true CLAUDE_PLUGIN_OPTION_CODE_INDEX=false bash "$RUN" korium-index-on-stop.sh 2>&1)"
sleep 1
[ ! -e "$T/korium-cli-ran" ] && ok || bad "code index off: the Stop hook should not run korium-cli index"
out="$(printf '%s' "$stop" | env PATH="$T/stubbin:$PATH" CLAUDE_PROJECT_DIR="$T/repo" CLAUDE_PLUGIN_OPTION_KORIUM=true CLAUDE_PLUGIN_OPTION_CODE_INDEX=true bash "$RUN" korium-index-on-stop.sh 2>&1)"
sleep 1
[ -e "$T/korium-cli-ran" ] && ok || bad "code index on: the Stop hook should run korium-cli index"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
