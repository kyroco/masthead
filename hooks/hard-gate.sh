#!/usr/bin/env bash
# hard-gate.sh -- the done gate for every stack: a PreToolUse hook on Bash that runs on `git push` and `gh pr create`,
# and on a GitHub connector's create_pull_request.
# It blocks (exit 2) when a check on the files the branch changed fails; every other command passes.

set -uo pipefail

case "${MASTHEAD_DONE_GATE:-on}" in off|0|false|no) exit 0 ;; esac

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)"
# Print one fact about the repo at ROOT, or nothing.
project_fact() {
  local root="$1"
  shift
  python3 "$_HOOK_DIR/project_fact.py" --root "$root" "$@" 2>/dev/null
}

# Read the PreToolUse JSON and gate only a command that pushes or opens a PR; the match is loose on purpose.
_PAYLOAD=""
if [ ! -t 0 ]; then
  _PAYLOAD="$(cat 2>/dev/null || true)"
fi
# Pass any call that is not a push before starting an interpreter.
case "$_PAYLOAD" in
  *push*|*"pr create"*|*create-pr*|*create_pull_request*) ;;
  *) exit 0 ;;
esac
# Parse the payload in one python3 call: the cwd on the first line, the command after it.
# A GitHub connector's create_pull_request opens a PR the way `gh pr create` does, so it is read as that (issue #27).
_PARSED="$(printf '%s' "$_PAYLOAD" | python3 -c 'import json,re,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
print(d.get("cwd",""))
if re.match(r"^mcp__.+__create_pull_request$", str(d.get("tool_name") or "")): print("gh pr create")
else: print((d.get("tool_input") or {}).get("command",""))' 2>/dev/null || true)"
_CWD="$(printf '%s\n' "$_PARSED" | head -1)"
_CMD="$(printf '%s\n' "$_PARSED" | tail -n +2)"
# The Python that reads the words of the command. It is held in a plain here-document, outside any $( ),
# because bash 3.2 reads a quote or a backtick in a here-document nested inside $( ) as its own.
_CMD_READER=""
IFS= read -r -d '' _CMD_READER <<'PYEOF' || true
import re, subprocess, sys
# Two questions about one command. "opens-pr CMD" prints no when a create-pr.sh the command names is
# only read, and yes otherwise. "sends CMD HEAD_TREE" prints what a push sends: skip, check, or other REFSPEC.
mode, cmd = sys.argv[1], sys.argv[2]
VALUED = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
# Commands that read, search, list, copy or mark a file and have no option that runs a program.
# Anything not named here that names create-pr.sh is taken for a run of it: the match stays loose that way round.
# rg (--pre), sort (--compress-program), bat, less and more (a pager) and gh (a shell alias) each take a program
# to run, so they are not here. sed is here, and its script is read first: see sed_reads.
READERS = {
    "cat", "head", "tail", "sed", "grep", "egrep", "fgrep", "ls", "wc", "nl", "cut",
    "uniq", "file", "stat", "du", "tree", "diff", "cmp", "jq", "tr", "column", "echo", "printf", "test", "[",
    "true", "false", "cd", "pwd", "chmod", "touch", "cp", "mv", "rm", "mkdir", "tee", "basename", "dirname",
    "readlink", "realpath", "md5", "md5sum", "shasum", "sha256sum", "shellcheck", "shfmt",
}
# One sed command that prints, deletes, quits, counts, moves text between its two buffers or substitutes: an
# optional address or pair of addresses (a line number, $, or /regex/), an optional !, then the command. A
# substitution may carry only the flags g, p, i, I and a number. GNU sed's e command and e flag run a program,
# and r, w and the w flag name a file, so none of those fit.
SED_ADDRESS = r"(?:[0-9]+|\$|/(?:[^/\\\n]|\\.)*/)"
SED_COMMAND = re.compile(
    r"\s*(?:" + SED_ADDRESS + r"(?:\s*,\s*(?:\+[0-9]+|" + SED_ADDRESS + r"))?)?\s*!?\s*"
    r"(?:[pdq=nNPDhHgGx]"
    r"|s(?P<cut>[/|,#:@%])(?:(?!(?P=cut))[^\\\n]|\\.)*(?P=cut)(?:(?!(?P=cut))[^\\\n]|\\.)*(?P=cut)[gpiI0-9]*)"
    r"\s*")
SED_PLAIN_OPTIONS = {"--posix", "--quiet", "--silent", "--regexp-extended", "--separate", "--unbuffered", "--null-data"}
# The git commands that do the same. bisect, rebase, grep, submodule and the rest can run a command, so they are not here.
GIT_READERS = {
    "add", "annotate", "blame", "cat-file", "checkout", "commit", "diff", "log", "ls-files", "ls-tree", "mv",
    "restore", "rm", "show", "status",
}
GIT_PLAIN_OPTIONS = {"--no-pager", "-P", "--no-optional-locks", "--literal-pathspecs"}


def shell_words(seg):
    """Split one command into words the way a shell does, leaving out its redirections:
    2>&1, >file, >>file, &>file, <file, and an operator whose target is the next word.
    A quoted or escaped > or < is part of a word, as it is to the shell."""
    words, cur, plain, drop, i, n = [], None, True, False, 0, len(seg)
    while i <= n:
        c = seg[i] if i < n else " "
        redirect = c in "<>" or (c == "&" and seg[i + 1:i + 2] == ">")
        if c in " \t\r\n" or redirect:
            # A word made only of the bare digits 0 to 9, right against the operator, is its file descriptor.
            # Only those ten: str.isdigit() and \d also take digits of other scripts, which the shell reads as a word.
            if redirect and cur is not None and plain and re.fullmatch(r"[0-9]+", cur):
                cur = None
            if cur is not None:
                if drop:
                    drop = False  # this word was the target of the redirect before it
                else:
                    words.append(cur)
            cur, plain = None, True
            if redirect:
                while i < n and seg[i] in "<>&|":
                    i += 1
                drop = True
                continue
        elif c == "'":
            end = seg.find("'", i + 1)
            if end < 0:
                raise ValueError("no closing quote")
            cur, plain, i = (cur or "") + seg[i + 1:end], False, end
        elif c == '"':
            cur, plain, i = cur or "", False, i + 1
            while i < n and seg[i] != '"':
                if seg[i] == "\\" and seg[i + 1:i + 2] in ('"', "\\", "$", "`"):
                    i += 1
                cur += seg[i]
                i += 1
            if i >= n:
                raise ValueError("no closing quote")
        elif c == "\\":
            if i + 1 >= n:
                raise ValueError("nothing after the backslash")
            cur, plain, i = (cur or "") + seg[i + 1], False, i + 1
        else:
            cur = (cur or "") + c
        i += 1
    return words


def loose_words(seg):
    """The same for a piece shell_words cannot read (a quote cut in half): split on spaces, drop what is shaped like a redirect."""
    words, drop = [], False
    for word in seg.split():
        if drop:
            drop = False
        elif re.match(r"^([0-9]*|&)[<>]", word):
            drop = re.match(r"^([0-9]*|&)[<>]+[&|]?$", word) is not None
        else:
            words.append(word)
    return words


def sed_script_reads(script):
    """Whether every command of a sed script is one SED_COMMAND takes, with ; or a newline between them."""
    at = 0
    while True:
        found = SED_COMMAND.match(script, at)
        if not found:
            return False
        at = found.end()
        if at == len(script):
            return True
        if script[at] not in ";\n":
            return False
        at += 1
        if at == len(script):
            return True


def sed_reads(words):
    """Whether a sed command only reads or edits text: each script is one sed_script_reads takes, and no option
    names a script file (-f) or is one this reader does not know."""
    scripts, others, named, i = [], [], False, 1
    while i < len(words):
        word = words[i]
        if word in ("-e", "--expression"):
            if i + 1 >= len(words):
                return False
            scripts.append(words[i + 1])
            named, i = True, i + 2
            continue
        if word.startswith("--expression="):
            scripts.append(word.split("=", 1)[1])
            named = True
        elif word == "-i" and words[i + 1:i + 2] == [""]:
            i += 1  # BSD sed: -i takes its backup suffix as the next word, and '' means none
        elif word in SED_PLAIN_OPTIONS or re.fullmatch(r"-[nErsuz]+|-i.*|--in-place(=.*)?", word):
            pass
        elif word.startswith("-") and word != "-":
            return False
        else:
            others.append(word)
        i += 1
    if not named:
        if not others:
            return False
        scripts.append(others[0])
    return all(sed_script_reads(script) for script in scripts)


def parts(text):
    """The commands in one command line, cut at newlines, ;, &&, || and |, quotes not read."""
    return re.split(r"\n|;|&&|\|\||\|", text)


def drop_assignments(words):
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words.pop(0)
    return words


def shell_parts(text):
    """The commands in one command line, cut where the shell cuts them: at a newline, ;, &&, ||, | or a lone &
    that is not inside quotes, with a line continued by a backslash joined first. Also says what the line holds
    that this reader does not follow: a command inside it ($( ), backticks, <( ), >( ), which stay live inside
    double quotes), a command sent to the background, or a here-document. Raises ValueError on a quote left open."""
    pieces, holds, cur, quote, i, n = [], set(), "", None, 0, len(text)
    while i < n:
        c, two = text[i], text[i:i + 2]
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == "\\" and i + 1 < n:
            if text[i + 1] != "\n":
                cur += two
            i += 2
            continue
        elif two == "$(" or c == "`":
            holds.add("a command inside it")
        elif quote == '"':
            quote = None if c == '"' else quote
        elif c in "'\"":
            quote = c
        elif text[i:i + 3] == "<<<":
            cur, i = cur + "<<<", i + 3
            continue
        elif two in ("<(", ">("):
            holds.add("a command inside it")
        elif two == "<<":
            holds.add("a here-document")
        elif two in ("&&", "||") or c in ";|\n":
            pieces.append(cur)
            cur, i = "", i + (2 if two in ("&&", "||") else 1)
            continue
        elif c == "&" and not (text[i - 1:i] in ("<", ">") or text[i + 1:i + 2] == ">"):
            holds.add("a command sent to the background")
            pieces.append(cur)
            cur, i = "", i + 1
            continue
        cur += c
        i += 1
    if quote:
        raise ValueError("no closing quote")
    pieces.append(cur)
    return pieces, holds


def only_reads(text):
    """Whether every part of the command is a plain file command, so a create-pr.sh it names is read and not run."""
    try:
        pieces, holds = shell_parts(text)
    except ValueError:
        return False
    if holds:
        return False
    for seg in pieces:
        try:
            words = shell_words(seg)
        except ValueError:
            return False
        if not words:
            continue
        # A NAME=value before the command can hand it a program to run (GIT_EXTERNAL_DIFF, GIT_EDITOR, PAGER),
        # so its value would have to be read too. A command that sets one is not taken for a read.
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            return False
        name = words[0].rsplit("/", 1)[-1]
        if name == "git":
            i = 1
            while i < len(words) and words[i].startswith("-"):
                if words[i] == "-C":
                    i += 2
                elif words[i] in GIT_PLAIN_OPTIONS:
                    i += 1
                else:
                    return False  # -c and the like can name a command to run
            if i >= len(words) or words[i] not in GIT_READERS:
                return False
        elif name not in READERS:
            return False
        elif name == "sed" and not sed_reads(words):
            return False
    return True


runs_create_pr = "create-pr.sh" in cmd and not only_reads(cmd)
if mode == "opens-pr":
    print("yes" if runs_create_pr or "create-pr.sh" not in cmd else "no")
    sys.exit(0)

head_tree = sys.argv[3]
# One answer for the whole command, the same one the top of the gate acts on: a command taken for a run of
# create-pr.sh opens a PR however the name reaches the shell (a word, a redirect, a here-string), so it needs the receipt.
verdict = "check" if runs_create_pr else "skip"
# Two readings of the command, and a push that either one shows is read. The first cuts the line without
# reading quotes, as this gate always has, so a push written inside a quoted command line is still seen. The
# second cuts it where the shell does, so a push whose words a line continuation, or a ; or | inside quotes,
# would split is read whole.
readings = []
for seg in parts(cmd):
    try:
        readings.append(shell_words(seg))
    except ValueError:
        readings.append(loose_words(seg))
try:
    readings.extend([shell_words(seg) for seg in shell_parts(cmd)[0]])
except ValueError:
    pass  # a quote left open: only the first reading stands
for words in readings:
    words = drop_assignments(words)
    if not words:
        continue
    joined = " ".join(words)
    if re.search(r"(^|\s)gh\s+pr\s+create(\s|$)", joined):
        verdict = "check" if verdict == "skip" else verdict
        continue
    if words[0] != "git":
        continue
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in ("-C", "-c") else 1
    if i >= len(words) or words[i] != "push":
        continue
    args, deleting, positional = words[i + 1:], False, []
    j = 0
    while j < len(args):
        a = args[j]
        if a in ("--delete", "-d"):
            deleting = True
        elif a in ("--all", "--mirror", "--branches"):
            print("other " + a)
            sys.exit(0)
        elif a in VALUED:
            j += 1
        elif not a.startswith("-"):
            positional.append(a)
        j += 1
    refspecs = positional[1:]
    if deleting:
        continue
    if not refspecs:
        verdict = "check"
        continue
    for spec in refspecs:
        src = spec.lstrip("+").split(":", 1)[0]
        if src == "":
            continue  # ":branch" deletes it
        if not head_tree:
            verdict = "check"  # no commit yet: nothing to compare, the check decides
            continue
        tree = subprocess.run(["git", "rev-parse", "--verify", "-q", src + "^{tree}"],
                              capture_output=True, text=True).stdout.strip()
        if tree != head_tree:
            print("other " + spec)
            sys.exit(0)
        verdict = "check"
print(verdict)
PYEOF

# Pass the command unless it is a git push, a `gh pr create` or a create-pr.sh run; a here-string avoids a SIGPIPE false pass.
if ! grep -Eq '(^|[^[:alnum:]_./-])git([[:space:]]+[^;&|[:space:]]+)*[[:space:]]+push([[:space:]]|$|[;&|])|gh[[:space:]]+pr[[:space:]]+create' <<<"$_CMD"; then
  # A command that names create-pr.sh is taken for a run of it, unless every part of it only reads files
  # (cat, sed, grep, ls and the like). Only the reader's plain "no" lets it pass, so a reader that fails gates.
  grep -q 'create-pr\.sh' <<<"$_CMD" || exit 0
  [ "$(python3 -c "$_CMD_READER" opens-pr "$_CMD" 2>/dev/null)" = no ] && exit 0
fi
[ -n "$_CWD" ] && { cd "$_CWD" 2>/dev/null || true; }
# Move into the checkout the push acts on: a leading `cd DIR`, then each `git -C DIR`, with quotes stripped.
_unquote() { printf '%s' "$1" | sed -E "s/^[\"']//; s/[\"']$//"; }
_LEAD_CD="$(printf '%s' "$_CMD" | sed -nE 's/^[[:space:]]*cd[[:space:]]+("[^"]+"|'"'"'[^'"'"']+'"'"'|[^[:space:];&|]+)[[:space:]]*&&.*/\1/p' | head -1)"
[ -n "$_LEAD_CD" ] && { cd "$(_unquote "$_LEAD_CD")" 2>/dev/null || true; }
for _d in $(printf '%s' "$_CMD" | grep -oE -- '-C[[:space:]]+("[^"]+"|[^[:space:]]+)' | sed -E 's/^-C[[:space:]]+//'); do
  cd "$(_unquote "$_d")" 2>/dev/null || true
done

# Changed set: stand down outside a git repo.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# List the files the branch changed since origin/main, committed or not, plus untracked files, as absolute paths.
TOP="$(git rev-parse --show-toplevel)"
cd "$TOP" || exit 0
# Run checks only in the session's own repository.
if ! python3 "$_HOOK_DIR/project_fact.py" --trusted "$TOP" 2>/dev/null; then
  echo "WARN: $TOP is not this session's repository, so the push gate ran none of its checks there." >&2
  exit 0
fi
BASE="$(git merge-base HEAD origin/main 2>/dev/null || true)"
if [ -z "$BASE" ]; then
  echo "WARN: no origin/main to compare against, so only uncommitted files were checked. Run 'git fetch origin main' and push again for a full check." >&2
fi

# Remember a pass. When every rung has passed, one line goes into this worktree's git directory, and a later
# call whose state matches that line skips the slow stack rungs. The quick rungs always run. The line names
# what the slow rungs read: the tree of HEAD, the merge base with origin/main, this script with the fact
# reader beside it, the pinned toolchain file, and a print of the files git ignores (see ignored_print). A
# checkout with anything uncommitted, untracked or hidden from git status has no key, and neither has a call
# whose environment can point git somewhere else. So no variable and no setting can aim the gate at a record
# made for another commit: the most one can do is switch the reuse off. What the line cannot see is listed in
# the gate catalog.
pass_key() {
  local name dirty hidden tree gate toolchain toolsum
  [ -n "$BASE" ] || return 0
  # Any GIT_ variable outside this list may move the repository, the index, the objects or the config git reads.
  for name in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do
    case "$name" in
      GIT_EDITOR|GIT_SEQUENCE_EDITOR|GIT_PAGER|GIT_TERMINAL_PROMPT|GIT_ASKPASS|GIT_SSH|GIT_SSH_COMMAND) ;;
      GIT_CEILING_DIRECTORIES|GIT_OPTIONAL_LOCKS|GIT_AUTHOR_*|GIT_COMMITTER_*|GIT_TRACE*) ;;
      *) return 0 ;;
    esac
  done
  # The rungs check files on disk, so one uncommitted or untracked file means the tree of HEAD is not what they saw.
  dirty="$(git status --porcelain --untracked-files=all --ignore-submodules=none 2>/dev/null)" || return 0
  [ -z "$dirty" ] || return 0
  # A file marked assume-unchanged or skip-worktree can differ on disk while git status calls the tree clean.
  hidden="$(git ls-files -v 2>/dev/null)" || return 0
  grep -q '^[a-zS] ' <<<"$hidden" && return 0
  tree="$(git rev-parse --verify -q 'HEAD^{tree}' 2>/dev/null)" || return 0
  [ -n "$tree" ] || return 0
  # A plugin update changes this script or the fact reader, and so voids every record made before it.
  gate="$(cat "$_HOOK_DIR/$(basename "${BASH_SOURCE[0]}")" "$_HOOK_DIR/project_fact.py" 2>/dev/null | git hash-object --stdin 2>/dev/null)" || return 0
  [ -n "$gate" ] || return 0
  toolsum=none
  toolchain="$(project_fact "$TOP" --path PROJECT_TOOLCHAIN_ENV)"
  if [ -n "$toolchain" ] && [ -f "$toolchain" ]; then
    toolsum="$(git hash-object --no-filters -- "$toolchain" 2>/dev/null)" || return 0
    [ -n "$toolsum" ] || return 0
  fi
  printf 'masthead push gate pass 2 tree=%s base=%s gate=%s toolchain=%s\n' "$tree" "$BASE" "$gate" "$toolsum"
}
# The files git ignores are read by the stack rungs too: installed packages, build output. This prints one
# hash over the path, size and time stamp of every one of them, so a file that is added, changed or removed
# after a pass shows as a different print. An ignored folder that is a git clone of its own (a package
# fetched from git) comes from git as one entry, so its files are walked. One whose .git is a file is a
# linked worktree, another checkout with a gate of its own, and is not walked: a main checkout can hold
# dozens of them, each as large as itself. The rungs write build output themselves, so the print is taken
# after they pass, and it is not part of the key that is compared across the run. Prints nothing when the
# files cannot be listed, and then nothing is remembered or reused.
ignored_print() {
  local print
  # Under pipefail a git that fails fails the pipe, so a list that could not be made is never read as an empty one.
  print="$(git ls-files --others --ignored --exclude-standard -z 2>/dev/null | python3 -I -c 'import hashlib, os, sys
seen = hashlib.sha1()
def note(path):
    try:
        info = os.lstat(path)
        seen.update(os.fsencode(path) + b"\0" + ("%d %d %d" % (info.st_size, info.st_mtime_ns, info.st_mode)).encode() + b"\n")
    except OSError:
        seen.update(os.fsencode(path) + b"\0gone\n")
for raw in sorted(sys.stdin.buffer.read().split(b"\0")):
    if not raw:
        continue
    path = os.fsdecode(raw)
    note(path)
    if path.endswith("/") and os.path.isdir(os.path.join(path, ".git")):
        for folder, folders, files in os.walk(path):
            folders[:] = sorted(name for name in folders if name != ".git")
            for name in sorted(files):
                note(os.path.join(folder, name))
print(seen.hexdigest())' 2>/dev/null)" || return 0
  printf '%s' "$print"
}
# Take the key before the changed files are listed, so a commit that lands after this line shows up at the
# end as a key that no longer matches, and that run is not remembered.
PASS_KEY="$(pass_key)"
PASS_RECORD="$(git rev-parse --git-path masthead-push-gate-pass 2>/dev/null || true)"
CHANGED="$( {
  [ -n "$BASE" ] && git diff --name-only "$BASE" HEAD 2>/dev/null
  git status --porcelain --untracked-files=all 2>/dev/null | awk '{print $NF}'
} | sort -u | sed "s|^|$TOP/|")"

[ -z "$CHANGED" ] && exit 0
# Warn that uncommitted edits are checked on disk but the push carries the committed copy.
_DIRTY="$(git diff --name-only HEAD 2>/dev/null | head -5)"
[ -n "$_DIRTY" ] && echo "WARN: uncommitted edits are checked as they are on disk, but this push carries the committed version of: $(printf '%s' "$_DIRTY" | tr '\n' ' ')" >&2

pick() { printf '%s\n' "$CHANGED" | grep -E "$1" || true; }

ELIXIR="$(pick '\.(ex|exs)$')"
NODE="$(pick '\.(ts|tsx|js|jsx|mjs|cjs)$')"
SWIFT="$(pick '\.swift$|/korium-cli/(Native/|Scripts/build-extractor\.sh$|Package\.(swift|resolved)$)')"
KOTLIN="$(pick '\.(kt|kts)$')"
TF="$(pick '\.tf$')"
# Every changed source or config file, for the stack-independent secret rung.
SECRETSCAN="$(pick '\.(ex|exs|ts|tsx|js|jsx|mjs|cjs|rs|swift|kt|kts|tf|tfvars|py|rb|go|java|sh|json|ya?ml|toml|plist|xcconfig|properties|entitlements|xml|env)$')"

fail=0

# Keep only the paths that still exist, for the rungs that take a file list.
existing() {
  out=""
  for f in $1; do [ -f "$f" ] && out="$out $f"; done
  printf '%s' "$out"
}

block() { echo "BLOCK: $1" >&2; fail=1; }
warn()  { echo "WARN: $1" >&2; }

# Secrets: block a credential compiled into source, with a repo-owned allow-secret waiver on the line or the line above.
gate_secrets() {
  # Build repeat counts by writing them out, because some awks have no {n}.
  rep() { local s='' i; for ((i = 0; i < $2; i++)); do s="$s$1"; done; printf '%s' "$s"; }
  # Match high-confidence issuer shapes only: AWS, Google, GitHub and Slack keys and PEM armor.
  issuer="AKIA$(rep '[0-9A-Z]' 16)|AIza$(rep '[0-9A-Za-z_-]' 35)|gh[pousr]_$(rep '[A-Za-z0-9]' 36)|xox[baprs]-$(rep '[0-9A-Za-z-]' 10)|-----BEGIN [A-Z ]*PRIVATE KEY-----"
  # Match a quoted literal of 16 or more characters assigned to a credential-named field, skipping interpolated lines.
  assign='(api[_-]?key|secret|token|passwd|password)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']'"$(rep "[^\"']" 16)"'[^"'"'"']*["'"'"']'

  # Check that awk matches two built test keys first, and block if it cannot.
  canary="AKIA$(rep A 16)
api_key: \"$(rep a 16)\""
  seen="$(printf '%s\n' "$canary" | awk -v issuer="$issuer" -v assign="$assign" '
    $0 ~ issuer || tolower($0) ~ tolower(assign) { n++ } END { print n + 0 }' 2>&1)"
  if [ "$seen" != 2 ]; then
    block "the secret scan could not run: this machine's awk did not match the two test keys built to match (it answered '$seen'), so no file was checked for secrets."
    return
  fi

  for f in $(existing "$SECRETSCAN"); do
    # Scan with awk so the waiver can sit on the line above the hit.
    hits="$(awk -v issuer="$issuer" -v assign="$assign" -v waiver="allow-secret" '
      {
        line = $0
        hit = 0
        if (line ~ issuer) hit = 1
        if (tolower(line) ~ tolower(assign)) hit = 1
        if (hit && index(line, waiver) == 0 && index(prev, waiver) == 0 \
            && line !~ /[$#]\{/ && line !~ /\$\(/ && line !~ /\\\(/) {
          printf "line %d\n", NR
        }
        prev = line
      }' "$f" 2>/dev/null)"
    if [ -n "$hits" ]; then
      block "possible secret in $f. A secret never ships in source: serve it from the backend, or read it from the platform keystore. A known placeholder may carry an 'allow-secret' marker on the line, or on the line above it."
      printf '%s\n' "$hits" | sed 's/^/  /' >&2
    fi
  done

  # Scan the lines the branch's commits added too, so a secret removed later is still caught.
  [ -n "$BASE" ] || return 0
  hist="$(git log -p --format= "$BASE"..HEAD 2>/dev/null | awk -v issuer="$issuer" -v assign="$assign" -v waiver="allow-secret" '
    /^\+\+\+ / { file = substr($0, 7); next }
    /^\+/ {
      line = substr($0, 2)
      hit = 0
      if (line ~ issuer) hit = 1
      if (tolower(line) ~ tolower(assign)) hit = 1
      if (hit && index(line, waiver) == 0 && index(prev, waiver) == 0 \
          && line !~ /[$#]\{/ && line !~ /\$\(/ && line !~ /\\\(/) {
        printf "%s\n", file
      }
      prev = line
      next
    }
    { prev = "" }')"
  if [ -n "$hist" ]; then
    block "a commit on this branch adds a possible secret. Removing it in a later commit does not help: the history still carries it. Rewrite the commit, or mark a known placeholder with 'allow-secret'."
    printf '%s\n' "$hist" | sort -u | head -20 | sed 's/^/  /' >&2
  fi
}

# Elixir: mix format check, compile with warnings as errors, then credo strict.
gate_elixir() {
  [ -f mix.exs ] || { warn "Elixir files changed but no mix.exs at cwd. Run the gate from the project root."; return; }

  # Use the pinned Elixir from the repo's toolchain file when it names one.
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  toolchain=""
  [ -n "$top" ] && toolchain="$(project_fact "$top" --path PROJECT_TOOLCHAIN_ENV)"
  if [ -n "$toolchain" ] && [ -f "$toolchain" ]; then
    # shellcheck disable=SC1090
    . "$toolchain" >/dev/null 2>&1 || true
  fi

  command -v mix >/dev/null 2>&1 || { block "Elixir files changed but 'mix' is not installed, so the change cannot be verified. Source the toolchain env before declaring done."; return; }

  files="$(existing "$ELIXIR")"
  # shellcheck disable=SC2086 # $files is a list of paths, split on purpose
  if [ -n "$files" ] && ! mix format --check-formatted $files >/dev/null 2>&1; then
    block "'mix format --check-formatted' failed on the changed files. Run 'mix format'."
  fi

  if ! mix compile --warnings-as-errors >/dev/null 2>&1; then
    block "'mix compile --warnings-as-errors' failed:"
    mix compile --warnings-as-errors >&2 2>&1 || true
  fi

  if mix help credo >/dev/null 2>&1; then
    if ! mix credo --strict >/dev/null 2>&1; then
      block "'mix credo --strict' reported issues:"
      mix credo --strict >&2 2>&1 || true
      echo "Accepted exceptions belong in .credo.exs, which the repo owns and reviews, not in disabling this gate." >&2
    fi
  else
    warn "credo is not available, so the lint rung was skipped."
  fi

  # The local-tests rung covers the tests.
}

# Node: prettier, eslint, tsc and vitest, for plain Node and React or Next projects.
gate_node() {
  [ -f package.json ] || { warn "JS or TS files changed but no package.json at cwd. Run the gate from the project root."; return; }
  command -v node >/dev/null 2>&1 || { block "JS or TS files changed but 'node' is not installed, so the change cannot be verified."; return; }

  files="$(existing "$NODE")"

  if npx --no-install prettier --version >/dev/null 2>&1; then
    # shellcheck disable=SC2086 # $files is a list of paths, split on purpose
    if [ -n "$files" ] && ! npx --no-install prettier --check $files >/dev/null 2>&1; then
      block "'prettier --check' failed on the changed files. Run 'npx prettier --write' on them."
    fi
  else
    warn "prettier is not available, so the format rung was skipped."
  fi

  if npx --no-install eslint --version >/dev/null 2>&1; then
    # shellcheck disable=SC2086 # $files is a list of paths, split on purpose
    if [ -n "$files" ] && ! npx --no-install eslint $files >/dev/null 2>&1; then
      block "'eslint' reported problems on the changed files:"
      npx --no-install eslint $files >&2 2>&1 || true
      echo "Accepted exceptions belong in the repo's eslint config, or in an inline '// eslint-disable-* -- <justification>', not in disabling this gate." >&2
    fi
  else
    warn "eslint is not available, so the lint rung was skipped."
  fi

  if [ -f tsconfig.json ]; then
    if npx --no-install tsc --version >/dev/null 2>&1; then
      if ! npx --no-install tsc --noEmit >/dev/null 2>&1; then
        block "'tsc --noEmit' failed:"
        npx --no-install tsc --noEmit >&2 2>&1 || true
      fi
    else
      warn "tsconfig.json is present but typescript is not installed, so the typecheck rung was skipped."
    fi
  fi

  if npx --no-install vitest --version >/dev/null 2>&1; then
    if ! npx --no-install vitest run --changed >/dev/null 2>&1; then
      block "'vitest run --changed' failed:"
      npx --no-install vitest run --changed >&2 2>&1 || true
    fi
  elif [ -f package.json ] && node -e 'process.exit(require("./package.json").scripts?.test?0:1)' 2>/dev/null; then
    # Fall back to npm test when vitest is absent but the project has a test script.
    if ! npm test --silent >/dev/null 2>&1; then
      block "'npm test' failed:"
      npm test --silent >&2 2>&1 || true
    fi
  else
    warn "neither vitest nor an npm test script is available, so the test rung was skipped."
  fi
}

# Swift: swiftformat, swiftlint and swift build, each only when the project configures it.
gate_swift() {
  if [ ! -f Package.swift ] && ! ls -1 ./*.xcodeproj >/dev/null 2>&1 && ! ls -1 ./*.xcworkspace >/dev/null 2>&1; then
    warn "Swift files changed but no Package.swift or Xcode project at cwd. Run the gate from the project root."
    return
  fi

  if [ -f .swiftformat ]; then
    if command -v swiftformat >/dev/null 2>&1; then
      if ! swiftformat --lint . >/dev/null 2>&1; then
        block "'swiftformat --lint' found unformatted Swift. Run 'swiftformat .'."
      fi
    else
      warn ".swiftformat is present but swiftformat is not installed, so the format rung was skipped."
    fi
  fi

  if [ -f .swiftlint.yml ] || [ -f .swiftlint.yaml ]; then
    if command -v swiftlint >/dev/null 2>&1; then
      if ! swiftlint lint --quiet --strict >/dev/null 2>&1; then
        block "'swiftlint --strict' reported violations:"
        swiftlint lint --quiet --strict >&2 2>&1 || true
        echo "Project-accepted exceptions belong in .swiftlint.yml, which the repo owns and reviews, not in disabling this gate." >&2
      fi
    else
      warn "a SwiftLint config is present but swiftlint is not installed, so the lint rung was skipped."
    fi
  fi

  # Run a project's own run-tests.sh when it has one, else swift build and swift test.
  if [ -x run-tests.sh ]; then
    # Run once, keep the output, and show it on failure.
    out="$(mktemp "${TMPDIR:-/tmp}/hard-gate-swift.XXXXXX")"
    if [ -x Scripts/build-extractor.sh ] && ! Scripts/build-extractor.sh >"$out" 2>&1; then
      block "'Scripts/build-extractor.sh' failed in $(pwd):"
      tail -40 "$out" >&2
    elif ! ./run-tests.sh >"$out" 2>&1; then
      block "'./run-tests.sh' failed in $(pwd):"
      { grep -E 'error:|✘|failed' "$out" | head -30; echo "  (last lines of the run)"; tail -15 "$out"; } >&2
    fi
    rm -f "$out"
  elif [ -f Package.swift ]; then
    if ! command -v swift >/dev/null 2>&1; then
      block "Swift files changed but the 'swift' toolchain is not installed, so the change cannot be verified."
    else
      if ! swift build >/dev/null 2>&1; then
        block "'swift build' failed:"
        swift build >&2 2>&1 || true
      elif ! swift test >/dev/null 2>&1; then
        block "'swift test' failed:"
        swift test >&2 2>&1 || true
      fi
    fi
  fi
}

# Kotlin: run the ktlint task and the unit tests through the Gradle wrapper.
gate_kotlin() {
  if [ ! -f gradlew ]; then
    warn "Kotlin files changed but no gradlew at cwd. Run the gate from the project root."
    return
  fi

  # Check that the lint task exists before running it.
  kt_task=""
  kt_tasks="$(./gradlew --offline tasks --all 2>/dev/null || true)"
  for t in lintKotlin ktlintCheck; do
    if grep -qE "(^| )$t( |$)" <<<"$kt_tasks"; then
      kt_task="$t"
      break
    fi
  done
  if [ -z "$kt_task" ]; then
    warn "no ktlint task on this Gradle project, so the lint rung was skipped."
  elif ! ./gradlew --offline "$kt_task" >/dev/null 2>&1; then
    block "'./gradlew $kt_task' reported lint violations:"
    ./gradlew --offline "$kt_task" >&2 2>&1 || true
  fi

  if ! ./gradlew --offline testDebugUnitTest >/dev/null 2>&1; then
    block "'./gradlew testDebugUnitTest' failed:"
    ./gradlew --offline testDebugUnitTest >&2 2>&1 || true
  fi
}

# Terraform: fmt, validate, tflint and a security scan in each directory of a changed .tf file.
gate_tf() {
  RUNTIME=""
  command -v tofu >/dev/null 2>&1 && RUNTIME=tofu
  [ -z "$RUNTIME" ] && command -v terraform >/dev/null 2>&1 && RUNTIME=terraform
  if [ -z "$RUNTIME" ]; then
    block "Terraform files changed but neither 'tofu' nor 'terraform' is installed, so the change cannot be verified."
    return
  fi

  tf_dirs="$(for f in $TF; do d="${f%/*}"; [ "$d" = "$f" ] && d="."; echo "$d"; done | sort -u)"

  for d in $tf_dirs; do
    [ -d "$d" ] || continue
    ( cd "$d" || exit 0

      if ! $RUNTIME fmt -check -recursive >/dev/null 2>&1; then
        echo "BLOCK: '$RUNTIME fmt -check -recursive' found unformatted HCL in $d. Run '$RUNTIME fmt -recursive'." >&2
        exit 1
      fi

      # Initialise without a backend so validate can run on a fresh checkout.
      if [ ! -d .terraform ]; then
        $RUNTIME init -backend=false -input=false >/dev/null 2>&1 || true
      fi
      if [ -d .terraform ]; then
        if ! $RUNTIME validate >/dev/null 2>&1; then
          echo "BLOCK: '$RUNTIME validate' failed in $d:" >&2
          $RUNTIME validate >&2 2>&1 || true
          exit 1
        fi
      else
        echo "WARN: '$RUNTIME init -backend=false' did not initialise $d, so validate was skipped." >&2
      fi

      if command -v tflint >/dev/null 2>&1; then
        if ! tflint >/dev/null 2>&1; then
          echo "BLOCK: 'tflint' reported issues in $d:" >&2
          tflint >&2 2>&1 || true
          exit 1
        fi
      else
        echo "WARN: tflint is not installed, so the lint rung was skipped." >&2
      fi

      if command -v checkov >/dev/null 2>&1; then
        if [ -f .checkov.baseline ]; then
          checkov -d . --baseline .checkov.baseline --compact --quiet >/dev/null 2>&1 \
            || { echo "BLOCK: 'checkov' found NEW findings beyond .checkov.baseline in $d. Fix them, or record accepted risk in the baseline with sign-off." >&2; exit 1; }
        else
          checkov -d . --compact --quiet >/dev/null 2>&1 \
            || { echo "BLOCK: 'checkov' reported findings in $d. Fix them, or create a reviewed baseline with 'checkov -d . --create-baseline'." >&2; exit 1; }
        fi
      elif command -v trivy >/dev/null 2>&1; then
        trivy config --exit-code 1 --quiet . >/dev/null 2>&1 \
          || { echo "BLOCK: 'trivy config' reported findings in $d. Fix them, or record accepted risk in .trivyignore with sign-off." >&2; exit 1; }
      else
        echo "WARN: neither checkov nor trivy is installed, so the security scan was skipped." >&2
      fi
    ) || fail=1
  done
}

# Dispatch: find the project roots that own the changed files.
roots() {
  # Find the nearest directory above each file that holds the first matching marker in the list.
  markers="$1"; list="$2"; out=""
  for f in $list; do
    for marker in $markers; do
      d="$(dirname "$f")"; found=""
      while [ "${d#"$TOP"}" != "$d" ]; do
        # Only a tracked marker makes a root, so an unpacked archive or a scratch folder never gets its build files run.
        if [ -e "$d/$marker" ] && git -C "$TOP" ls-files --error-unmatch "$d/$marker" >/dev/null 2>&1; then found="$d"; break; fi
        [ "$d" = "$TOP" ] && break
        d="$(dirname "$d")"
      done
      if [ -n "$found" ]; then out="$out
$found"; break; fi
    done
  done
  printf '%s\n' "$out" | grep -v '^$' | sort -u
}
each_root() {
  rung="$1"; marker="$2"; var="$3"; eval "list=\"\$$var\""
  # Run each rung in a subshell so its cd stays there and its failure code reaches the parent.
  found_roots="$(roots "$marker" "$list")"
  [ -z "$found_roots" ] && warn "${rung#gate_} files changed but no $marker above them, so that rung was skipped."
  for r in $found_roots; do
    # Cut the stack's file list down to the files under this root.
    mine="$(printf '%s\n' $list | grep -F "$r/" || true)"
    ( cd "$r" || exit 1; fail=0; eval "$var=\"\$mine\""; "$rung"; exit "$fail" ) || fail=1
  done
}

# Local tests: require the push-check script's receipt for HEAD, and refuse a push of any other commit.
gate_local_tests() {
  check_script="$(project_fact "$TOP" --path PROJECT_PUSH_CHECK)"
  [ -n "$check_script" ] && [ -f "$check_script" ] || return 0
  check_rel="${check_script#"$TOP"/}"
  sends="$(python3 -c "$_CMD_READER" sends "$_CMD" "$(git rev-parse --verify -q 'HEAD^{tree}' 2>/dev/null)" 2>/dev/null || echo check)"
  case "$sends" in
    skip) return 0 ;;
    other*)
      block "this push sends '${sends#other }', not HEAD, and the local test receipt is only for HEAD. Check that branch out, run 'bash $check_rel' there, and push it from there."
      return 0
      ;;
  esac
  if ! out="$(bash "$check_script" --check 2>&1)"; then
    block "the local tests have not passed on this commit. Run 'bash $check_rel' (it says what it needs), then push again."
    printf '%s\n' "$out" | sed 's/^/  /' >&2
  fi
}

# The quick rungs run first: what the push sends and the test receipt, then the secret scan. A refusal from
# either one stops the gate here, so it costs seconds and not the minutes the stack rungs can take.
SLOW="$ELIXIR$NODE$SWIFT$KOTLIN$TF"
gate_local_tests
[ -n "$SECRETSCAN" ] && gate_secrets
if [ "$fail" -ne 0 ]; then
  echo "" >&2
  if [ -n "$SLOW" ]; then
    echo "Nothing was pushed. Fix the failures above and push again. The slower checks of the changed code (format, compile, lint and tests) have not run yet: they run once these pass." >&2
  else
    echo "Nothing was pushed. Fix the failures above and push again; the gate re-runs on the branch." >&2
  fi
  exit 2
fi

[ -n "$SLOW" ] || exit 0

# The slow rungs: each changed stack's own format, compile, lint and tests. They are skipped when this exact
# state has passed them before.
if [ -n "$PASS_KEY" ] && [ -n "$PASS_RECORD" ] && [ -f "$PASS_RECORD" ]; then
  _RECORDED="$(cat "$PASS_RECORD" 2>/dev/null)"
  # The print of the ignored files costs a walk of them, so it is taken only when the rest of the line matches.
  case "$_RECORDED" in
    "$PASS_KEY ignored="?*)
      _PRINT="$(ignored_print)"
      if [ -n "$_PRINT" ] && [ "$_RECORDED" = "$PASS_KEY ignored=$_PRINT" ]; then
        echo "NOTE: the checks of the changed code (format, compile, lint and tests) passed earlier on exactly these files and this base, with nothing uncommitted and no ignored file changed since, so they were not run again." >&2
        exit 0
      fi
      ;;
  esac
fi
[ -n "$ELIXIR" ] && each_root gate_elixir "mix.lock mix.exs" ELIXIR
[ -n "$NODE" ]   && each_root gate_node package.json NODE
# No Rust rung; CI runs it.
[ -n "$SWIFT" ]  && each_root gate_swift Package.swift SWIFT
[ -n "$KOTLIN" ] && each_root gate_kotlin gradlew KOTLIN
[ -n "$TF" ]     && gate_tf

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "Nothing was pushed. Fix the failures above and push again; the gate re-runs on the branch." >&2
  exit 2
fi

# Remember the pass, but only when the state is still the one the rungs started on: a commit, an edit or a
# new file that arrived while they ran leaves no record.
if [ -n "$PASS_KEY" ] && [ -n "$PASS_RECORD" ] && [ "$(pass_key)" = "$PASS_KEY" ]; then
  _PRINT="$(ignored_print)"
  if [ -n "$_PRINT" ] && printf '%s ignored=%s\n' "$PASS_KEY" "$_PRINT" > "$PASS_RECORD.$$" 2>/dev/null; then
    mv -f "$PASS_RECORD.$$" "$PASS_RECORD" 2>/dev/null || rm -f "$PASS_RECORD.$$"
  fi
fi

exit 0
