#!/usr/bin/env bash
# Prove korium-index-hint.py tells an agent what the code index holds for the
# plain words of a search the gate let through, asks each word once per
# session, stays quiet on everything the judge already covers or the index
# cannot hold, and never runs `korium-cli search` on a Mac whose
# `korium-cli status` says it is signed out.
#
# A stub korium-cli first on PATH logs every call and answers from a fixture,
# so no case touches Korium. The last cases run the real gate-discovery with
# the real judge and hint beside it.
#
#   bash ~/.claude/hooks/tests/korium-index-hint-test.sh
set -u
HOOKS="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
pass=0
fail=0

mkdir -p "$T/bin" "$T/repo/lib" "$T/outside" "$T/state"
git -C "$T/repo" init -q
: > "$T/repo/notes.md"

cat > "$T/bin/korium-cli" <<'SH'
#!/usr/bin/env bash
case "$1" in
  status) echo status >> "$STUB_LOG"; exit "${STUB_STATUS:-0}" ;;
  search)
    echo "search ${*: -1}" >> "$STUB_LOG"
    if [ -n "${STUB_SEARCH_EXIT:-}" ]; then echo "Could not reach Korium." >&2; exit "$STUB_SEARCH_EXIT"; fi
    cat "$STUB_ROWS"
    ;;
esac
SH
chmod +x "$T/bin/korium-cli"
export STUB_LOG="$T/calls.log"

cat > "$T/rows.json" <<'JSON'
{"results":[
 {"fq_name":"Billing.Subscription","rel_path":"lib/billing/subscription.ex","kind":"module","start_line":1,"end_line":80},
 {"fq_name":"Billing.Subscription.cancel","rel_path":"lib/billing/subscription.ex","kind":"function","start_line":40,"end_line":52},
 {"fq_name":"Billing.subscriptions_for","rel_path":"lib/billing.ex","kind":"function","start_line":9,"end_line":20}]}
JSON
cat > "$T/many.json" <<'JSON'
{"results":[
 {"fq_name":"A.error","rel_path":"lib/a.ex","kind":"function","start_line":1,"end_line":2},
 {"fq_name":"B.error","rel_path":"lib/b.ex","kind":"function","start_line":3,"end_line":4},
 {"fq_name":"C.error","rel_path":"lib/c.ex","kind":"function","start_line":5,"end_line":6},
 {"fq_name":"D.error","rel_path":"lib/d.ex","kind":"function","start_line":7,"end_line":8},
 {"fq_name":"E.error","rel_path":"lib/e.ex","kind":"function","start_line":9,"end_line":10}]}
JSON
printf 'Signing you in first.\n' > "$T/garbage.txt"
export STUB_ROWS="$T/rows.json"

check() {
  local name="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    printf '  ok    %-56s %s\n' "$name" "$(printf '%s' "$got" | cut -c1-40)"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-56s\n        want [%s]\n        got  [%s]\n' "$name" "$want" "$got"
    fail=$((fail + 1))
  fi
}
has() { case "$2" in *"$1"*) echo yes ;; *) echo no ;; esac; }

# $1 pattern, $2 path, $3 cwd. Fixture env is the caller's. One session folder.
hint() {
  jq -n --arg p "$1" --arg d "$2" --arg c "${3:-$T/repo}" --arg s "$T/state" \
    '{pattern:$p,path:$d,cwd:$c,state:$s}' \
    | PATH="$T/bin:$PATH" TMPDIR="$T" python3 "$HOOKS/korium-index-hint.py"
}
fresh() { : > "$STUB_LOG"; rm -f "$T/claude-engram/korium-cli-signed-in" "$T/state/index-hinted"; }
calls() { tr '\n' ',' < "$STUB_LOG" | sed 's/,$//'; }

echo "--- plain words the index holds as names: say where ---"
fresh; out="$(hint 'cancel subscription' '')"
check "names the module, any letter case"               yes "$(has 'Billing.Subscription (module) at lib/billing/subscription.ex:1-80' "$out")"
check "names the function"                              yes "$(has 'Billing.Subscription.cancel (function) at lib/billing/subscription.ex:40-52' "$out")"
check "leaves out a near name (subscriptions_for)"      no  "$(has 'subscriptions_for' "$out")"
check "points at code_locate"                           yes "$(has 'ask code_locate' "$out")"
check "  status first"                                  status "$(head -1 "$STUB_LOG")"
# The lookups run at once, so their order in the log is not fixed.
check "  then one search per word"                      "search cancel,search subscription" "$(tail -n +2 "$STUB_LOG" | sort | tr '\n' ',' | sed 's/,$//')"

echo "--- each word once per session ---"
: > "$STUB_LOG"
check "same words again: nothing"                       "" "$(hint 'subscription cancel' '')"
check "  and no korium-cli call"                        "" "$(calls)"
: > "$STUB_LOG"; hint 'cancel invoice' '' > /dev/null
check "only the new word is asked"                      "search invoice" "$(calls)"

echo "--- more than three hits: three, and how many more ---"
fresh; out="$(STUB_ROWS="$T/many.json" hint 'error' '')"
check "three shown"                                     yes "$(has 'C.error' "$out")"
check "the rest counted"                                yes "$(has '(and 2 more)' "$out")"

echo "--- product code first, vendored code never ---"
cat > "$T/mixed.json" <<'JSON'
{"results":[
 {"fq_name":"invoice","rel_path":"test/fixtures/stripe/paid.json","kind":"other","start_line":5},
 {"fq_name":"Shop.InvoiceTest.invoice","rel_path":"test/shop/invoice_test.exs","kind":"function","start_line":3,"end_line":9},
 {"fq_name":"invoice","rel_path":"native/x/vendor/lib/src/mod.rs","kind":"module","start_line":1},
 {"fq_name":"Shop.invoice","rel_path":"lib/shop.ex","kind":"function","start_line":20,"end_line":30},
 {"fq_name":"Shop.Invoice","rel_path":"lib/shop/invoice.ex","kind":"module","start_line":1,"end_line":90}]}
JSON
fresh; out="$(STUB_ROWS="$T/mixed.json" hint 'invoice' '')"
check "module, then function, then test, then config key" \
  "Shop.Invoice,Shop.invoice,Shop.InvoiceTest.invoice" \
  "$(printf '%s' "$out" | sed 's/^.*mentions: //; s/\. If one.*//; s/ ([a-z]*) at [^;]*//g; s/; /,/g; s/ (and [0-9]* more)//')"
check "vendored code left out"                          no "$(has 'vendor' "$out")"
check "the config key is counted, not shown"            yes "$(has '(and 1 more)' "$out")"

echo "--- nothing to say: quiet ---"
fresh; check "a word the index does not name"           "" "$(hint 'ubuntu' '')"
check "  asked once"                                    "status,search ubuntu" "$(calls)"
: > "$STUB_LOG"; hint 'ubuntu' '' > /dev/null
check "  and not again, though it held nothing"         "" "$(calls)"

echo "--- not this hint's business: quiet, no korium-cli call ---"
fresh; check "code-shaped name (the judge's job)"       "" "$(hint 'handle_call' '')"
check "definition (the judge's job)"                    "" "$(hint 'def cancel' '')"
check "words under four letters"                        "" "$(hint 'add ref' '')"
check "a markdown file"                                 "" "$(hint 'subscription' 'notes.md')"
check "outside any git repository"                      "" "$(hint 'subscription' '' "$T/outside")"
check "empty pattern"                                   "" "$(hint '' '')"
check "  none of the above called korium-cli"           "" "$(calls)"

echo "--- korium-cli cannot answer: quiet, never a browser ---"
fresh; check "signed out"                               "" "$(STUB_STATUS=1 hint 'subscription' '')"
check "  status only, never search"                     "status" "$(calls)"
fresh; check "search fails"                             "" "$(STUB_SEARCH_EXIT=1 hint 'subscription' '')"
check "  the good status is forgotten"                  absent "$([ -e "$T/claude-engram/korium-cli-signed-in" ] && echo present || echo absent)"
: > "$STUB_LOG"; hint 'subscription' '' > /dev/null
check "  and the word is asked again next time"         "status,search subscription" "$(calls)"
fresh; check "search prints something that is not JSON" "" "$(STUB_ROWS="$T/garbage.txt" hint 'subscription' '')"

echo "--- the real gate with this hint beside it ---"
gate() { # $1 session, $2 tool, $3 tool_input json; prints the hook's output
  jq -n --arg s "$1" --arg t "$2" --arg c "$T/repo" --argjson i "$3" \
      '{tool_name:$t,session_id:$s,cwd:$c,tool_input:$i}' \
    | PATH="$T/bin:$PATH" TMPDIR="$T" bash "$HOOKS/engram-protocol.sh" gate-discovery 2>/dev/null
}
decision() { printf '%s' "$1" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null | head -1 | grep . || echo allow; }
context() { printf '%s' "$1" | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null; }

fresh; out="$(gate s1 Grep '{"pattern":"cancel subscription"}')"
check "Grep in plain words is let through"              allow "$(decision "$out")"
check "  with the hint"                                 yes "$(has 'holds names this search mentions' "$(context "$out")")"
check "  after the once-a-session reminder"             yes "$(has 'Korium code index reminder' "$(context "$out")")"
out="$(gate s1 Grep '{"pattern":"ubuntu runner"}')"
check "next search, nothing held, reminder spent: silent" "" "$out"
fresh; out="$(gate s2 Bash '{"command":"rg -n \"subscription\" lib/"}')"
check "shell rg in plain words gets the hint"           yes "$(has 'Billing.Subscription' "$(context "$out")")"
fresh; out="$(gate s3 Glob '{"pattern":"**/subscription"}')"
check "Glob gets no hint"                               no "$(has 'holds names' "$(context "$out")")"
fresh; out="$(MASTHEAD_INDEX_HINT=off gate s4 Grep '{"pattern":"cancel subscription"}')"
check "off switch: reminder only"                       no "$(has 'holds names' "$(context "$out")")"
check "  no search made"                                "" "$(calls | tr ',' '\n' | grep search)"
fresh; out="$(STUB_STATUS=1 gate s5 Grep '{"pattern":"cancel subscription"}')"
check "signed out: let through, no hint"                allow "$(decision "$out")"
check "  never searched"                                "status" "$(calls)"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
