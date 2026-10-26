#!/usr/bin/env bash
# Korium memory protocol: the gates that make search-before-edit, capture-before-finish and an honest brief mechanical.
# Runs in every repo through shared-run.sh; nothing here names one repository.
#
# Modes, each wired on one hook event:
#   mark-search, mark-capture, mark-codesearch, mark-grep, mark-edit  (PostToolUse) record a search, a capture, a code_locate answer, a Grep/Glob/shell search, an edit
#   gate-edit         refuses the first edit until a Korium search ran
#   gate-discovery    refuses a Grep, Glob or shell search for a name the code index holds until a fresh code_locate lookup
#   gate-redundant-grep, gate-span-read  refuse repeating what code_locate just answered
#   gate-agent, gate-fix-evidence, gate-wave-brief, gate-brief-inference  check a dispatch brief before the agent starts
#   gate-capture      refuses a subagent capture filed under another agent's name
#   gate-stop, gate-substop  refuse one finish with no capture
# Every refusal happens once per session, then stands down. MASTHEAD_<NAME>_GATE=off in the operator's environment switches a gate off.

set -uo pipefail

mode="${1:?usage: engram-protocol.sh <mode>}"
payload="$(cat 2>/dev/null || echo '{}')"

field() { printf '%s' "$payload" | jq -r "$1" 2>/dev/null || echo ""; }

# The dispatched agent: Claude Code sends this plugin's reviewer as masthead:reviewer, or masthead:<folder>:reviewer for one in a subfolder of agents/, so a masthead: name is matched on the part after the last colon. Another plugin's agent keeps its prefix, so it is never taken for ours.
# The masthead: namespace is trusted as this plugin's identity. A fork also named masthead would pass as ours, but reading the name from .claude-plugin/plugin.json would not tell it apart either, since a fork's plugin.json says masthead too.
# Of a masthead: name's parts, the last one naming a masthead agent is the agent, as in the fences; else the last part.
agent_type() {
  local t; t="$(field '.tool_input.subagent_type // ""')"
  case "$t" in
    masthead:*) printf '%s' "${t#masthead:}" | awk -F: '{ for (i = NF; i >= 1; i--) if ($i ~ /^(reviewer|security-reviewer|adjudicator|diagnoser|reader)$/) { printf "%s", $i; exit } printf "%s", $NF }' ;;
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
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
}

# Block once, then stand down (see FAIL-OPEN above).
block_stop() {
  local once="$dir/stop-blocked-$2"
  [ -f "$once" ] && exit 0
  : > "$once"
  jq -n --arg r "$1" '{decision: "block", reason: $r}'
}

# Tell the model, every time, that a capture was refused and why.
report_refusal() {
  jq -n --arg r "$1" '{decision: "block", reason: $r}'
}

# Classify a capture's tool_response: stored, unfixable, rejected or unknown.
capture_outcome() {
  local resp
  resp="$(printf '%s' "$payload" | jq -r '.tool_response | tostring' 2>/dev/null | tr -d '\\ ')"

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

# Flatten a brief to one line so a phrase split by wrapping still matches.
flatten() {
  printf '%s' "$1" | tr -s '[:space:]' ' '
}

# Does this brief ask somebody to write something? Its changes_code declaration decides, else its first instruction line.
brief_instructs_a_source_change() {
  local brief="$1"

  printf '%s' "$brief" | grep -qE '^[[:space:]]*(\*\*)?changes_code:[[:space:]]*true' && return 0
  declares_read_only "$brief" && return 1

  local first
  first="$(printf '%s' "$brief" | awk '
    { line = $0
      sub(/^[[:space:]]+/, "", line)
      if (line == "") next
      if (tolower(line) ~ /^(model-choice|korium|read_only|changes_code)[: ]/) next
      sub(/^#+[[:space:]]*/, "", line)
      sub(/^[-*][[:space:]]*/, "", line)
      sub(/^\*\*/, "", line)
      sub(/^<task>[[:space:]]*/, "", line)
      print line
      exit }')"
  printf '%s' "$first" \
    | grep -qiE '^(fix|implement|repair|harden|refactor|rewrite|migrate|port|delete|remove|add|update|change|adjust|wire|build|write|patch)\b'
}

brief_asks_for_a_write() {
  flatten "$1" \
    | grep -qiE 'fix|repair|patch|implement|harden|commit|sha\b|do not push|mix (format|credo|compile|test)|mutation-prove'
}

# Does this brief declare that it changes nothing (read_only: true, docs only, no code change)?
declares_read_only() {
  printf '%s' "$1" \
    | sed -e 's/^[[:space:]]*[>*_#`-]*[[:space:]]*//' -e 's/[[:space:]*_`]*$//' \
    | grep -v '^[[:space:]]*$' \
    | head -12 \
    | grep -qiE '^(read[_-]?only|readonly)[[:space:]]*:[[:space:]]*(true|yes)$|^(changes[_-]code|code[_-]change|writes[_-]code)[[:space:]]*:[[:space:]]*(false|no)$|^(no code change|read only|read-only|docs only|documentation only|diagnose only|diagnose-only|audit only|changes nothing)[.:!]?$'
}

case "$mode" in
  # mark-search: record the search's query and hit count.
  mark-search)
    : > "$dir/searched"
    q="$(field '.tool_input.query // ""' | tr '\t\n' '  ')"
    resp="$(printf '%s' "$payload" | jq -r '.tool_response | tostring' 2>/dev/null | tr -d '\\ ')"
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
        pat="$(printf '%s' "$found" | jq -r '.pattern // ""' 2>/dev/null)"
        path="$(printf '%s' "$found" | jq -r '.path // ""' 2>/dev/null)"
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
      verdict="$(jq -n --arg t "$tool" --arg p "$pat" --arg d "${path:-}" \
        --arg c "$(field '.cwd // ""')" \
        '{tool:$t,pattern:$p,path:$d,cwd:$c}' 2>/dev/null \
        | python3 "$judge" 2>/dev/null | tr -d '[:space:]')"
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

  # gate-agent: refuse a brief that carries no Korium line when this session found results.
  gate-agent)
    prompt="$(field '.tool_input.prompt // ""')"

    case "${MASTHEAD_BRIEF_GATE:-}" in off|0|false|no) exit 0 ;; esac

    # The blind reviewers and the adjudicator are exempt unless the brief orders a source change.
    case "$(agent_type)" in
      reviewer|security-reviewer|adjudicator)
        brief_instructs_a_source_change "$prompt" || exit 0
        ;;
    esac

    hits=0
    [ -s "$dir/searches.tsv" ] && \
      hits="$(awk -F'\t' '$1 ~ /^[0-9]+$/ && $1 > 0' "$dir/searches.tsv" 2>/dev/null | wc -l | tr -d ' ')"

    if [ "${hits:-0}" -gt 0 ]; then
      # A line that starts with the token and says something after it.
      found="$(printf '%s' "$prompt" | awk '
        { line = $0; sub(/^[[:space:]]+/, "", line)
          if (tolower(substr(line, 1, 7)) == "korium:") {
            r = substr(line, 8); sub(/^[[:space:]]+/, "", r)
            if (length(r) >= 40) { print "yes"; exit }
          } }')"
      [ "$found" = "yes" ] && exit 0
      deny_tool "This session has already searched Korium and got results, and this brief does not pass them on. Sending an agent to re-derive what we are holding pays twice for one answer.

Add a line to the brief that STARTS with 'Korium:' and carries what we know, in at least a sentence:

    Korium: the gate refuses by exit 2 rather than JSON, and its self-test is proof/brief-gates-selftest.sh.

If we searched and Korium had nothing on what this agent needs, say that instead, so it does not go looking for something we have already established is not there:

    Korium: nothing on the reconnect loop; the only hits were about socket auth, which is a different subsystem.

Only a line BEGINNING with the token counts, so a brief that merely mentions Korium does not satisfy this. MASTHEAD_BRIEF_GATE=off in the operator's environment turns it off."
      # deny_tool prints, it does not exit.
      exit 0
    fi

    # A word counts only outside a path.
    printf '%s' "$prompt" | tr -s '[:space:]' '\n' | grep -v '/' | grep -qiE 'engram|korium' && exit 0
    deny_tool "Korium memory protocol: a subagent prompt must carry the memory protocol. Add explicit instructions to (1) run the korium MCP server's agent_search tool before substantive work, (2) capture non-obvious decisions, gotchas, and reversals via its agent_capture tool as they happen, and (3) capture one summary thought before finishing. The tool is mcp__korium__agent_search / mcp__korium__agent_capture on a direct registration, or mcp__claude_ai_korium__* through the hosted connector. Then retry."    ;;

  # gate-capture: refuse a subagent capture filed under another agent's name.
  gate-capture)
    case "${MASTHEAD_CAPTURE_GATE:-}" in off|0|false|no) exit 0 ;; esac
    acting="$(field '.agent_name // .agent_type // ""')"
    [ -n "$acting" ] || exit 0
    claimed="$(field '.tool_input.source_agent // ""')"
    [ -n "$claimed" ] || exit 0
    [ -n "$(field '.tool_input.captured_by // ""')" ] && exit 0

    a="$(printf '%s' "${acting##*:}" | tr 'A-Z' 'a-z')"
    c="$(printf '%s' "${claimed##*:}" | tr 'A-Z' 'a-z')"
    [ "$a" = "$c" ] && exit 0
    case "$c" in "$a"-*|"$a"_*) exit 0 ;; esac
    deny_tool "This capture is filed under '$claimed' but the agent making it is '$acting'. ADR-0120: source_agent is the one field that answers who decided this, and filing under another name falsifies exactly that. Use your own name. If you are genuinely re-filing for an agent whose own capture failed, keep their source_agent and set captured_by to your name, which this gate allows. MASTHEAD_CAPTURE_GATE=off in the operator's environment turns it off."
    ;;

  # gate-fix-evidence: refuse a brief that asks for a fix without saying how the fix is proven.
  gate-fix-evidence)
    prompt="$(field '.tool_input.prompt // ""')"

    # The four read-only agents are exempt unless the brief orders a change.
    case "$(agent_type)" in
      reviewer|security-reviewer|diagnoser|reader)
        brief_instructs_a_source_change "$prompt" || exit 0
        ;;
    esac

    # A read-only brief is exempt.
    declares_read_only "$prompt" && exit 0

    # The same declaration in other words.
    flatten "$prompt" \
      | grep -qiE 'read[ -]?only|diagnose[ -]?only|report findings|never edit|do(es)? not edit|do not change any file|chang(e|es) nothing|no files? (are|is|will be) (changed|modified|edited|written)|makes? no (code )?changes|writes? no code|no code is (written|changed)|without changing any (code|file)|nothing (is|will be) (changed|edited|written)|audit[ -]only|no edits' && exit 0

    # Only briefs that ask somebody to WRITE something.
    brief_asks_for_a_write "$prompt" || exit 0

    # A brief with no failure path to drive opts out.
    flatten "$prompt" \
      | grep -qiE 'docs only|comment only|comments only|no code change|documentation only|no behaviou?r change|behaviou?r-preserving|rename only|pure rename|infrastructure declaration|infra only|no application code|not executable in tests' && exit 0

    # The brief says how the fix is proven.
    flatten "$prompt" \
      | grep -qiE 'test-evidence|test evidence|real failure|really fails|genuinely (absent|fails|failing)|not a stub|rather than a stub|baseline' && exit 0

    deny_tool "Test-evidence rule: a brief that asks for a fix must also say how the fix will be PROVEN, and the proof must drive the REAL failure rather than a stub of it. A stub returning an error tuple does not exit like a dead process and does not poison a transaction like a real failed statement, so a fix proven against one can still be broken in production - this has cost us three review rounds. Add to the brief: what real failure the test must cause (terminate the process, cause a genuine SQL error, revoke the grant, stop the container), and where a real failure is genuinely out of reach, that the test says so in one line instead of implying coverage it does not have. Do NOT ask for the break-it-and-restore ritual; it was dropped on 2026-09-10 because editing working code to watch a test go red and editing it back costs a full loop per fix and proves only that the test reads the line you broke. See docs/conventions/test-evidence-conventions.md. If this brief changes no code at all, declare it and retry: put 'read_only: true' on a line of its own near the top of the brief, or say 'docs only' or 'no code change'. Declare it because it is true, not to get past this gate."
    ;;

  # gate-wave-brief: refuse a brief to reviewer or security-reviewer that states no author claims, or no code outside the diff the change depends on.
  gate-wave-brief)
    subagent="$(agent_type)"
    prompt="$(field '.tool_input.prompt // ""')"

    # Only the two review agents are screened.
    case "$subagent" in
      reviewer|security-reviewer) : ;;
      *) exit 0 ;;
    esac

    # The brief says what the author claims, or where those claims are written.
    reasons=""

    if ! flatten "$prompt" \
      | grep -qiE 'claim|unproven|(could|did|does) not (prove|verify|test)|stays unproven|not tested|untested|(have|has|had) not (proven|verified|tested)|unverified|not verified|builder-claims|author asserts|asserts that'; then
      reasons="Review brief rule: a reviewer must be told what the AUTHOR claims and what the author could not prove, not just handed a diff. On 2026-08-17 the build's own moduledoc said an unrecognised throw 'costs precision and never costs correctness'; it was false, it was the third finding of the day, and it reached no reviewer because the brief carried the patch alone. Add to this brief: the claims the change makes about its own behaviour, and the list of things the author did not test or could not prove. If the author wrote one, name the file. Then retry."
    fi

    # The brief names the unchanged code the change depends on, or says the change is self-contained.
    if ! flatten "$prompt" \
      | grep -qiE 'unchanged|unmodified|untouched|outside (the|this) (diff|patch|change)|not in the diff|beyond the patch|depend(s|ed|ing)? on|lean(s|ed|ing)? on|rel(y|ies|ied|ying) on|call(s|ed|ing)? into|callers? of|call sites?|seams?\b|self-contained|no external dependenc|touches nothing outside'; then
      [ -n "$reasons" ] && reasons="$reasons

"
      reasons="${reasons}Review brief rule: name the code OUTSIDE this diff that the change depends on, so the reviewer reads the seam rather than grading the patch as text. On 2026-08-17 all three findings that changed the code lived in unchanged files and a vendored library. List the modules the change calls into or is called by, or say plainly that it is self-contained if it truly is. Then retry."
    fi

    # One decision carrying every complaint.
    [ -n "$reasons" ] && deny_tool "$reasons"
    exit 0
    ;;

  # gate-brief-inference: refuse a build brief that passes the lead's conclusion off as a rule without saying whose judgment it is.
  gate-brief-inference)
    subagent="$(agent_type)"

    # Every dispatch except the reviewers.
    case "$subagent" in
      reviewer|security-reviewer) exit 0 ;;
      *) : ;;
    esac

    prompt="$(field '.tool_input.prompt // ""')"

    # No impossibility claim, nothing to label.
    printf '%s' "$prompt" \
      | grep -qiE 'cannot be done|can not be done|impossible|no way to|there is no way|is not possible|cannot be made|so we cannot|therefore we cannot|rules? (it|that) out' \
      || exit 0

    # It carries one, and it says whose it is and how to overturn it.
    printf '%s' "$prompt" \
      | grep -qiE 'my (inference|conclusion|reading|assumption)|i (may be|might be|could be) wrong|unverified|not a rule|treat (this|that) as a proposal|disprove|if you (can|think you can) (show|prove|disprove)|say so and do the better thing|verify this yourself|do not take (this|my word)' \
      && exit 0

    deny_tool "Build brief rule: this brief says something cannot be done, and does not say whose judgement that is. A rule the specialist must obey and a conclusion you drew from a rule are different things, and handing over the second as the first is how a false sentence ends up in a moduledoc. On 2026-08-17 a brief said attributing a crash needed either a rescue inside the transaction or the process dictionary and that both were closed. The rule was real, the conclusion was false, a per-call :atomics reference answers it, and the specialist built a whole design inside the mistake because it came from the lead. Rewrite it: state the rule and its source, mark the inference as yours, and tell the specialist to disprove it if they can."
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
