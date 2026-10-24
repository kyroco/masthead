#!/usr/bin/env bash
# Proves mark-codesearch parses all three tool_response shapes and records
# count, indexed sha and spans - the columns gate-span-read and the staleness
# counter read. Fixture mirrors a real captured code_locate payload.
HOOK="${GATE_HOOKS_DIR:-$(cd "$(dirname "$0")/.." && pwd)}/engram-protocol.sh"
pass=0; fail=0
INNER='{"results":[{"rel_path":"products/apps/engram_core/lib/engram/read/hybrid.ex","start_line":1996,"end_line":1998},{"rel_path":"products/apps/engram_core/lib/engram/read/rerank.ex","start_line":223,"end_line":244}],"indexed_git_sha":"904536515a772f3bd56c828b533c99bcabae93f4"}'

run() { # name, shape, expect_n, expect_sha_prefix, expect_span_substr
  sid="cstest-$RANDOM$RANDOM"
  d="${TMPDIR:-/tmp}/masthead-$(id -u)/claude-engram/$sid"; mkdir -p "$d"
  python3 - "$sid" "$2" "$INNER" <<'PY' | bash "$HOOK" mark-codesearch >/dev/null 2>&1
import json,sys
sid,shape,inner=sys.argv[1],sys.argv[2],sys.argv[3]
if shape=="array":    resp=[{"type":"text","text":inner}]
elif shape=="string": resp=inner
elif shape=="object": resp=json.loads(inner)
elif shape=="nested": resp={"content":[{"type":"text","text":inner}]}
print(json.dumps({"session_id":sid,"tool_name":"mcp__korium__code_locate",
  "tool_input":{"query":"interleave_by_rank"},"tool_response":resp}))
PY
  row="$(cat "$d/codesearches.tsv" 2>/dev/null | head -1)"
  n="$(printf '%s' "$row" | cut -f1)"; sha="$(printf '%s' "$row" | cut -f2)"; sp="$(printf '%s' "$row" | cut -f3)"
  ok=1
  [ "$n" = "$3" ] || { ok=0; echo "  FAIL $1: count=$n want $3"; }
  case "$sha" in "$4"*) : ;; *) ok=0; echo "  FAIL $1: sha=$sha want $4*";; esac
  case "$sp" in *"$5"*) : ;; *) ok=0; echo "  FAIL $1: spans=$sp want *$5*";; esac
  [ "$ok" = 1 ] && pass=$((pass+1)) || fail=$((fail+1))
  rm -rf "$d"
}
echo "== three response shapes =="
run "bare array (this client)" array  2 904536515 "hybrid.ex:1996-1998"
run "json string"              string 2 904536515 "hybrid.ex:1996-1998"
run "parsed object"            object 2 904536515 "hybrid.ex:1996-1998"
run "nested content block"     nested 2 904536515 "hybrid.ex:1996-1998"
echo "== second span also recorded =="
run "multi-span row"           array  2 904536515 "rerank.ex:223-244"
echo; echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
