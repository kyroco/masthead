#!/usr/bin/env bash
# Prove korium-index-judge.py asks the code index for the right words, reads its
# answer exactly, lets through what the index cannot hold without asking, and
# never runs `korium-cli search` on a Mac whose `korium-cli status` says it is
# signed out (search would open a browser sign-in from inside a hook).
#
# A stub korium-cli first on PATH logs every call and answers from fixtures, so
# no case touches Korium. The last cases run the real gate-discovery with the
# real judge beside it.
#
#   bash ~/.claude/hooks/tests/korium-index-judge-test.sh
set -u
HOOKS="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
pass=0
fail=0

mkdir -p "$T/bin" "$T/repo/lib" "$T/outside"
git -C "$T/repo" init -q
: > "$T/repo/notes.md"
: > "$T/repo/lib/x.ex"

cat > "$T/bin/korium-cli" <<'SH'
#!/usr/bin/env bash
echo "$1" >> "$STUB_LOG"
case "$1" in
  status) exit "${STUB_STATUS:-0}" ;;
  search)
    if [ -n "${STUB_SEARCH_EXIT:-}" ]; then echo "Could not reach Korium." >&2; exit "$STUB_SEARCH_EXIT"; fi
    cat "$STUB_ROWS"
    ;;
esac
SH
chmod +x "$T/bin/korium-cli"
export STUB_LOG="$T/calls.log"

cat > "$T/held.json" <<'JSON'
{"results":[
 {"fq_name":"Engram.MCP.Stdio.handle_call","rel_path":"lib/stdio.ex","kind":"function"},
 {"fq_name":"Engram.RateLimit.SlidingWindow","rel_path":"lib/engram/rate_limit/sliding_window.ex","kind":"module"},
 {"fq_name":"Foo.valid?","rel_path":"lib/foo.ex","kind":"function"}]}
JSON
cat > "$T/near.json" <<'JSON'
{"results":[
 {"fq_name":"SalonWeb.SiteChromeVersions.script","rel_path":"lib/a.ex","kind":"function"},
 {"fq_name":"body","rel_path":"scripts/check.mjs","kind":"constant"}]}
JSON
printf 'Signing you in first.\n' > "$T/garbage.txt"

check() {
  local name="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    printf '  ok    %-58s %s\n' "$name" "$got"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-58s want %s got %s\n' "$name" "$want" "$got"
    fail=$((fail + 1))
  fi
}

# $1 tool, $2 pattern, $3 path, $4 cwd. Fixture env is the caller's.
judge() {
  jq -n --arg t "$1" --arg p "$2" --arg d "$3" --arg c "${4:-$T/repo}" \
    '{tool:$t,pattern:$p,path:$d,cwd:$c}' \
    | PATH="$T/bin:$PATH" TMPDIR="$T" python3 "$HOOKS/korium-index-judge.py"
}
fresh() { : > "$STUB_LOG"; rm -f "$T/claude-engram/korium-cli-signed-in"; }
calls() { tr '\n' ' ' < "$STUB_LOG" | sed 's/ $//'; }

echo "--- the index holds the name: refuse until the agent asks it ---"
export STUB_ROWS="$T/held.json"
fresh; check "def handle_call"                          SEARCHABLE "$(judge Grep 'def handle_call' '')"
check "  asked status, then searched"                   "status search" "$(calls)"
fresh; check "full dotted module name"                  SEARCHABLE "$(judge Grep 'Engram.RateLimit.SlidingWindow' '')"
fresh; check "dotted tail of the name"                  SEARCHABLE "$(judge Grep 'RateLimit\.SlidingWindow' '')"
fresh; check "bare module part"                         SEARCHABLE "$(judge Grep 'SlidingWindow' '')"
fresh; check "Elixir name ending in ?"                  SEARCHABLE "$(judge Grep 'def valid?' '')"
fresh; check "Glob for a file the index read"           SEARCHABLE "$(judge Glob '**/sliding_window.ex' '')"

echo "--- the index answered but does not hold it exactly: let through ---"
fresh; check "dotted name with another head"            NOT_SEARCHABLE "$(judge Grep 'Other.SlidingWindow' '')"
fresh; check "Glob for a file the index lacks"          NOT_SEARCHABLE "$(judge Glob '**/other.ex' '')"
export STUB_ROWS="$T/near.json"
fresh; check "Terraform literal, near rows only"        NOT_SEARCHABLE "$(judge Grep 'CrossSiteScripting_BODY' 'infra/')"

echo "--- nothing worth asking: let through without calling korium-cli ---"
export STUB_ROWS="$T/held.json"
fresh; check "plain words (runs-on: ubuntu)"            NOT_SEARCHABLE "$(judge Grep 'runs-on: ubuntu' '')"
check "  no korium-cli call"                            "" "$(calls)"
fresh; check "markdown heading"                         NOT_SEARCHABLE "$(judge Grep '## Mandatory PR workflow' '')"
fresh; check "a name, in a markdown file"               NOT_SEARCHABLE "$(judge Grep 'handle_call' 'notes.md')"
fresh; check "a name, outside any git repository"       NOT_SEARCHABLE "$(judge Grep 'handle_call' '' "$T/outside")"
fresh; check "Glob with a wildcard file name"           NOT_SEARCHABLE "$(judge Glob '**/*.ex' '')"
fresh; check "empty pattern"                            NOT_SEARCHABLE "$(judge Grep '' '')"
check "  none of the above called korium-cli"           "" "$(calls)"

echo "--- korium-cli cannot answer: UNKNOWN, which the gate refuses on ---"
fresh; check "signed out (status fails)"                UNKNOWN "$(STUB_STATUS=1 judge Grep 'def handle_call' '')"
check "  never searched, so no browser sign-in"         "status" "$(calls)"
fresh; check "search fails"                             UNKNOWN "$(STUB_SEARCH_EXIT=1 judge Grep 'def handle_call' '')"
check "  and the good status is forgotten"              "absent" "$([ -e "$T/claude-engram/korium-cli-signed-in" ] && echo present || echo absent)"
fresh; check "search prints something that is not JSON" UNKNOWN "$(STUB_ROWS="$T/garbage.txt" judge Grep 'def handle_call' '')"

echo "--- a good status is trusted for ten minutes ---"
fresh; judge Grep 'def handle_call' '' > /dev/null; : > "$STUB_LOG"
check "second search skips status"                      SEARCHABLE "$(judge Grep 'SlidingWindow' '')"
check "  only the search ran"                           "search" "$(calls)"

echo "--- the real gate with this judge beside it ---"
gate() { # $1 pattern; prints deny or allow
  local sid="probe-$RANDOM$RANDOM" out
  out="$(jq -n --arg s "$sid" --arg p "$1" --arg c "$T/repo" \
      '{tool_name:"Grep",session_id:$s,cwd:$c,tool_input:{pattern:$p}}' \
    | PATH="$T/bin:$PATH" TMPDIR="$T" bash "$HOOKS/engram-protocol.sh" gate-discovery 2>/dev/null)"
  printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null | head -1 | grep . || echo allow
}
fresh; check "gate refuses a name the index holds"      deny  "$(gate 'def handle_call')"
fresh; check "gate lets a plain-word search through"    allow "$(gate 'runs-on: ubuntu')"
fresh; check "gate refuses when signed out"             deny  "$(STUB_STATUS=1 gate 'def handle_call')"
check "  still without a search"                        "status" "$(calls)"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
