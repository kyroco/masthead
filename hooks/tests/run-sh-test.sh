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

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
