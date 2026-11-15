#!/usr/bin/env bash
# Korium memory protocol: the gates that make search-before-edit, capture-before-finish and an honest brief mechanical.
# Runs in every repo through shared-run.sh; nothing here names one repository.
#
# Modes, each wired on one hook event:
#   mark-search, mark-capture, mark-codesearch, mark-grep, mark-edit  (PostToolUse) record a search, a capture, a code_locate answer, a Grep/Glob/shell search, an edit
#   gate-edit         refuses the first edit until a Korium search ran
#   gate-discovery    refuses a Grep, Glob or shell search for a name the code index holds until a fresh code_locate lookup
#   gate-redundant-grep, gate-span-read  refuse repeating what code_locate just answered
#   gate-verify-brief  refuses a verifier or security-reviewer brief with no claims list, a third re-verify round, and an architecture-reviewer brief without the ADR alignment lines or the architecture doc the project records
#   gate-capture      refuses a capture over 2,000 characters, a decision with no decider or no word on what it replaces, and a subagent capture filed under another agent's name
#   gate-stop, gate-substop  refuse one finish with no capture
# Every refusal happens once per session, then stands down. MASTHEAD_<NAME>_GATE=off in the operator's environment switches a gate off.

set -uo pipefail

mode="${1:?usage: engram-protocol.sh <mode>}"
payload="$(cat 2>/dev/null || echo '{}')"

field() { printf '%s' "$payload" | jq -r "$1" 2>/dev/null || echo ""; }
# With no jq, json_field.py reads a plain path such as '.tool_input.prompt // ""', so the gates that read
# only plain paths (the brief check among them) hold the same (MAST-37). Any other filter reads as empty.
if ! command -v jq >/dev/null 2>&1; then
  _json_field="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)/json_field.py"
  field() { printf '%s' "$payload" | python3 -I "$_json_field" "$1" 2>/dev/null || echo ""; }
fi

# A plain path read from JSON other than the payload, such as shell-search-pattern.py's answer, with or without jq.
json_read() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -r "$2" 2>/dev/null
  else
    printf '%s' "$1" | python3 -I "$_json_field" "$2" 2>/dev/null
  fi
}

# The tool response as one line of text, as jq's tostring gives it; json_field.py prints the same value with no jq.
response_text() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$payload" | jq -r '.tool_response | tostring' 2>/dev/null
  else
    field '.tool_response'
  fi
}

# The dispatched agent: Claude Code sends this plugin's verifier as masthead:verifier, or masthead:<folder>:verifier for one in a subfolder of agents/, so a masthead: name is matched on the part after the last colon. Another plugin's agent keeps its prefix, so it is never taken for ours.
# The masthead: namespace is trusted as this plugin's identity. A fork also named masthead would pass as ours, but reading the name from .claude-plugin/plugin.json would not tell it apart either, since a fork's plugin.json says masthead too.
# Of a masthead: name's parts, the last one naming a masthead agent is the agent, as in the fences; else the last part.
agent_type() {
  local t; t="$(field '.tool_input.subagent_type // ""')"
  case "$t" in
    masthead:*) printf '%s' "${t#masthead:}" | awk -F: '{ for (i = NF; i >= 1; i--) if ($i ~ /^(verifier|security-reviewer|architecture-reviewer|adjudicator|diagnoser|reader)$/) { printf "%s", $i; exit } printf "%s", $NF }' ;;
    *) printf '%s' "$t" ;;
  esac
}

# The user's private state root: $CLAUDE_PLUGIN_DATA/state, else $TMPDIR/masthead-<uid>. Mode 0700; refused when a symlink or not ours.
state_root() {
  local r
  if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then r="$CLAUDE_PLUGIN_DATA/state"; else r="${TMPDIR:-/tmp}/masthead-$(id -u)"; fi
  (umask 077; mkdir -p "$r") 2>/dev/null
  [ -d "$r" ] && [ ! -L "$r" ] && [ -O "$r" ] || return 1
  chmod 700 "$r" 2>/dev/null
  printf '%s' "${r%/}"
}

sid="$(field '.session_id // "nosession"')"
sid="${sid//[^A-Za-z0-9_-]/}"
[ -n "$sid" ] || sid="nosession"
umask 077
root="$(state_root)" || exit 0
dir="$root/claude-engram/${sid}"
mkdir -p "$dir" 2>/dev/null || exit 0

# The folder this hook lives in; empty when unknown.
hook_dir=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  hook_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || hook_dir=""
fi

deny_tool() {
  if ! command -v jq >/dev/null 2>&1; then
    python3 -I "$_json_field" --deny "$1"
    return
  fi
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
}

# A Stop or PostToolUse block carrying the reason; json_field.py writes it when jq is missing (MAST-37).
block_decision() {
  if ! command -v jq >/dev/null 2>&1; then
    python3 -I "$_json_field" --block "$1"
    return
  fi
  jq -n --arg r "$1" '{decision: "block", reason: $r}'
}

# Block once, then stand down (see FAIL-OPEN above).
block_stop() {
  local once="$dir/stop-blocked-$2"
  [ -f "$once" ] && exit 0
  : > "$once"
  block_decision "$1"
}

# Tell the model, every time, that a capture was refused and why.
report_refusal() {
  block_decision "$1"
}

# Classify a capture's tool_response: stored, unfixable, rejected or unknown.
capture_outcome() {
  local resp
  resp="$(response_text | tr -d '\\ ')"

  case "$resp" in
    # stored: the tool returned a thought id.
    *'"thought_id":'*) echo stored ;;
    # unfixable: a ceiling is spent or the payer must act.
    *'"class":"quota"'* | *'"class":"payment"'*) echo unfixable ;;
    # rejected: any other named refusal.
    *'"status":"rejected"'*) echo rejected ;;
    # An outage, an error frame, or a shape nobody here recognises.
    *) echo unknown ;;
  esac
}

case "$mode" in
  # mark-search: record the search's query and hit count.
  mark-search)
    : > "$dir/searched"
    q="$(field '.tool_input.query // ""' | tr '\t\n' '  ')"
    resp="$(response_text | tr -d '\\ ')"
    n="$(printf '%s' "$resp" | grep -oE '"result_count":[0-9]+' | head -1 | grep -oE '[0-9]+$')"
    [ -n "$n" ] || n="-"
    printf '%s\t%s\n' "$n" "$q" >> "$dir/searches.tsv" 2>/dev/null || true
    ;;
  # mark-codesearch: record a code_locate answer (hits, spans, query, freshness).
  mark-codesearch)
    case "$(field '.tool_name // ""')" in
      *code_locate)
        q="$(field '.tool_input.query // ""' | tr '\t\n' '  ')"
        # The response arrives as a string, an object or a list of content blocks.
        resp="$(printf '%s' "$payload" | jq -c '
          (.tool_response // {})
          | if type == "array" then (.[0].text? // "{}" | fromjson? // {})
            elif type == "string" then (fromjson? // {})
            else . end
          | if (.content? | type) == "array"
            then ((.content[0].text? // "{}") | fromjson? // {})
            else . end' 2>/dev/null)"
        # path:start-end for every hit, which gate-span-read matches on.
        spans="$(printf '%s' "$resp" | jq -r '
          [(.results // [])[]
           | select(.rel_path != null)
           | "\(.rel_path):\(.start_line // 0)-\(.end_line // 0)"]
          | unique | join(" ")' 2>/dev/null)"
        sha="$(printf '%s' "$resp" | jq -r '.indexed_git_sha // ""' 2>/dev/null)"
        n="$(printf '%s' "$resp" | jq -r '(.results // []) | length' 2>/dev/null)"
        # The tool reports its own freshness in .staleness.stale.
        stale="$(printf '%s' "$resp" \
          | jq -r 'if (.staleness.stale // false) then "stale" else "fresh" end' 2>/dev/null)"
        ;;
      *)
        # For a Bash search, record only the rg or grep pattern.
        cmd="$(field '.tool_input.command // ""' | tr '\t\n' '  ')"
        case "$cmd" in
          *korium-cli*search*) : ;;
          *) exit 0 ;;
        esac
        q="$cmd"
        spans=""
        sha=""
        n="-"
        ;;
    esac
    # Columns: hits, sha, spans, query, freshness.
    printf '%s\t%s\t%s\t%s\t%s\n' "${n:--}" "${sha:--}" "${spans:--}" "$q" "${stale:--}" \
      >> "$dir/codesearches.tsv" 2>/dev/null || true
    ;;

  # mark-grep: record every Grep, Glob and shell search, allowed or not.
  mark-grep)
    tool="$(field '.tool_name // "?"')"
    case "$tool" in
      Bash)
        cmd="$(field '.tool_input.command // ""' | tr '\t\n' '  ')"
        # A search verb at a command boundary.
        printf '%s' "$cmd" \
          | grep -qE '(^|[|;&]|\$\()[[:space:]]*(grep|egrep|fgrep|rg|ag|ack|find)[[:space:]]' \
          || exit 0
        pat="$cmd"
        ;;
      *)
        pat="$(field '.tool_input.pattern // .tool_input.path // ""' | tr '\t\n' '  ')"
        ;;
    esac
    printf '%s\t%s\n' "$tool" "$pat" \
      >> "$dir/greps.tsv" 2>/dev/null || true
    ;;

  mark-edit)    : > "$dir/edited"   ;;

  mark-capture)
    case "$(capture_outcome)" in
      stored)
        : > "$dir/captured"
        ;;
      unfixable)
        : > "$dir/refused-unfixable"
        report_refusal "Korium refused that capture: a plan limit is reached, so nothing was stored. This does NOT resolve on a retry, so do not send the same capture again. Read the reason and the numbers in the tool response, tell the user in one plain sentence what limit was hit and what clears it, and carry on with the work. Captures stay refused for the rest of this session unless the limit is raised, and reads, searching and linking all still work."
        ;;
      rejected)
        report_refusal "Korium refused that capture and nothing was stored. Read the reason in the tool response: it names what to change. A payload refused for size can be saved by splitting it into smaller memories, so fix it and capture again rather than dropping the thought."
        ;;
      unknown)
        # No capture recorded; gate-stop handles it.
        :
        ;;
    esac
    ;;

  # gate-discovery: refuse a Grep, Glob or shell search for a name the code index holds until a fresh code_locate lookup of it.
  gate-discovery)
    # Operator off switch.
    case "${MASTHEAD_CODE_GATE:-}" in off|0|false|no) exit 0 ;; esac
    # No korium-cli on this machine means no index this person can build: stand aside.
    command -v korium-cli >/dev/null 2>&1 || exit 0

    judge="$hook_dir/korium-index-judge.py"
    [ -x "$judge" ] || exit 0

    tool="$(field '.tool_name // ""')"
    case "$tool" in
      Bash)
        # A shell search carries its pattern inside the command line.
        cmd="$(field '.tool_input.command // ""')"
        printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])(grep|egrep|fgrep|rg)([[:space:]]|$)' || exit 0
        found="$(printf '%s' "$cmd" | python3 "$hook_dir/shell-search-pattern.py" 2>/dev/null)"
        pat="$(json_read "$found" '.pattern // ""')"
        path="$(json_read "$found" '.path // ""')"
        # The judge reads a shell search as the Grep it is.
        tool="Grep"
        ;;
      *)
        pat="$(field '.tool_input.pattern // .tool_input.glob // ""')"
        path="$(field '.tool_input.path // ""')"
        ;;
    esac
    [ -n "${pat:-}" ] || exit 0

    # One index lookup per distinct search; a repeat reuses the verdict.
    cache="$dir/judged-$(printf '%s\t%s' "$pat" "${path:-}" | cksum | tr -d ' ')"
    if [ -s "$cache" ]; then
      verdict="$(cat "$cache")"
    elif [ -n "$(find "$dir/judge-down" -mmin -5 2>/dev/null)" ]; then
      # The judge failed within the last five minutes; do not ask again.
      verdict="UNKNOWN"
    else
      # Ask the index judge, with the cwd for a relative path.
      if command -v jq >/dev/null 2>&1; then
        question="$(jq -n --arg t "$tool" --arg p "$pat" --arg d "${path:-}" \
          --arg c "$(field '.cwd // ""')" \
          '{tool:$t,pattern:$p,path:$d,cwd:$c}' 2>/dev/null)"
      else
        question="$(python3 -I "$_json_field" --build tool "$tool" pattern "$pat" path "${path:-}" \
          cwd "$(field '.cwd // ""')" 2>/dev/null)"
      fi
      verdict="$(printf '%s' "$question" | python3 "$judge" 2>/dev/null | tr -d '[:space:]')"
      case "$verdict" in
        SEARCHABLE|NOT_SEARCHABLE) printf '%s' "$verdict" > "$cache" ;;
        *) : > "$dir/judge-down" ;;
      esac
    fi

    # Anything but a clear verdict is a judge that cannot be read: refuse.
    judge_down=""
    case "$verdict" in
      SEARCHABLE|NOT_SEARCHABLE) ;;
      *) judge_down="The code index could not be asked whether it holds this name (korium-cli is signed out, or Korium did not answer), so the search is treated as one it can answer. "; verdict="SEARCHABLE" ;;
    esac

    if [ "$verdict" != "SEARCHABLE" ]; then
      # Allowed; for a plain-word search, korium-index-hint.py says where the index holds its words.
      context=""
      case "${MASTHEAD_INDEX_HINT:-}" in off|0|false|no) ;; *)
        if [ "$tool" = Grep ] && [ -x "$hook_dir/korium-index-hint.py" ]; then
          context="$(jq -n --arg p "$pat" --arg d "${path:-}" --arg c "$(field '.cwd // ""')" \
            --arg s "$dir" '{pattern:$p,path:$d,cwd:$c,state:$s}' 2>/dev/null \
            | python3 "$hook_dir/korium-index-hint.py" 2>/dev/null)"
        fi ;;
      esac
      if [ ! -f "$dir/discovery-nudged" ]; then
        : > "$dir/discovery-nudged"
        context="Korium code index reminder: code_locate answers where a function, module, YAML key, SQL object or Terraform resource lives, faster than a search. If it reports itself stale, run korium-cli index in your checkout and ask again with branch set to the branch you are on.${context:+ $context}"
      fi
      [ -n "$context" ] || exit 0
      jq -n --arg c "$context" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $c}}'
      exit 0
    fi

    # A fresh lookup of the same name counts.
    if [ -s "$dir/codesearches.tsv" ]; then
      words() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]_' '\n' | awk 'length >= 4'; }
      pat_words="$(words "$pat")"
      while IFS="$(printf '\t')" read -r _ _ _ q stale; do
        [ "$stale" = fresh ] || [ "$stale" = "-" ] || continue
        for word in $(words "$q"); do
          printf '%s\n' "$pat_words" | grep -qxF -- "$word" && exit 0
        done
      done < "$dir/codesearches.tsv"
    fi

    # A review agent cannot run korium-cli index, so a lagging index would refuse it on every search: it is
    # refused once a session, then its searches go through (MAST-37). The main session can re-index, so it stays refused.
    # Only Masthead's own agents, by the rule review-write-fence.py uses: a masthead: name, whose last part that
    # names one of them is the agent. A bare name such as reader can be a repo's own agent, which can re-index.
    acting="$(field '.agent_type // .agent_name // ""')"
    case "$acting" in
      masthead:*) acting="$(printf '%s' "${acting#masthead:}" | awk -F: '{ for (i = NF; i >= 1; i--) if ($i ~ /^(verifier|security-reviewer|adjudicator|diagnoser|reader)$/) { printf "%s", $i; exit } }')" ;;
      *) acting="" ;;
    esac
    case "$acting" in
      verifier|security-reviewer|adjudicator|diagnoser|reader)
        [ -f "$dir/discovery-refused-agent" ] && exit 0
        : > "$dir/discovery-refused-agent"
        judge_down="${judge_down}This agent cannot re-index, so this is the only search it is refused this session: ask code_locate once, and if the answer is stale, search again and it goes through. " ;;
    esac
    printf 'refused\n' >> "$dir/discovery-refused"
    deny_tool "${judge_down}Korium code index first: the index can answer this. Call code_locate (mcp__korium__code_locate, or mcp__claude_ai_korium__code_locate through the claude.ai connector) with the repo value for the checkout you are in, head_sha set to the current HEAD, and a query phrased toward the name you expect. The repo's CLAUDE.md names that value when it has one; if it does not, ask code_locate without repo and, when the answer lists known_repositories, use the one for this repository. It holds code symbols and also YAML keys, SQL and Terraform resources. Read the span it returns instead of the whole file. If it reports itself stale, or holds no index for this branch, run korium-cli index in your checkout (it takes seconds) and ask again with branch set to your checkout's branch; without branch it reads the trunk, which is still stale. If korium-cli says this Mac is not signed in, stop and tell the person rather than wait on a browser sign-in. Without the MCP tool, korium-cli search \"<name>\" asks the same index. Once a fresh lookup of this name has been made, whatever it found, this search goes through, so a search for its callers is not blocked."
    ;;

  # gate-redundant-grep: refuse, once, a search that repeats a name code_locate just answered.
  gate-redundant-grep)
    case "${MASTHEAD_CODE_GATE:-}" in off|0|false|no) exit 0 ;; esac
    # No korium-cli on this machine means no index this person can build: stand aside.
    command -v korium-cli >/dev/null 2>&1 || exit 0
    [ -s "$dir/codesearches.tsv" ] || exit 0

    # For a shell command, only the pattern of an rg or grep.
    if [ "$(field '.tool_name // ""')" = Bash ]; then
      cmd="$(field '.tool_input.command // ""')"
      printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])(grep|egrep|fgrep|rg)([[:space:]]|$)' || exit 0
      pat="$(printf '%s' "$cmd" | python3 "$hook_dir/shell-search-pattern.py" 2>/dev/null \
        | jq -r '.pattern // ""' 2>/dev/null)"
    else
      pat="$(field '.tool_input.pattern // ""')"
    fi
    [ -n "$pat" ] || exit 0

    # Columns: hits, sha, spans, query, freshness; only fresh hits count.
    hit_query="$(awk -F'\t' '$1 ~ /^[0-9]+$/ && $1 > 0 && $5 == "fresh" {print $4}' \
      "$dir/codesearches.tsv" 2>/dev/null | tail -5)"
    [ -n "$hit_query" ] || exit 0

    # Containment either way, case-insensitive.
    lower_pat="$(printf '%s' "$pat" | tr '[:upper:]' '[:lower:]')"
    match=""
    while IFS= read -r q; do
      [ -n "$q" ] || continue
      lower_q="$(printf '%s' "$q" | tr '[:upper:]' '[:lower:]')"
      case "$lower_pat" in *"$lower_q"*) match="$q"; break ;; esac
      case "$lower_q" in *"$lower_pat"*) match="$q"; break ;; esac
      for word in $lower_q; do
        [ "${#word}" -ge 6 ] || continue
        case "$lower_pat" in *"$word"*) match="$q"; break 2 ;; esac
      done
    done <<EOF
$hit_query
EOF
    [ -n "$match" ] || exit 0

    # Once per pattern.
    stamp="$dir/redundant-$(printf '%s' "$lower_pat" | cksum | tr -d ' ')"
    [ -f "$stamp" ] && exit 0
    : > "$stamp"

    deny_tool "The code index already answered this: \"$match\" returned results this session, and their spans are in the search response. Read those spans instead of searching for \"$pat\" again. Ripgrep is the right tool when a fresh index came back EMPTY, for what the index does not hold (callers and other uses of a name, values, markdown, HTML), or for the file types it does not read. A STALE answer means run korium-cli index and ask again, not ripgrep. If this search is genuinely for something else, run it again and it will go through."
    ;;

  # gate-span-read: refuse, once, a whole-file read after code_locate returned a span in that file.
  gate-span-read)
    [ -s "$dir/codesearches.tsv" ] || exit 0
    case "${MASTHEAD_CODE_GATE:-}" in off|0|false|no) exit 0 ;; esac
    # No korium-cli on this machine means no index this person can build: stand aside.
    command -v korium-cli >/dev/null 2>&1 || exit 0
    [ -f "$dir/span-refused" ] && exit 0

    # An offset means the read is already scoped. Nothing to say.
    [ "$(field '.tool_input.offset // ""')" = "" ] || exit 0

    path="$(field '.tool_input.file_path // ""')"
    [ -n "$path" ] || exit 0

    # Column 3 holds the path:start-end list; match on the path.
    hit="$(cut -f3 "$dir/codesearches.tsv" 2>/dev/null | tr ' ' '\n' \
      | awk -v target="$path" '
          $0 == "" || $0 == "-" { next }
          {
            p = $0
            sub(/:[0-9]+-[0-9]+$/, "", p)
            if (p == "") next
            if (length(target) >= length(p) &&
                substr(target, length(target) - length(p) + 1) == p) print $0
          }' | head -3 | tr '\n' ' ')"
    [ -n "$hit" ] || exit 0

    : > "$dir/span-refused"
    deny_tool "The code index already told you where this is: $hit. Read that span with offset and limit rather than the whole file, widening if the surrounding function needs it. That is the saving the lookup exists for. If you genuinely need the whole file, run this same Read again and it will go through."
    ;;

  gate-edit)
    [ -f "$dir/searched" ] || deny_tool "Korium memory protocol: search Korium before changing files. Run the korium MCP server's agent_search tool (mcp__korium__agent_search, or mcp__claude_ai_korium__agent_search if your client reaches it through the hosted connector) with 1-2 focused queries (the feature, the files you are touching, the subsystem) and fold prior decisions and lessons into your approach. This is the first file change this session."

    # Operator off switch.
    case "${MASTHEAD_SEARCH_GATE:-}" in off|0|false|no) exit 0 ;; esac

    # No record of searches (an older session or a failed write): allow.
    [ -s "$dir/searches.tsv" ] || exit 0

    # Refuse only when every search returned nothing and one wording was tried.
    hits="$(awk -F'\t' '$1 ~ /^[0-9]+$/ && $1 > 0' "$dir/searches.tsv" 2>/dev/null | wc -l | tr -d ' ')"
    tries="$(cut -f2 "$dir/searches.tsv" 2>/dev/null | sort -u | wc -l | tr -d ' ')"
    if [ "${hits:-0}" -eq 0 ] && [ "${tries:-0}" -le 1 ]; then
      deny_tool "Korium memory protocol: your Korium search came back empty and was only tried one way, so nothing was learned before this edit. Search again with a different wording: name the file or the subsystem, or the error, or the decision you expect somebody made. If Korium genuinely holds nothing on this, two different queries returning nothing is the evidence for that and this gate stands aside once you have it."
      # deny_tool prints, it does not exit.
      exit 0
    fi

    exit 0
    ;;

  # gate-capture: refuse a capture over 2,000 characters, a decision with no decider or no word on what it replaces, and a subagent capture filed under another agent's name.
  gate-capture)
    case "${MASTHEAD_CAPTURE_GATE:-}" in off|0|false|no) exit 0 ;; esac

    # Issue #63: a 7,339 character verdict took 12.5 seconds to embed and blocked the account's drain for two hours. Any session or agent; content that is not text is left to Korium to refuse.
    # With no jq, field reads nothing and deny_tool prints nothing, so python3 does both here and this rule still holds.
    if command -v jq >/dev/null 2>&1; then
      size="$(field '.tool_input.content | if type == "string" then length else 0 end')"
    else
      size="$(printf '%s' "$payload" | python3 -I -c 'import json, sys
content = json.load(sys.stdin)["tool_input"]["content"]
print(len(content) if isinstance(content, str) else 0)' 2>/dev/null)"
    fi
    if [ "${size:-0}" -gt 2000 ]; then
      reason="This capture's content is $(printf '%d,%03d' $((size / 1000)) $((size % 1000))) characters, and the limit is 2,000. Split it into the claims it makes, one memory each. Save one short memory first, then give each of the others a relation to it: {\"target_id\": \"<its id>\", \"relation_type\": \"supports\"}. MASTHEAD_CAPTURE_GATE=off in the operator's environment turns this gate off."
      if command -v jq >/dev/null 2>&1; then
        deny_tool "$reason"
      else
        python3 -I -c 'import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": sys.argv[1]}}))' "$reason"
      fi
      exit 0
    fi

    # Issue #57: Korium answers what is adopted only when a decision says who ruled and which earlier rulings stop being live. Any session or agent; a jq error reads as the field missing, so a wrong shape is refused.
    if [ "$(field '.tool_input.thought_type // ""')" = "decision" ]; then
      if [ "$(field '.tool_input.decided_by | . != null and . != {} and . != "" and . != []')" != "true" ]; then
        deny_tool "A decision saved to Korium must say who decided. Name them in decided_by, an object such as {\"name\": \"<who ruled>\"}. If nobody ruled, this is a finding, not a decision: save it with thought_type insight. MASTHEAD_CAPTURE_GATE=off in the operator's environment turns this gate off."
        exit 0
      fi
      if [ "$(field '.tool_input | (.relations | if type == "array" then any(.[]; type == "object" and .relation_type == "supersedes") else false end) or ((.metadata | if type == "object" then .replaces else null end) == "none")')" != "true" ]; then
        deny_tool "A decision saved to Korium must say what it replaces. Search what is adopted (agent_search with stance \"position\" and limit 10), then list every record this one replaces in relations, each as {\"target_id\": \"<id>\", \"relation_type\": \"supersedes\"}. If it replaces nothing, state that with metadata {\"replaces\": \"none\"}. MASTHEAD_CAPTURE_GATE=off in the operator's environment turns this gate off."
        exit 0
      fi
    fi

    acting="$(field '.agent_name // .agent_type // ""')"
    [ -n "$acting" ] || exit 0
    claimed="$(field '.tool_input.source_agent // ""')"
    [ -n "$claimed" ] || exit 0
    [ -n "$(field '.tool_input.captured_by // ""')" ] && exit 0

    # The name to file under is the bare agent name: masthead:verifier files as verifier (Robert, 2026-10-29: "just verifier"), since Korium refuses a colon.
    a="$(printf '%s' "${acting##*:}" | tr 'A-Z' 'a-z')"
    c="$(printf '%s' "${claimed##*:}" | tr 'A-Z' 'a-z')"
    # Korium's own source_agent pattern; a name it would refuse is refused here, with the name that passes both.
    if ! printf '%s' "$claimed" | grep -qE '^[a-z][a-z0-9_-]{1,63}$'; then
      deny_tool "Korium refuses source_agent '$claimed': it must match ^[a-z][a-z0-9_-]{1,63}\$, so no colon and no capital. File this capture as source_agent '$a', your agent name without the plugin prefix. MASTHEAD_CAPTURE_GATE=off in the operator's environment turns this gate off."
      exit 0
    fi
    [ "$a" = "$c" ] && exit 0
    case "$c" in "$a"-*|"$a"_*) exit 0 ;; esac
    deny_tool "This capture is filed under '$claimed' but the agent making it is '$acting'. source_agent is the one field that answers who decided this, and filing under another name falsifies exactly that. File it as source_agent '$a', your agent name without any plugin prefix. If you are genuinely re-filing for an agent whose own capture failed, keep their source_agent and set captured_by to your name, which this gate allows. MASTHEAD_CAPTURE_GATE=off in the operator's environment turns it off."
    ;;

  # gate-verify-brief: refuse a brief to verifier or security-reviewer that carries no claims list, and a third re-verify round.
  gate-verify-brief)
    case "${MASTHEAD_BRIEF_GATE:-}" in off|0|false|no) exit 0 ;; esac

    # Only the two agents that verify claims, and the architecture reviewer, are screened.
    case "$(agent_type)" in
      verifier|security-reviewer|architecture-reviewer) : ;;
      *) exit 0 ;;
    esac

    prompt="$(field '.tool_input.prompt // ""')"
    reasons=""
    REVERIFY_FORM="the form is a line that begins 'Re-verify: round N' at column zero, N the number of this round, with no marker before it"

    # The round cap, on a verifier's and an architecture reviewer's brief. A
    # change gets at most two re-verify rounds. A round is spent by the
    # verifier, the architecture reviewer re-checking the architecture findings
    # a fix addressed (MAST-35 scenario 6), or both sent in it under one round
    # number: a row of one agent pairs with one row of the other that names the
    # same round, and a pair is one round. The security reviewer sent beside
    # them is neither counted nor capped, and no other agent's row counts. The
    # row is written before the agent runs, so one that died or was declined
    # has spent its round. The dispatch log decides; the brief's number only
    # says which round a dispatch joins.
    reverify_cap() {
      local kind="$1" state n log_root log session8 branch counts spent joins
      state="$(printf '%s' "$prompt" | awk '
        {
          line = $0; sub(/\r$/, "", line)
          bare = line; gsub(/^[[:space:]>*_#`-]+|^[0-9]+\.[[:space:]]*/, "", bare); gsub(/[*_`]+/, "", bare)
          if (tolower(bare) ~ /^re-?verify[[:space:]]*:/) {
            if (match(line, /^Re-verify: round [0-9]+/)) print "yes\t" substr(line, 18, RLENGTH - 17); else print "variant\t"
            exit
          }
        }' | head -1)"
      n="${state#*$'\t'}"
      state="${state%%$'\t'*}"
      if [ "$state" = variant ]; then
        [ -n "$reasons" ] && reasons="$reasons

"
        reasons="${reasons}Re-verify rule: this brief's re-verify line is not in the one form the check reads, so it would run uncounted; $REVERIFY_FORM. Then retry."
        return 0
      fi
      [ "$state" = yes ] || return 0
      log_root="$(field '.cwd // ""')"
      [ -n "$log_root" ] || log_root="${CLAUDE_PROJECT_DIR:-$PWD}"
      log="$log_root/.claude/state/dispatches.tsv"
      session8="$(field '.session_id // "nosession"' | cut -c1-8)"
      branch="$(git -C "$log_root" branch --show-current 2>/dev/null || true)"
      [ -n "$branch" ] || branch="-"
      spent=0
      joins=0
      if [ -s "$log" ]; then
        # Columns: when, session, agent, type, model, outcome, reason, branch; a row with no branch column is from before the column existed and counts. Only this plugin's agents count: the bare name, or a masthead: name whose last part is the agent.
        counts="$(awk -F'\t' -v s="$session8" -v b="$branch" -v kind="$kind" -v want="$n" '
          function mine(t, name,   parts, k) { k = split(t, parts, ":"); return t == name || (parts[1] == "masthead" && parts[k] == name) }
          $2 == s && $6 ~ /^re-verify/ && (NF < 8 || $8 == b) {
            r = $6; sub(/^re-verify( round)?[[:space:]]*/, "", r)
            if (mine($4, "verifier")) { v[r]++; V++ }
            else if (mine($4, "architecture-reviewer")) { a[r]++; A++ }
          }
          END {
            paired = 0
            for (r in v) if (r in a) paired += (v[r] < a[r] ? v[r] : a[r])
            j = 0
            if (kind == "verifier" && a[want] + 0 > v[want] + 0) j = 1
            if (kind == "architecture-reviewer" && v[want] + 0 > a[want] + 0) j = 1
            print (V + A - paired) " " j
          }' "$log" 2>/dev/null)"
        spent="${counts%% *}"
        joins="${counts##* }"
      fi
      if [ "${joins:-0}" != 1 ] && [ "${spent:-0}" -ge 2 ]; then
        [ -n "$reasons" ] && reasons="$reasons

"
        reasons="${reasons}Re-verify cap: this session has already spent $spent re-verify rounds on this branch, read from the dispatch log at $log, and a change gets at most two. A round is the verifier, the architecture reviewer, or both sent under one round number; the number in the brief adds no round, and an agent that died or was declined still spent its round. What is still on the adjudicator's fix list after the second round goes to the foreman, or to the user when there is none; send no third round."
      fi
    }

    # The architecture reviewer (MAST-34 scenario 6): no claims list, but the ADR's alignment lines and the architecture doc the project records, each in one exact form.
    if [ "$(agent_type)" = architecture-reviewer ]; then
      ALIGN_FORM="the form is a line that is exactly 'ADR alignment:' at column zero, and the next non-blank line is a bullet starting '- ' of at least four words quoting the ADR's lines on how it applies the architecture doc, one bullet each; when the issue builds no ADR, that line reads 'ADR alignment: none, <why>' with the reason in at least three words"
      align_state="$(printf '%s' "$prompt" | awk '
        {
          line = $0; sub(/\r$/, "", line)
          if (!seen) {
            bare = line; gsub(/^[[:space:]>*_#`-]+|^[0-9]+\.[[:space:]]*/, "", bare); gsub(/[*_`]+/, "", bare)
            if (tolower(bare) ~ /^adr alignment[[:space:]]*:/) {
              seen = 1
              if (line ~ /^ADR alignment:[[:space:]]*none,/) {
                rest = line; sub(/^ADR alignment:[[:space:]]*none,[[:space:]]*/, "", rest)
                if (split(rest, words, /[[:space:]]+/) >= 3) print "yes"; else print "short"
                exit
              }
              if (line !~ /^ADR alignment:[[:space:]]*$/) { print "variant"; exit }
            }
            next
          }
          if (line ~ /[^[:space:]]/) {
            if (line ~ /^- [^[:space:]]/ && split(substr(line, 3), words, /[[:space:]]+/) >= 4) print "yes"; else print "short"
            exit
          }
        }
        END { if (!seen) print "missing"; else print "empty" }' | head -1)"
      if [ "$align_state" != yes ]; then
        reasons="Architecture review brief rule: the reviewer checks the change against the ADR's alignment with the architecture doc, so the brief carries those lines; $ALIGN_FORM. Then retry."
      fi

      # The ADR line names a path the reviewer can read, or none: it cannot open a link (round 1, fix F3).
      adr_line="$(printf '%s' "$prompt" | awk '
        {
          line = $0; sub(/\r$/, "", line)
          bare = line; gsub(/^[[:space:]>*_#`-]+|^[0-9]+\.[[:space:]]*/, "", bare); gsub(/[*_`]+/, "", bare)
          if (tolower(bare) ~ /^adr[[:space:]]*:/) {
            if (line ~ /^ADR: [^[:space:]]/) { sub(/^ADR: [[:space:]]*/, "", line); print "line\t" line } else print "variant\t"
            exit
          }
        }' | head -1)"
      case "$adr_line" in
        line$'\t'*://*|variant*|"")
          [ -n "$reasons" ] && reasons="$reasons

"
          reasons="${reasons}Architecture review brief rule: the reviewer reads the ADR from a file and cannot open a link, so the brief has a line that is exactly 'ADR: <path>' at column zero, the ADR's path in this checkout or in the local clone the repo's ADR_DIR fact names (pull it first), or 'ADR: none' when the issue builds no ADR. Then retry." ;;
      esac

      # The doc line names what the project records: project_fact.py --architecture-doc, read for the checkout the dispatch comes from.
      cwd="$(field '.cwd // ""')"
      [ -n "$cwd" ] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"
      recorded=""
      if [ -n "$hook_dir" ] && [ -r "$hook_dir/project_fact.py" ]; then
        recorded="$(CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$cwd}" python3 "$hook_dir/project_fact.py" --root "$cwd" --architecture-doc 2>/dev/null | head -1)"
      fi
      doc_line="$(printf '%s' "$prompt" | awk '
        {
          line = $0; sub(/\r$/, "", line)
          bare = line; gsub(/^[[:space:]>*_#`-]+|^[0-9]+\.[[:space:]]*/, "", bare); gsub(/[*_`]+/, "", bare)
          if (tolower(bare) ~ /^architecture doc[[:space:]]*:/) {
            if (line ~ /^Architecture doc: /) { sub(/^Architecture doc: [[:space:]]*/, "", line); sub(/[[:space:]]+$/, "", line); print "line\t" line }
            else print "variant\t"
            exit
          }
        }' | head -1)"
      doc_kind="${doc_line%%$'\t'*}"
      doc_value="${doc_line#*$'\t'}"
      doc_value="${doc_value//\`/}"
      if [ -n "$recorded" ]; then
        DOC_FORM="this project records its architecture doc at $recorded, so write 'Architecture doc: <that path>' at column zero, as the path from the repository's top or in full"
      else
        DOC_FORM="this project records no architecture doc (project_fact.py --architecture-doc prints nothing), so write 'Architecture doc: none recorded' at column zero, and the reviewer works from the project's principles alone"
      fi
      doc_ok=0
      if [ "$doc_kind" = line ] && [ -n "$doc_value" ]; then
        case "$doc_value" in
          none*|None*)
            [ -z "$recorded" ] && doc_ok=1 ;;
          *)
            if [ -n "$recorded" ]; then
              top="$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$cwd")"
              case "$doc_value" in /*) named="$doc_value" ;; *) named="$top/$doc_value" ;; esac
              named="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$named" 2>/dev/null)"
              [ -n "$named" ] && [ "$named" = "$recorded" ] && doc_ok=1
            fi ;;
        esac
      fi
      if [ "$doc_ok" -ne 1 ]; then
        [ -n "$reasons" ] && reasons="$reasons

"
        reasons="${reasons}Architecture review brief rule: the brief names the architecture doc the reviewer holds the change to, and the check reads one exact form; $DOC_FORM. Then retry."
      fi
      # On a re-verify round it re-checks only the architecture findings a fix addressed, inside the cap (MAST-35 scenario 6).
      reverify_cap architecture-reviewer
      [ -n "$reasons" ] && deny_tool "$reasons"
      exit 0
    fi

    # The form is exact, on purpose: a line that is exactly "Claims:" at column zero, whose next non-blank line is a "- " bullet of at least four words; and, on a re-verify, a line that begins "Re-verify: round N" at column zero. Every other spelling of either label is refused with the form to use, so no variant is ever half-read.
    CLAIMS_FORM="the form is a line that is exactly 'Claims:' at column zero (no marker before it, nothing after the colon), and the next non-blank line is a bullet starting '- ' with at least four words; put the claims under the first Claims: line, since only that one is read"

    # The first "Claims:" line: exact, or a variant that must be refused.
    claims_state="$(printf '%s' "$prompt" | awk '
      {
        line = $0; sub(/\r$/, "", line)
        if (!seen) {
          bare = line; gsub(/^[[:space:]>*_#`-]+|^[0-9]+\.[[:space:]]*/, "", bare); gsub(/[*_`]+/, "", bare)
          if (tolower(bare) ~ /^(what the author )?claims[[:space:]]*:/) {
            seen = 1
            if (line !~ /^Claims:[[:space:]]*$/) { print "variant"; exit }
            next
          }
          next
        }
        if (line ~ /[^[:space:]]/) {
          if (line ~ /^- [^[:space:]]/ && split(substr(line, 3), words, /[[:space:]]+/) >= 4) print "yes"; else print "short"
          exit
        }
      }
      END { if (!seen) print "missing"; else if (seen) print "empty" }' | head -1)"
    case "$claims_state" in
      yes) ;;
      *) reasons="Verification brief rule: a verifier is told what it must confirm, never just handed a diff, and the check reads one exact form: $CLAIMS_FORM. List under it the scenario's Then lines and every sentence a customer reads that the change adds or edits, and no claim of your own (for the security reviewer, the repository's security conventions; for a plan, the plan's lines), one bullet each. Then retry." ;;
    esac

    if [ "$(agent_type)" = verifier ]; then
      reverify_cap verifier
    fi

    [ -n "$reasons" ] && deny_tool "$reasons"
    exit 0
    ;;

  gate-stop)
    # gate-stop: refuse one finish when the session captured nothing; the main session is not exempt.
    [ -f "$dir/captured" ] && exit 0
    # A session refused for quota cannot capture; stand aside.
    [ -f "$dir/refused-unfixable" ] && exit 0
    block_stop "Korium memory protocol: this session captured nothing to Korium. Before finishing, call agent_capture (mcp__korium__agent_capture, or mcp__claude_ai_korium__agent_capture through the hosted connector): the non-obvious decisions and their why, any gotcha or reversal worth the next session knowing, and one summary thought (thought_type handoff or reflection) covering what was done, the key decisions, and the open threads. A session that decided things and wrote no code still has all of that. If nothing durable happened, capture that and say why. If Korium production is unreachable, retry once; if it fails again, STOP AND TELL THE USER in plain chat rather than continuing on local evidence - fixing the connection is his call. This gate refuses only once." "main"
    ;;

  gate-substop)
    # gate-substop: the same for a subagent, whether or not it wrote files.
    [ -f "$dir/captured" ] && exit 0
    [ -f "$dir/refused-unfixable" ] && exit 0
    block_stop "Korium memory protocol: this subagent is returning without writing to Korium. What you report back to your caller IS the capture: call agent_capture (mcp__korium__agent_capture, or mcp__claude_ai_korium__agent_capture through the hosted connector) with your findings, then return the thought_id it gives you so the caller can read the full text back. If nothing durable happened, capture that and say why, which is itself worth knowing. This gate refuses only once." "sub"
    ;;

  *) exit 0 ;;
esac

exit 0
