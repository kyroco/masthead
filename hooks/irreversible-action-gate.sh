#!/usr/bin/env bash
# irreversible-action-gate.sh - PreToolUse Bash: refuse a command nothing can undo (force push, hard reset, git clean, --no-verify, tofu destroy, state edits or prod apply, dropped data, deleted memory files).
# Appends every match to a record file in the session directory, fails open on any internal error, and always exits 0 printing a deny decision as JSON or nothing.

set -uo pipefail

INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0

command -v jq >/dev/null 2>&1 || exit 0

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)"
[ "$TOOL" = "Bash" ] || exit 0

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -n "$CMD" ] || exit 0

SID="$(printf '%s' "$INPUT" | jq -r '.session_id // "nosession"' 2>/dev/null || echo nosession)"
RECORD_DIR="${TMPDIR:-/tmp}/claude-irreversible/${SID//[^A-Za-z0-9_-]/}"

# Return the segment's real command: strip leading VAR=value assignments, wrappers and quoted-assignment fragments.
segment_command() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  while printf '%s' "$s" | grep -qE '^[A-Za-z_][A-Za-z0-9_]*='; do
    case "$s" in
      *[[:space:]]*) s="${s#*[[:space:]]}"; s="${s#"${s%%[![:space:]]*}"}" ;;
      *) s=""; break ;;
    esac
  done
  # Strip wrapper commands such as env and sudo, which run the command that follows.
  while :; do
    case "${s%%[[:space:]]*}" in
      env|nohup|nice|time|stdbuf|setsid|command|builtin|sudo|doas)
        s="${s#*[[:space:]]}"; s="${s#"${s%%[![:space:]]*}"}"
        # Skip the wrapper's own flags and assignments; -u takes a name, which goes too.
        while :; do
          case "${s%%[[:space:]]*}" in
            -u) s="${s#*[[:space:]]}"; s="${s#"${s%%[![:space:]]*}"}"
                s="${s#*[[:space:]]}"; s="${s#"${s%%[![:space:]]*}"}" ;;
            --|-*|[A-Za-z_]*=*)
                case "$s" in
                  *[[:space:]]*) s="${s#*[[:space:]]}"; s="${s#"${s%%[![:space:]]*}"}" ;;
                  *) s=""; break ;;
                esac ;;
            *) break ;;
          esac
        done
        ;;
      *) break ;;
    esac
  done

  case "${s%%[[:space:]]*}" in
    *=*|*\"*|*\'*)
      # Re-read from the first governed binary when the first word still holds a quote or equals sign.
      r="$(printf '%s' "$s" \
        | grep -oE '(^|[[:space:]"'"'"'])(git|tofu|terraform|psql|mysql|mix|rm|cp|mv|install|patch|tee|dd|rsync|ed|truncate|sed|perl|awk|python|python3|ruby|node|just|bash|sh|make)["'"'"']?[[:space:]].*' \
        | head -1)"
      [ -n "$r" ] && s="${r#"${r%%[![:space:]]*}"}"
      ;;
  esac
  printf '%s' "$s"
}

# Strip a `bash -c '<payload>'` wrapper down to the payload, up to four levels.
unwrap_dash_c() {
  local s="$1" depth=0 inner
  while [ "$depth" -lt 4 ]; do
    case "${s%%[[:space:]]*}" in
      bash|sh|zsh|/bin/bash|/bin/sh|/bin/zsh) ;;
      *) break ;;
    esac
    printf '%s' "$s" | grep -qE '^[^[:space:]]+[[:space:]]+(-[a-z]*c|--command)([[:space:]]|$)' || break
    inner="$(printf '%s' "$s" | sed -E 's/^[^[:space:]]+[[:space:]]+(-[a-z]*c|--command)[[:space:]]+//')"
    inner="${inner#\'}"; inner="${inner%\'}"
    inner="${inner#\"}"; inner="${inner%\"}"
    [ -z "$inner" ] && break
    s="$(segment_command "$inner")"
    depth=$((depth + 1))
  done
  printf '%s' "$s"
}

# Drop the body of a heredoc that is a plain write to a file; any other heredoc body is scanned like ordinary text.
strip_heredocs() {
  printf '%s' "$1" | awk '
    function is_plain_write(s,   t, n, i, w, tok) {
      # A body is data only when the line is cat or tee with plain paths and redirects before the heredoc; every other shape is scanned.
      if (s !~ /^[[:space:]]*(cat|tee)([[:space:]]|$)/) return 0
      t = s
      sub(/<<-?[[:space:]]*["'"'"']?[A-Za-z_][A-Za-z0-9_]*["'"'"']?/, " ", t)
      # Check every token against a whitelist of flags, paths and redirects.
      n = split(t, tok, /[[:space:]]+/)
      for (i = 1; i <= n; i++) {
        w = tok[i]
        if (w == "") continue
        if (w == "cat" || w == "tee") continue
        if (w ~ /^-[A-Za-z]+$/) continue
        if (w ~ /^>>?$/) continue
        if (w ~ /^>>?["'"'"']?[A-Za-z0-9_.\/~+-]+["'"'"']?$/) continue
        if (w ~ /^["'"'"']?[A-Za-z0-9_.\/~+-]+["'"'"']?$/) continue
        return 0
      }
      return 1
    }
    BEGIN { skip = 0; nheld = 0 }
    {
      # Hold heredoc body lines until the terminator is seen.
      if (skip) {
        if ($0 ~ ("^[[:space:]]*" tag "[[:space:]]*$")) { skip = 0; nheld = 0 }
        else { nheld = nheld + 1; held[nheld] = $0 }
        next
      }
      line = $0
      if (match(line, /<<-?[[:space:]]*["'"'"']?[A-Za-z_][A-Za-z0-9_]*["'"'"']?/) &&
          is_plain_write(line)) {
        tag = substr(line, RSTART, RLENGTH)
        gsub(/[<-]|[[:space:]]|["'"'"']/, "", tag)
        skip = 1; nheld = 0
      }
      print line
    }
    END {
      # An unclosed heredoc fails closed: print the held lines so they are scanned.
      if (skip) { for (i = 1; i <= nheld; i++) print held[i] }
    }
'
}

# Add lines built from the string literals in interpreter code (subprocess, os.system, SQL) so the rules see the commands it runs; the original text is printed too.
surface_invocations() {
  awk '
    # Drop quotes left inside a literal, split on ; and newlines, and print each governed statement once.
    function emit(s,   n, i, p, parts) {
      gsub(/["'"'"'`]/, "", s)
      n = split(s, parts, /[;\n]/)
      for (i = 1; i <= n; i++) {
        p = parts[i]
        sub(/^[[:space:]]*(\/\*[^*]*\*\/[[:space:]]*)*/, "", p)
        # Mark a drop, truncate or alter statement with a sql prefix.
        if (tolower(p) ~ /^(drop|truncate|alter)[[:space:]]/ ||
            tolower(p) ~ /(^|[^a-z0-9_])drop[[:space:]]+(table|database|schema|role|user|policy|owned|column)[[:space:]]/) p = "sql " p
        if (tolower(p) !~ governed || (p in seen)) continue
        seen[p] = 1
        print p
      }
    }
    # Join each string literal into every open group and print a group when it closes; sh means shell text and ml means it spans lines.
    function surface(code, rec, ml, sh,   n, i, c, e, q, lit, depth, k, grp, glue, tri) {
      n = length(code); depth = 0; grp[0] = ""; glue = 0
      for (i = 1; i <= n; i++) {
        c = substr(code, i, 1)
        if (c == "\"" || c == "'"'"'" || c == "`") {
          q = c; lit = ""
          tri = !sh && substr(code, i, 3) == q q q
          if (tri) i += 2
          for (i++; i <= n; i++) {
            c = substr(code, i, 1)
            if (c == "\\" && i < n && !(sh && q == "'"'"'")) {
              e = substr(code, i + 1, 1)
              if (sh && e !~ /["\\$`]/) { lit = lit c; continue }
              i++
              lit = lit (sh ? e : ((e == "n" || e == "r") ? "\n" : ((e == "t") ? " " : e)))
              continue
            }
            if (tri) { if (substr(code, i, 3) == q q q) { i += 2; break } }
            else if (c == q) break
            # A quote not closed on its line ends there, so a stray apostrophe in a comment cannot swallow the code below.
            else if (c == "\n" && q != "`" && !ml) break
            lit = lit c
          }
          for (k = 0; k <= depth; k++) grp[k] = grp[k] ((grp[k] == "" || glue) ? "" : " ") lit
          glue = 1
          if (rec < 3 && lit ~ /["'"'"'`(]/) surface(lit, rec + 1, 0, 0)
          continue
        }
        if (c == "+" || c == " " || c == "\t") continue
        glue = 0
        if (c == "(" || c == "[") { grp[++depth] = ""; continue }
        if ((c == ")" || c == "]") && depth > 0) { emit(grp[depth--]); continue }
        if (depth == 0 && (c == "\n" || c == ";" || c == "{" || c == "}")) { emit(grp[0]); grp[0] = "" }
      }
      while (depth >= 0) emit(grp[depth--])
    }
    # Split shell text into pipeline stages, treating a separator inside quotes as text; returns the stage count.
    function stages(s, s_, p_, a_,   n, i, c, q, k) {
      n = length(s); k = 1; s_[1] = ""; p_[1] = ""; a_[1] = 1; q = ""
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (q == "'"'"'") { s_[k] = s_[k] c; if (c == "'"'"'") q = ""; continue }
        if (c == "\\") { s_[k] = s_[k] c substr(s, i + 1, 1); i++; continue }
        if (q == "\"") { s_[k] = s_[k] c; if (c == "\"") q = ""; continue }
        if (c == "'"'"'" || c == "\"") { q = c; s_[k] = s_[k] c; continue }
        if (c == "|" || c == ";" || c == "&" || c == "(" || c == "\n") {
          k++; s_[k] = ""; p_[k] = c; a_[k] = i + 1; continue
        }
        s_[k] = s_[k] c
      }
      return k
    }
    # Does this one stage run an interpreter, however wrapped? Sets kind.
    function code_stage(t,   w) {
      gsub(/[\\"'"'"'`]/, "", t)
      sub(/^[[:space:]]*/, "", t)
      w = t; sub(/[[:space:]].*/, "", w); sub(/.*\//, "", w)
      if (w ~ textcmd) return 0
      if (t ~ sqlcli) { kind = "sql"; return 1 }
      if (t ~ interp) { kind = "code"; return 1 }
      return 0
    }
    # Read the stages of shell text that run code, and the stage that feeds one through a pipe.
    function surface_shell(s, ml,   n, k, s_, p_, a_) {
      n = stages(s, s_, p_, a_)
      for (k = 1; k <= n; k++) {
        if (!code_stage(s_[k])) continue
        surface(s_[k], 0, ml, 1)
        if (k > 1 && p_[k] == "|") surface(s_[k - 1], 0, ml, 1)
      }
    }
    # The quote state after reading s from state st, as the shell reads it.
    function quote_step(s, st,   n, i, c) {
      n = length(s)
      for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (st == "'"'"'") { if (c == "'"'"'") st = ""; continue }
        if (c == "\\") { i++; continue }
        if (st == "\"") { if (c == "\"") st = ""; continue }
        if (c == "'"'"'" || c == "\"") st = c
      }
      return st
    }
    # Find the first line after i that is exactly this tag, from an index built as the lines arrive.
    function terminator(tag, i,   n, m, ps) {
      n = split(T[tag], ps, " ")
      for (m = 1; m <= n; m++) if (ps[m] + 0 > i) return ps[m] + 0
      return N + 1
    }
    BEGIN {
      # `=` because `x=`python3 ...`` is an interpreter once its backticks go.
      w = "(^|[[:space:]/=])"
      interp = w "(python[0-9.]*|node|nodejs|deno|bun|ruby|perl|php|elixir|mix|lua|osascript|awk|bash|sh|zsh|dash|ksh|pwsh|powershell|ssh)([[:space:]<]|$)"
      sqlcli = w "(psql|mysql|sqlite3)([[:space:]<]|$)"
      textcmd = "^(git|gh|echo|printf|rg|grep|jq)$"
      governed = "(^|[^a-z0-9_-])(git|tofu|terraform|terragrunt|psql|mysql|mix|rm|sql)([^a-z0-9_-]|$)"
    }
    {
      print
      L[++N] = $0
      t = $0; gsub(/^[[:space:]]+|[[:space:]]+$/, "", t)
      if (t ~ /^[A-Za-z_][A-Za-z0-9_]*$/) T[t] = T[t] " " N
    }
    END {
      for (i = 1; i <= N; i++) {
        line = L[i]
        # Start a heredoc only where the shell would: outside single quotes, outside double quotes unless a $( is open, and not after a comment.
        if (match(line, /<<-?[[:space:]]*\\?["'"'"']?[A-Za-z_][A-Za-z0-9_]*["'"'"']?/) &&
            substr(line, RSTART + 2, 1) != "<" && (RSTART == 1 || substr(line, RSTART - 1, 1) != "<")) {
          hpos = RSTART
          tag = substr(line, RSTART, RLENGTH)
          gsub(/[<\\-]|[[:space:]]|["'"'"']/, "", tag)
          pre = substr(line, 1, hpos - 1)
          qs = quote_step(pre, "")
          if ((qs == "" || (qs == "\"" && pre ~ /\$\(/)) && pre !~ /(^|[[:space:]])#/) {
            j = terminator(tag, i)
            # The heredoc is code when the pipeline it belongs to runs code.
            n = stages(line, S, P, A)
            for (k = n; k > 1 && A[k] > hpos; k--) ;
            lo = k; while (lo > 1 && P[lo] == "|") lo--
            hi = k; while (hi < n && P[hi + 1] == "|") hi++
            code = 0
            for (m = lo; m <= hi; m++) if (code_stage(S[m])) { code = 1; break }
            # An unterminated heredoc runs to the end of the input, so an interpreter reading one gets every remaining line.
            if (code || j <= N) {
              surface_shell(line, 0)
              if (code) {
                body = ""
                for (m = i + 1; m < j && m <= N; m++) body = body L[m] "\n"
                if (kind == "sql") emit(body)
                else surface(body, 0, 0, 0)
              }
              i = (j <= N) ? j : N
              continue
            }
          }
        }
        qs = quote_step(line, "")
        text = line
        for (j = i; qs != "" && j < N; ) { j++; text = text "\n" L[j]; qs = quote_step("\n" L[j], qs) }
        surface_shell(text, j > i)
        i = j
      }
    }
  '
}

# Pass on only the segments that name a command and a word a rule reads, so a long script is not run through the slow loop; a new rule needs its words added here.
can_match() {
  awk '
    {
      t = tolower($0)
      gsub(/[\\"'"'"'`]/, "", t)
      if ((t ~ /(^|[^a-z0-9_-])git([^a-z0-9_-]|$)/ && t ~ /push|reset|clean|no-verify/) ||
          (t ~ /(^|[^a-z0-9_-])(tofu|terraform|terragrunt)([^a-z0-9_-]|$)/ &&
           t ~ /destroy|state|taint|import|force-unlock|apply/) ||
          (t ~ /(^|[^a-z0-9_-])(psql|mysql|mix|sql)([^a-z0-9_-]|$)/ && t ~ /drop|truncate/) ||
          (t ~ /(^|[^a-z0-9_-])rm([^a-z0-9_-]|$)/ && t ~ /memory|claude\.md/)) { print; next }
      # Pass a glob that could spell a command name: in the command word past any assignment or wrapper, or in any path word.
      w = $0; sub(/^[[:space:]]*/, "", w)
      while (sub(/^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+/, "", w)) {}
      while (sub(/^(sudo|doas|env|nohup|nice|time|command|builtin|exec|setsid|stdbuf)([[:space:]]+-[^[:space:]]+)*[[:space:]]+/, "", w)) {}
      sub(/[[:space:]].*/, "", w)
      # `[` and `[[` are the test command, not a glob.
      if ((w ~ /[][?*]/ && w !~ /^\[\[?$/) ||
          $0 ~ /[^[:space:]]*\/[^[:space:]]*[][?*]|[][?*][^[:space:]]*\//) print
    }
  '
}

deny() {
  # Record the attempt before refusing; a failure to record never changes the decision.
  mkdir -p "$RECORD_DIR" 2>/dev/null && \
    printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$CMD" \
    >> "$RECORD_DIR/attempts.tsv" 2>/dev/null || true

  jq -n --arg r "$1"$'\n\n'"$2"$'\n\nCommand: '"$CMD" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }' 2>/dev/null
  exit 0
}

# Judge each segment (split on ; | & and newlines, after strip_heredocs) so a path or message that merely contains a word is not treated as running it.
while IFS= read -r seg; do
  seg="$(segment_command "$seg")"
  # Unwrap a bash -c payload and judge that instead, repeatedly since -c can nest.
  seg="$(unwrap_dash_c "$seg")"
  seg="${seg#"${seg%%[![:space:]]*}"}"
  [ -n "$seg" ] || continue
  # Re-read the segment with the command bare name in front, with globs expanded and quotes and backslashes removed.
  word="${seg%%[[:space:]]*}"
  # shellcheck disable=SC2086
  set -- $word
  first="${1:-$word}"
  first="${first//\\/}"; first="${first//\"/}"; first="${first//\'/}"
  first="${first##*/}"
  seg="$first${seg#"$word"}"
  # Unquote a whole word that is one quoted flag, running each pattern twice so adjacent quoted flags both come off.
  seg="$(printf '%s' "$seg" | sed -E \
    -e "s/(^|[[:space:]])\"([-+][^\"[:space:]]*)\"([[:space:]]|\$)/\\1\\2\\3/g" \
    -e "s/(^|[[:space:]])'([-+][^'[:space:]]*)'([[:space:]]|\$)/\\1\\2\\3/g" \
    -e "s/(^|[[:space:]])\"([-+][^\"[:space:]]*)\"([[:space:]]|\$)/\\1\\2\\3/g" \
    -e "s/(^|[[:space:]])'([-+][^'[:space:]]*)'([[:space:]]|\$)/\\1\\2\\3/g")"
  # Strip git global options such as -C and -c that come before the subcommand.
  [ "$first" = git ] && seg="$(printf '%s' "$seg" | sed -E \
    "s/^git(([[:space:]]+(-C|-c|--git-dir|--work-tree|--namespace|--exec-path|--super-prefix|--config-env)[[:space:]]+(\"[^\"]*\"|'[^']*'|[^[:space:]]+))|([[:space:]]+-[^[:space:]]+))*/git/")"

  case "$first" in
    git)
      # Refuse a force push, which rewrites history other clones already have.
      printf '%s' "$seg" | grep -qE '^[[:space:]]*git[[:space:]]+push([[:space:]]|$)' &&
        # -f in a bundle of short flags and a + refspec force the push too.
        printf '%s' "$seg" | grep -qE '(^|[[:space:]])(-[a-zA-Z]*f[a-zA-Z]*|--force|--force-with-lease)([[:space:]=]|$)|[[:space:]]\+[^[:space:]]' &&
        deny "Force-pushing rewrites history that other clones already have." \
             "Push normally instead. If the branch really has to be rebuilt, that is the operator's call to make while awake, because anyone who already pulled these commits keeps a different history."

      # Refuse a hard reset, which discards uncommitted work with no copy.
      printf '%s' "$seg" | grep -qE '^[[:space:]]*git[[:space:]]+reset([[:space:]]|$)' &&
        printf '%s' "$seg" | grep -qE '(^|[[:space:]])--hard([[:space:]]|$)' &&
        deny "A hard reset throws away every uncommitted change, and nothing has a copy." \
             "Run 'git stash' first if you want the working tree clean, or 'git checkout' the specific files you meant. Both keep the work."

      # Refuse git clean, which deletes untracked files.
      printf '%s' "$seg" | grep -qE '^[[:space:]]*git[[:space:]]+clean([[:space:]]|$)' &&
        printf '%s' "$seg" | grep -qE '(^|[[:space:]])-[a-zA-Z]*[fdx]' &&
        deny "'git clean' deletes untracked files, and untracked means nothing has a copy." \
             "List what would go with 'git clean -nd' first, then delete the specific files you actually meant."

      # Refuse --no-verify, which bypasses the checks before a commit or push.
      printf '%s' "$seg" | grep -qE '(^|[[:space:]])--no-verify([[:space:]]|$)' &&
        deny "'--no-verify' turns off the checks that run before a commit or a push." \
             "Run the checks and fix what they find. If one of them is wrong, fix the check; skipping it hides the same problem from everyone else too."
      ;;

    tofu|terraform|terragrunt)
      # terragrunt is included because it wraps these subcommands.
      IAC='(tofu|terraform|terragrunt)'

      # Refuse destroy, which tears down infrastructure with no undo.
      printf '%s' "$seg" | grep -qE "^[[:space:]]*${IAC}[[:space:]]+destroy([[:space:]]|\$)" &&
        deny "'destroy' tears down the infrastructure and everything living on it." \
             "If this is a real teardown, it is the operator's decision while awake. If you only wanted to see what would change, run 'plan'."

      # Refuse direct state edits (rm, mv, push, replace-provider), which can orphan or delete live infrastructure.
      printf '%s' "$seg" | grep -qE "^[[:space:]]*${IAC}[[:space:]]+state[[:space:]]+(rm|mv|push|replace-provider)([[:space:]]|\$)" &&
        deny "This edits the state file directly, and the state file is the only record of what actually exists." \
             "A wrong entry here either orphans live infrastructure or makes the next apply delete something. Say what you are trying to reconcile and let the operator do it with a state backup in hand."

      printf '%s' "$seg" | grep -qE "^[[:space:]]*${IAC}[[:space:]]+(taint|untaint|import|force-unlock)([[:space:]]|\$)" &&
        deny "This rewrites what the state believes, outside of a plan." \
             "'taint' schedules a real resource for replacement, 'import' adopts one that nothing here created, and 'force-unlock' removes the lock that stops two applies running at once. Each is the operator's call while awake."

      # Refuse an apply when the whole command line mentions prod.
      printf '%s' "$seg" | grep -qE "^[[:space:]]*${IAC}[[:space:]]+apply([[:space:]]|\$)" &&
        printf '%s' "$CMD" | grep -qiE 'prod' &&
        deny "This applies infrastructure changes to production, where customers are." \
             "Run 'plan' and have the operator read it. A production apply is their call, and a bare apply on the prod root has taken the site down before by rolling onto placeholder images."
      ;;

    # sql is a prefix surface_invocations adds to a statement that reached this gate with no client named.
    psql|mysql|mix|sql)
      # Refuse dropping or truncating data; ALTER TABLE drops of NOT NULL, DEFAULT or CONSTRAINT are not read.
      printf '%s' "$seg" | grep -qiE 'drop[[:space:]]+(table|database|schema|role|user|policy|owned)|truncate[[:space:]]+(table[[:space:]]+)?(only[[:space:]]+)?[A-Za-z_"][^[:space:];,]*[[:space:]]*(;|,|$|restart|continue|cascade|restrict)|drop[[:space:]]+column|ecto\.drop' &&
        deny "This drops data, and getting it back needs a backup that may not exist." \
             "This workspace is forward-only: add a column, backfill it, and remove the old path in a later deploy. If data really must go, the operator decides that awake."
      ;;

    rm)
      # Refuse deleting a memory file, which no build step can rebuild.
      printf '%s' "$seg" | grep -qE '/\.claude[^/]*/.*/memory/|MEMORY\.md|CLAUDE\.md' &&
        deny "That deletes a memory file, and memory is the one thing here that no build step can rebuild." \
             "If the memory is wrong, rewrite it so the next session reads the correct thing. If it genuinely has to go, the operator removes it themselves."
      ;;
  esac
done <<EOF
$(strip_heredocs "$CMD" | surface_invocations | tr ';|&' '\n' | can_match)
EOF

# Allow everything no rule refused.
exit 0
