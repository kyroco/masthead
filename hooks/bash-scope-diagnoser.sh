#!/usr/bin/env bash
# bash-scope-diagnoser.sh: PreToolUse Bash hook that lets the diagnoser and reader agents run only test runners, read-only git and gh, and read-only inspection, and denies the rest (exit 2). The architecture reviewer gets only three exact command shapes: git diff, show or log with plain revisions and paths, this plugin's project_fact.py with --tracker or --architecture-doc, and gh issue view <n>.

set -uo pipefail

[ "${DIAGNOSER_BASH_GATE:-on}" = "off" ] && exit 0

INPUT="$(cat)"

if ! command -v jq >/dev/null 2>&1; then
  # Project-wide, this hook reads every session's Bash call: with no jq, read the caller from its identity field in
  # the raw text and leave anyone but the diagnoser and reader alone (MAST-37), as bash-scope-reviewer.sh does.
  if [ "${1:-}" = "--project-wide" ] && ! printf '%s' "$INPUT" | grep -qE "\"(agent_type|subagent_type|agent_name)\"[[:space:]]*:[[:space:]]*\"(masthead:([^\"\\\\]*:)?)?(diagnoser|reader)\""; then
    exit 0
  fi
  echo "DENIED: jq is not installed, so the diagnoser Bash guard cannot read the tool payload." >&2
  echo "The gate fails closed: an unverifiable command is not an allowed command. Install jq, or set DIAGNOSER_BASH_GATE=off if this destination has explicitly accepted the risk." >&2
  exit 2
fi

TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"
[ "$TOOL_NAME" = "Bash" ] || exit 0

# Apply the gate only to the diagnoser, reader and architecture-reviewer agents when run with --project-wide; a main-session call passes.
# Claude Code sends this plugin's agents as masthead:diagnoser; another plugin's agent of the same name is not ours to police.
IS_ARCH=false
if [ "${1:-}" = "--project-wide" ]; then
  NAMES='[.agent_type, .subagent_type, .agent_name] | map(select(type == "string") | if startswith("masthead:") then (ltrimstr("masthead:") | split(":") | .[]) else . end)'
  IS_DIAGNOSER="$(printf '%s' "$INPUT" | jq -r "$NAMES"' | any(. == "diagnoser" or . == "reader" or . == "architecture-reviewer")')"
  [ "$IS_DIAGNOSER" = "true" ] || exit 0
  IS_ARCH="$(printf '%s' "$INPUT" | jq -r "$NAMES"' | any(. == "architecture-reviewer")')"
fi
# The one script the architecture reviewer may run: this plugin's project_fact.py, by its full path.
FACT_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)/project_fact.py"
FACT_ROOT="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/hooks/project_fact.py}"

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty')"
if [ -z "$CMD" ]; then
  echo "DENIED: Bash call carried no readable command string, so the guard cannot check it." >&2
  exit 2
fi

deny() {
  echo "DENIED by the diagnoser Bash guard: $1" >&2
  echo "Command: $CMD" >&2
  echo "Allowed: test runners (mix test, npm test, pytest, cargo test, go test and the like), read-only git (status, diff, log, show, blame, rev-parse, ls-files, describe, grep, shortlog), read-only inspection (ls, cat, head, tail, grep, rg, find and the like), curl to localhost, pipes between those, and redirects into /tmp or /dev/null." >&2
  echo "Denied: changing files or git state, the network beyond this machine, credential reads, and anything the guard cannot check (substitution, variables, subshells, braces, input redirects, multi-line commands, path traversal). The diagnoser diagnoses; it does not fix." >&2
  exit 2
}

# The credential check, applied to every word.
CRED_RE='(^|[/:=])\.env|\.pgpass|\.netrc|(^|/)\.aws(/|$)|(^|/)\.ssh(/|$)|\.gnupg|\.docker/config|\.kube/config|\.npmrc|\.pypirc|\.git-credentials|id_(rsa|dsa|ecdsa|ed25519)|\.(pem|key|p12|pfx)$|(^|/)credentials(\.json)?$|gh/hosts\.yml|\.config/gcloud|\.azure(/|$)|(^|/)secrets?\.(ya?ml|json|env)$'

# --- 0. the architecture reviewer: exact command shapes, and nothing else ---
# Robert, November 15 (MAST-34 comment): its shell allows only exact command shapes and refuses everything
# else, since every list of refused flags left a spelling open. It reads files with Read, Glob and Grep, so it
# needs only these, each as the whole command, its words split by single spaces:
#   git diff, git show or git log, then plain revisions and paths: no flag but a lone --, no quote, variable,
#     glob, pipe, chain or redirect, no path out of the checkout, and nothing set before git or between git and
#     its subcommand;
#   python3 <this plugin>/hooks/project_fact.py --tracker, or --architecture-doc;
#   gh issue view <n>, bare or with --comments.
if [ "$IS_ARCH" = true ]; then
  arch_deny() {
    echo "DENIED by the architecture reviewer's shell guard: $1" >&2
    echo "Command: $CMD" >&2
    echo "Allowed, each as the whole command: git diff, git show or git log with plain revisions and paths (no flag but --); python3 $FACT_SELF --tracker, or --architecture-doc; gh issue view <n>, bare or with --comments. Read files with Read, Glob and Grep." >&2
    exit 2
  }
  A="${CMD#"${CMD%%[! ]*}"}"
  A="${A%"${A##*[! ]}"}"
  for fact in "$FACT_SELF" "$FACT_ROOT"; do
    [ -n "$fact" ] || continue
    case "$A" in
      "python3 $fact --tracker"|"python3 $fact --architecture-doc") exit 0 ;;
    esac
  done
  [[ "$A" =~ ^gh\ issue\ view\ [0-9]+(\ --comments)?$ ]] && exit 0
  case "$A" in
    *[!A-Za-z0-9._/@:^~\ -]*) arch_deny "the command holds a character outside plain revisions and paths (a quote, variable, glob, pipe, chain, redirect, tab or new line)" ;;
  esac
  read -r -a AW <<< "$A"
  [ "${AW[0]:-}" = git ] || arch_deny "'${AW[0]:-}' is not one of its commands"
  case "${AW[1]:-}" in
    diff|show|log) ;;
    *) arch_deny "'git ${AW[1]:-}' is not allowed; only git diff, git show and git log, with nothing between git and the subcommand" ;;
  esac
  for w in "${AW[@]:2}"; do
    case "$w" in
      --) continue ;;
      -*) arch_deny "'$w' is a flag; only plain revisions and paths, and a lone --, follow git ${AW[1]}" ;;
      /*|'~'*) arch_deny "'$w' is a path out of the checkout" ;;
    esac
    [[ "$w" =~ (^|[/:])\.\.(/|$) ]] && arch_deny "'$w' climbs out of the checkout with .."
    printf '%s' "$w" | grep -Eiq "$CRED_RE" && arch_deny "'$w' names a credential file or directory"
  done
  exit 0
fi

# --- 1. what cannot be checked is not allowed ---
NL='
'
case "$CMD" in
  *"$NL"*) deny "multi-line commands are not allowed" ;;
  *'\'*) deny "backslash escapes are not allowed; quote the word instead" ;;
esac
# Path traversal is checked per word, as a whole '..' path component.

# Walk the command once, the way the shell reads quotes, keeping unquoted text in UNQ and refusing separators, redirects and expansions inside quotes.
UNQ=""
QSTATE=N
i=0
while [ "$i" -lt "${#CMD}" ]; do
  c="${CMD:$i:1}"
  case "$QSTATE" in
    N)
      case "$c" in
        "'") QSTATE=S; UNQ="${UNQ}_" ;;
        '"') QSTATE=D; UNQ="${UNQ}_" ;;
        *) UNQ="${UNQ}${c}" ;;
      esac ;;
    S)
      case "$c" in
        "'") QSTATE=N ;;
        ';'|'|'|'&'|'>'|'<') deny "a separator or redirect inside quotes cannot be checked; pass it some other way" ;;
      esac ;;
    D)
      case "$c" in
        '"') QSTATE=N ;;
        '$'|'`') deny "\$ and backticks expand inside double quotes; use single quotes" ;;
        ';'|'|'|'&'|'>'|'<') deny "a separator or redirect inside quotes cannot be checked; pass it some other way" ;;
      esac ;;
  esac
  i=$((i + 1))
done
[ "$QSTATE" = N ] || deny "an unterminated quote"

case "$UNQ" in
  *'`'*|*'$'*) deny "substitution and variables are not allowed; write the literal command" ;;
  *'<'*) deny "input redirection and process substitution are not allowed" ;;
  *'('*|*')'*|*'{'*|*'}'*) deny "subshells and brace groups are not allowed" ;;
esac

# --- 2. normalise fd duplication, then split into simple commands ---
S="$CMD"
S="${S//2>&1/ }"
S="${S//1>&2/ }"
S="${S//>&2/ }"
S="${S//&>>/ >>}"
S="${S//&>/ >}"
# Turn every separator into one so each simple command is checked on its own.
S="${S//&&/;}"
S="${S//||/;}"
S="${S//|/;}"
S="${S//&/;}"

strip_quotes() { printf '%s' "$1" | tr -d "'\"\\\\"; }

# Allow an absolute path only inside the project or a temp dir.
check_abs() {
  local p="$1"
  case "$p" in
    /tmp|/tmp/*|/private/tmp|/private/tmp/*|/dev/null) return 0 ;;
  esac
  [ -n "$CWD" ] || deny "'$p' is an absolute path and the payload carried no working directory to check it against"
  case "$p" in
    "$CWD"|"$CWD"/*) return 0 ;;
  esac
  deny "'$p' is outside the project; absolute paths must stay under $CWD or /tmp"
}

check_word() {
  local raw="$1" w v
  w="$(strip_quotes "$raw")"
  case "$w" in
    ..|../*|*/../*|*/..) deny "path traversal ('..') is not allowed" ;;
  esac
  case "$w" in
    '~'*) deny "'$raw' starts with ~, which expands to a home directory" ;;
  esac
  if printf '%s' "$w" | grep -Eiq "$CRED_RE"; then
    deny "'$raw' names a credential file or directory"
  fi
  v="$w"
  case "$w" in
    -*=*) v="${w#*=}" ;;
  esac
  case "$v" in
    /*) check_abs "$v" ;;
  esac
  # Deny a glob the shell would expand after this check, unless the word is wholly quoted.
  case "$raw" in
    \'*\'|\"*\") ;;
    *'*'*|*'?'*|*'['*) deny "'$raw' is a glob the shell would expand after this check; quote it or name the file" ;;
  esac
  return 0
}

check_redirect_target() {
  local t
  t="$(strip_quotes "$1")"
  [ -n "$t" ] || deny "a redirect with no target"
  case "$t" in
    *..*) deny "path traversal ('..') in a redirect target is not allowed" ;;
    /dev/null) return 0 ;;
  esac
  case "$t" in
    /tmp/*|/private/tmp/*) ;;
    *) deny "a redirect into '$t'; the diagnoser writes nothing to the tree, only to /tmp or /dev/null" ;;
  esac
  case "$t" in
    *'*'*|*'?'*|*'['*|*'~'*) deny "the redirect target '$t' is a pattern, not a file" ;;
  esac
  [ -L "$t" ] && deny "the redirect target '$t' is a symlink, which could point back into the tree"
  return 0
}

# A write or run flag is refused in every spelling a program accepts, not only as an exact word: a short letter
# alone or bundled with others or with its value joined on (-o, -uo, -oFILE), and a long name shortened to any
# prefix, as git and GNU tools take it (--out for --output). Matching a short letter anywhere after one dash
# refuses some harmless bundles too, which is the safe way to be wrong.
# flag_hits <word> <short letters> <long names without dashes>: true when the word is one of those flags.
flag_hits() {
  local word="$1" short="$2" long="$3" name n
  case "$word" in
    --) return 1 ;;
    --*)
      name="${word#--}"; name="${name%%=*}"
      [ -n "$name" ] || return 1
      for n in $long; do
        case "$n" in "$name"*) return 0 ;; esac
      done ;;
    -?*)
      [ -n "$short" ] || return 1
      case "${word#-}" in *["$short"]*) return 0 ;; esac ;;
  esac
  return 1
}

# --- the allowed commands ---
ENV_OK=" MIX_ENV CI NODE_ENV RUST_BACKTRACE RUST_LOG TZ LANG LC_ALL DEBUG VERBOSE FORCE_COLOR NO_COLOR PYTHONDONTWRITEBYTECODE "

check_git() {
  local i t sub
  [ "${#W[@]}" -ge $((H + 2)) ] || deny "git with no subcommand"
  i=$((H + 1))
  while [ "$i" -lt "${#W[@]}" ]; do
    t="${W[$i]}"
    case "$t" in
      *[!A-Za-z0-9._/+@,:=%~^-]*) deny "'$t' holds a character the shell rewrites before git sees it; write plain paths and revisions" ;;
    esac
    i=$((i + 1))
  done
  sub="${W[$((H + 1))]}"
  case "$sub" in
    status|diff|log|show|blame|rev-parse|ls-files|describe|grep|shortlog) ;;
    *) deny "'git $sub' is not allowed; the diagnoser reads history, it does not change it (only status, diff, log, show, blame, rev-parse, ls-files, describe, grep, shortlog)" ;;
  esac
  i=$((H + 2))
  while [ "$i" -lt "${#W[@]}" ]; do
    if flag_hits "${W[$i]}" "O" "output exec upload-pack ext-diff no-index open-files-in-pager"; then
      deny "'${W[$i]}' can write or execute, in this spelling or another; the git allowance is read-only"
    fi
    i=$((i + 1))
  done
}

check_curl() {
  local i t url="" expect=""
  i=$((H + 1))
  while [ "$i" -lt "${#W[@]}" ]; do
    t="$(strip_quotes "${W[$i]}")"
    if [ -n "$expect" ]; then
      case "$expect:$t" in
        data:@*) deny "curl data from a file ('$t') reads a file; pass the data inline" ;;
      esac
      expect=""; i=$((i + 1)); continue
    fi
    case "$t" in
      -i|-I|-s|-S|-v|-sS|-Ss|-si|-is|-sv|-vs|-sSi|-isS|--compressed|--include|--head|--silent|--show-error|--verbose|--fail) ;;
      -X|--request|-H|--header|-m|--max-time|-A|--user-agent) expect=value ;;
      -d|--data|--data-raw|--json) expect=data ;;
      -*) deny "'$t' is not an allowed curl flag (downloads, uploads, config files, proxies, redirects and host overrides are refused)" ;;
      *)
        [ -z "$url" ] || deny "curl takes one URL"
        url="$t" ;;
    esac
    i=$((i + 1))
  done
  [ -z "$expect" ] || deny "a curl flag with no value"
  [ -n "$url" ] || deny "curl with no URL"
  if ! printf '%s' "$url" | grep -Eq '^https?://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?(/|$)'; then
    deny "curl may only reach this machine (localhost, 127.0.0.1, [::1]), not '$url'"
  fi
}

# Allow only reading gh subcommands: nothing that opens a browser, checks out or writes.
check_gh() {
  local i sub="${W[$((H + 1))]:-}" sub2="${W[$((H + 2))]:-}"
  case "$sub:$sub2" in
    issue:view|issue:list|pr:view|pr:list|pr:diff|pr:checks|run:view|run:list) ;;
    *) deny "'gh $sub $sub2' is not allowed; only gh issue view/list, pr view/list/diff/checks and run view/list" ;;
  esac
  i=$((H + 3))
  while [ "$i" -lt "${#W[@]}" ]; do
    case "${W[$i]}" in
      -w|--web) deny "'gh ${W[$i]}' opens a browser; a reader only reads" ;;
    esac
    i=$((i + 1))
  done
}

check_runner() {
  local base="$1" sub="${W[$((H + 1))]:-}" sub2="${W[$((H + 2))]:-}"
  case "$base" in
    mix)
      case "$sub" in
        test|compile|help) ;;
        format) case " ${W[*]} " in *" --check-formatted "*) ;; *) deny "'mix format' rewrites files; only 'mix format --check-formatted' is allowed" ;; esac ;;
        *) deny "'mix $sub' is not allowed; the diagnoser runs mix test, compile, help and format --check-formatted" ;;
      esac ;;
    npm|pnpm|yarn)
      case "$sub" in
        test|t) ;;
        run|run-script) case "$sub2" in test|test:*) ;; *) deny "'$base $sub $sub2' is not allowed; only test scripts run" ;; esac ;;
        *) deny "'$base $sub' is not allowed; the diagnoser runs the project's tests, it does not install or publish" ;;
      esac ;;
    node)
      [ "$sub" = "--test" ] || deny "node runs only as 'node --test <files>'"
      case " ${W[*]} " in
        *" -e "*|*" --eval "*|*" -p "*|*" --print "*|*" -r "*|*" --require "*|*" --import "*|*" --loader "*)
          deny "node code injection flags are not allowed" ;;
      esac ;;
    pytest) ;;
    python|python3)
      [ "$sub" = "-m" ] || deny "python runs only as 'python -m pytest' or 'python -m unittest'"
      case "$sub2" in pytest|unittest) ;; *) deny "python -m $sub2 is not allowed" ;; esac ;;
    cargo)
      case "$sub" in test|build|check) ;; *) deny "'cargo $sub' is not allowed; only test, build and check" ;; esac ;;
    go)
      case "$sub" in test|vet|build) ;; *) deny "'go $sub' is not allowed; only test, vet and build" ;; esac ;;
    bundle)
      [ "$sub" = "exec" ] && [ "$sub2" = "rspec" ] || deny "bundle runs only as 'bundle exec rspec'" ;;
    rspec) ;;
    swift|xcodebuild|dotnet)
      case "$sub" in test|build) ;; *) deny "'$base $sub' is not allowed; only test and build" ;; esac ;;
    gradle|gradlew)
      case "$sub" in test|check|build) ;; *) deny "'$base $sub' is not allowed; only test, check and build" ;; esac ;;
    mvn)
      case "$sub" in test|verify) ;; *) deny "'mvn $sub' is not allowed; only test and verify" ;; esac ;;
    make)
      case "$sub" in test|check) ;; *) deny "'make $sub' is not allowed; only make test and make check" ;; esac ;;
  esac
}

check_reader() {
  local base="$1" i t
  i=$((H + 1))
  while [ "$i" -lt "${#W[@]}" ]; do
    t="${W[$i]}"
    case "$base" in
      sort) flag_hits "$t" "o" "output compress-program" && deny "'sort $t' writes a file, in this spelling or another" ;;
      tree) flag_hits "$t" "o" "" && deny "'tree $t' writes a file" ;;
      file) flag_hits "$t" "C" "compile" && deny "'file $t' writes a compiled magic file" ;;
      date) flag_hits "$t" "s" "set" && deny "'date $t' sets the clock" ;;
      rg) flag_hits "$t" "" "pre" && deny "'rg $t' runs a program on each file" ;;
    esac
    case "$base:$t" in
      find:-delete|find:-exec|find:-execdir|find:-ok|find:-okdir|find:-fprint|find:-fprint0|find:-fprintf|find:-fls)
        deny "find $t can change or execute; only searching is allowed" ;;
      uniq:-*) ;;
      uniq:*) deny "uniq with a file argument can write its output file; pipe into it instead" ;;
    esac
    # Deny recursive searches that could print a credential file without naming it.
    case "$base:$t" in
      grep:--recursive|grep:--dereference-recursive|grep:--directories=*|grep:-d|egrep:--recursive|fgrep:--recursive|diff:--recursive)
        deny "'$base $t' searches files it was not given by name; use rg, which skips hidden and ignored files" ;;
      grep:--*|egrep:--*|fgrep:--*|diff:--*|rg:--*) ;;
      grep:-*[rR]*|egrep:-*[rR]*|fgrep:-*[rR]*|diff:-*r*)
        deny "'$base $t' searches files it was not given by name; use rg, which skips hidden and ignored files" ;;
      rg:-*[u.]*) deny "'rg $t' searches hidden or ignored files, where credentials live" ;;
    esac
    case "$base:$t" in
      rg:--hidden|rg:--no-ignore*|rg:--unrestricted) deny "'rg $t' searches hidden or ignored files, where credentials live" ;;
    esac
    i=$((i + 1))
  done
}

check_segment() {
  local seg="$1" i t op tgt base
  set -f
  # shellcheck disable=SC2206
  local RAW=($seg)
  set +f
  [ "${#RAW[@]}" -ge 1 ] || return 0

  # Take the redirects out, checking each target, and check every other word.
  W=()
  i=0
  while [ "$i" -lt "${#RAW[@]}" ]; do
    t="${RAW[$i]}"
    case "$t" in
      '>'*|'>>'*|'1>'*|'2>'*)
        op="${t#[12]}"
        tgt="${op#>}"; tgt="${tgt#>}"
        if [ -z "$tgt" ]; then
          i=$((i + 1))
          tgt="${RAW[$i]:-}"
        fi
        check_redirect_target "$tgt" ;;
      *'>'*) deny "'$t' hides a redirect inside a word; write it as a separate word" ;;
      *)
        check_word "$t"
        # Keep each word as the shell will pass it, quotes removed.
        W+=("$(strip_quotes "$t")") ;;
    esac
    i=$((i + 1))
  done
  [ "${#W[@]}" -ge 1 ] || deny "a redirect with no command"

  # Skip leading allowlisted environment settings, then an optional `timeout N`.
  H=0
  while [ "$H" -lt "${#W[@]}" ]; do
    case "${W[$H]}" in
      [A-Z_]*=*)
        case "$ENV_OK" in
          *" ${W[$H]%%=*} "*) H=$((H + 1)) ;;
          *) deny "setting ${W[$H]%%=*} is not allowed; only harmless test settings such as MIX_ENV or CI" ;;
        esac ;;
      *) break ;;
    esac
  done
  if [ "${W[$H]:-}" = "timeout" ]; then
    case "${W[$((H + 1))]:-}" in
      [0-9]*) H=$((H + 2)) ;;
      *) deny "timeout takes a duration first" ;;
    esac
  fi
  [ "$H" -lt "${#W[@]}" ] || deny "no command after the settings"

  base="$(strip_quotes "${W[$H]}")"
  case "$base" in
    ./gradlew) base=gradlew ;;
    */*) deny "'$base' runs a program by path; the diagnoser runs the named tools on the allowlist" ;;
  esac
  case "$base" in
    git) check_git ;;
    curl) check_curl ;;
    gh) check_gh ;;
    mix|npm|pnpm|yarn|node|pytest|python|python3|cargo|go|bundle|rspec|swift|xcodebuild|dotnet|gradle|gradlew|mvn|make)
      check_runner "$base" ;;
    ls|cat|head|tail|wc|file|stat|tree|du|grep|egrep|fgrep|rg|find|diff|cmp|sort|uniq|cut|tr|nl|basename|dirname|realpath|readlink|which|type|pwd|echo|printf|date|uname|cd)
      check_reader "$base" ;;
    *) deny "'$base' is not an allowed command" ;;
  esac
}

IFS=';' read -r -a SEGS <<< "$S"
for SEG in "${SEGS[@]}"; do
  case "$SEG" in
    *[![:space:]]*) check_segment "$SEG" ;;
  esac
done
exit 0
