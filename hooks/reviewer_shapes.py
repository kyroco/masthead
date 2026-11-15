#!/usr/bin/env python3
"""The exact command shapes a verifier or security reviewer may run in its shell (MAST-43).

bash-scope-reviewer.sh sends the command on stdin and the checkout as --cwd. This
prints nothing and exits 0 when every command in it is one of the shapes below,
and prints the reason and exits 2 when one is not.

Each round of MAST-34 refused one more flag or wrapper, and the next round found
one more spelling, so this is an allowlist: a program, flag or shell form that
is not named here is refused, however it is spelled. It holds the command line
the agent types, not code it runs: a test, a test runner, semgrep, or a probe
script the agent wrote itself in its scratch folder can still do anything
(Robert, November 15, kept probe scripts open).

The shapes, each command separated by |, &&, || or ; and each judged alone:
  git, read only: status, diff, log, show, blame, rev-parse, ls-files,
    merge-base, shortlog, describe and grep, with the flags below and plain
    revisions and paths; nothing between git and the subcommand but --no-pager.
  the repository's tests, each runner with its offline switch where it has
    one, and every path or package it is given in the checkout: bash, sh or
    python3 with a script path inside the checkout; ./<script>; python3 -m
    pytest (not -m unittest, which imports any name it is given; a unittest
    suite runs through pytest); pytest; mix test (MIX_ENV=test may come first);
    cargo test --offline; GOPROXY=off go test ./<path>; npm, pnpm or yarn
    test; npx --no-install vitest, jest or mocha; make test or make check;
    bundle exec rspec; rspec; swift test --skip-update
    --disable-automatic-resolution; xcodebuild test -skipPackageUpdates
    -disableAutomaticPackageResolution; dotnet test --no-restore; mvn -o test
    or verify; gradle test or check --offline.
  semgrep (scan) with --metrics=off and --disable-version-check, and
    opengrep with --disable-version-check, each with --config naming a rules
    file in the checkout.
  reading: cat, head, tail, wc, ls, grep, egrep, fgrep, rg, jq, find (searching
    only), diff, cmp, sort, uniq, cut, tr, echo, printf, pwd, basename,
    dirname, realpath.
  rm of the agent's own files under <state>/review/scratch/.
  2>&1, >/dev/null and 2>/dev/null; no other redirect.
Refused everywhere: a wrapper (timeout, env, nice, xargs, exec, sudo...), a
shell's -c, $, backticks, backslashes, globs, braces, subshells, & on its own,
a word starting with = (zsh's path of a program), a new line, a URL and
/dev/tcp.
"""

import os
import re
import sys

# What a refused agent is told, and what the README says, word for word (a test holds them together).
SUMMARY = ("read-only git, the repository's own tests with their offline switches, semgrep and "
           "opengrep with their calls home turned off, a few reading tools such as cat, grep and "
           "jq, and rm of the agent's own scratch files, one command at a time or several joined "
           "by |, &&, || or ;")

# --- git -------------------------------------------------------------------
GIT_SUBS = {"status", "diff", "log", "show", "blame", "rev-parse", "ls-files",
            "merge-base", "shortlog", "describe", "grep"}
# Short flags per subcommand: (letters that take no value, letters whose value is
# the rest of the word). A letter git reads as taking a value is never listed
# as taking none, or the rest of the word would go unjudged by git and by this.
GIT_SHORT = {
    "status": ("sbz", "u"),
    "diff": ("pswbRazWu", "USG"),
    "log": ("pswbRazWuimEFP", "nUSGL"),
    "show": ("pswbRazWum", "USG"),
    "blame": ("seltwfnpc", "L"),
    "rev-parse": ("q", ""),
    "ls-files": ("cdmotsiz", ""),
    "merge-base": ("a", ""),
    "shortlog": ("nsec", ""),
    "describe": ("", ""),
    "grep": ("inlvwcEFPhHoqsIaLzpW", "efABCm"),
}
# Long flags, each may carry =value. None is a prefix of a long option that runs
# a program or writes (output, ext-diff, textconv, open-files-in-pager, exec,
# upload-pack, no-index), which git would take as an abbreviation.
GIT_LONG = {
    "oneline", "stat", "shortstat", "numstat", "name-only", "name-status", "no-color",
    "color", "patch", "no-patch", "reverse", "first-parent", "merges", "no-merges",
    "cached", "staged", "follow", "decorate", "no-decorate", "graph", "all", "word-diff",
    "ignore-all-space", "ignore-space-change", "porcelain", "short", "branch",
    "abbrev-ref", "show-toplevel", "verify", "is-ancestor", "abbrev-commit", "summary",
    "check", "exit-code", "quiet", "others", "exclude-standard", "deleted", "modified",
    "symbolic-full-name", "relative", "raw", "root", "topo-order", "date-order",
    "boundary", "left-right", "cherry-pick", "count", "no-renames", "full-index",
    "function-context", "minimal", "histogram", "patience", "full-diff", "source",
    "parents", "children", "no-walk", "compact-summary", "dirstat", "line-number",
    "ignore-case", "files-with-matches", "files-without-match", "word-regexp",
    "extended-regexp", "fixed-strings", "perl-regexp", "invert-match", "numbered",
    "email", "tags", "always", "long", "git-dir", "show-prefix", "is-inside-work-tree",
    "format", "pretty", "max-count", "skip", "since", "after", "until", "before",
    "author", "committer", "grep", "diff-filter", "unified", "date", "abbrev",
    "find-renames", "untracked-files", "ignored", "max-depth", "show-current",
    "fork-point", "octopus", "error-unmatch", "full-name", "regexp-ignore-case",
    "show-function", "heading", "break", "context", "after-context", "before-context",
    "null",
}

# --- reading programs: (short letters with no value, short letters with a value, long names)
READERS = {
    "cat": ("nbsvetAEuT", "", set()),
    "head": ("qv", "nc", {"lines", "bytes", "quiet", "verbose"}),
    "tail": ("qvr", "nc", {"lines", "bytes", "quiet", "verbose"}),
    "wc": ("lwcmL", "", {"lines", "words", "bytes", "chars"}),
    "ls": ("1aAbcCdfFghHiklLmnopqrRsStuUx", "", {"all", "almost-all", "color"}),
    "grep": ("rRnilvwcEFGPHhoqsxLZzaIUb", "efABCmd",
             {"include", "exclude", "exclude-dir", "color", "colour", "line-number",
              "recursive", "ignore-case", "files-with-matches", "files-without-match",
              "count", "fixed-strings", "extended-regexp", "perl-regexp", "word-regexp",
              "line-regexp", "invert-match", "no-filename", "with-filename",
              "only-matching", "quiet", "silent", "max-count", "context", "after-context",
              "before-context", "null", "text", "binary-files", "regexp"}),
    "rg": ("nilvwcFHoqsSLNUPx0", "egtTABCmMj",
           {"line-number", "ignore-case", "fixed-strings", "files", "files-with-matches",
            "files-without-match", "count", "count-matches", "glob", "iglob", "type",
            "type-not", "no-heading", "heading", "with-filename", "no-filename",
            "only-matching", "max-count", "context", "after-context", "before-context",
            "smart-case", "case-sensitive", "word-regexp", "line-regexp", "invert-match",
            "multiline", "json", "color", "vimgrep", "sort", "regexp", "no-line-number",
            "max-depth", "max-columns", "trim", "column", "stats", "passthru",
            "follow", "type-list"}),
    "jq": ("rcsSnjeaCMR", "f",
           {"raw-output", "compact-output", "slurp", "null-input", "exit-status", "arg",
            "argjson", "slurpfile", "rawfile", "tab", "indent", "sort-keys", "raw-input",
            "join-output", "ascii-output", "color-output", "monochrome-output",
            "from-file", "args", "jsonargs"}),
    "diff": ("uqrNawbBiyEtTsc", "UCx",
             {"unified", "brief", "recursive", "ignore-all-space", "ignore-space-change",
              "ignore-case", "side-by-side", "text", "new-file", "context", "color",
              "report-identical-files", "exclude", "strip-trailing-cr"}),
    "cmp": ("lsb", "in", {"verbose", "silent", "quiet", "print-bytes"}),
    "sort": ("nrufbdghiMVsz", "kt",
             {"numeric-sort", "reverse", "unique", "ignore-case", "key",
              "field-separator", "human-numeric-sort", "version-sort", "stable"}),
    "uniq": ("cdiuD", "fs", {"count", "repeated", "unique", "ignore-case"}),
    "cut": ("sn", "bcdf", {"bytes", "characters", "delimiter", "fields", "only-delimited"}),
    "tr": ("cdsC", "", set()),
    "echo": ("neE", "", set()),
    "printf": ("", "", set()),
    "pwd": ("LP", "", set()),
    "basename": ("a", "s", set()),
    "dirname": ("", "", set()),
    "realpath": ("eqsmL", "", set()),
}
# find: (predicates that take no value, predicates whose value is the next word).
# -exec, -execdir, -ok, -okdir, -delete and the -fprint family are not here.
FIND_NOVALUE = {"-print", "-print0", "-empty", "-not", "-o", "-a", "-and", "-or",
                "-prune", "-depth", "-xdev", "-readable", "-true", "-false", "!"}
FIND_VALUE = {"-name", "-iname", "-path", "-ipath", "-wholename", "-type", "-maxdepth",
              "-mindepth", "-newer", "-size", "-mtime", "-mmin", "-regex", "-iregex",
              "-perm", "-links"}

# --- test runners ---------------------------------------------------------------
PYTEST = ("qvxsl", "kmr", {"tb", "lf", "last-failed", "ff", "failed-first", "maxfail",
                          "no-header", "collect-only", "co", "quiet", "verbose", "exitfirst",
                          "durations", "showlocals", "deselect", "strict-markers",
                          "capture", "no-summary", "color"})
MIX_TEST = ("", "", {"only", "exclude", "include", "seed", "max-failures", "trace", "failed",
                     "stale", "warnings-as-errors", "color", "no-color", "slowest",
                     "max-cases", "timeout"})
CARGO_TEST = ("q", "p", {"offline", "lib", "bins", "tests", "doc", "all-targets", "workspace",
                         "no-fail-fast", "release", "quiet", "verbose", "all-features",
                         "no-default-features", "locked", "frozen", "test", "package",
                         "features", "exclude", "nocapture", "exact", "test-threads",
                         "ignored", "include-ignored", "show-output"})
GO_TEST = ("", "", {"v", "run", "count", "race", "short", "timeout", "cover", "failfast",
                    "skip", "bench", "benchtime", "cpu", "parallel", "list", "json"})
# No -c: semgrep reads a c anywhere in a bundle such as -qc as --config, so the rules file is named only by --config.
SEMGREP_VALUE = {"--config", "--exclude", "--include", "--severity", "--max-target-bytes", "--timeout", "--jobs"}
SEMGREP = ("q", "", {"metrics", "disable-version-check", "config", "json", "quiet", "error",
                      "no-git-ignore", "sarif", "exclude", "include", "severity", "verbose",
                      "text", "max-target-bytes", "timeout", "jobs"})

GO_VALUE = {"run", "count", "timeout", "skip", "bench", "benchtime", "cpu", "parallel", "list"}
SWIFT_TEST = ("qv", "c", {"skip-update", "disable-automatic-resolution", "force-resolved-versions",
                          "only-use-versions-from-resolved-file", "filter", "skip", "parallel",
                          "num-workers", "configuration", "quiet", "verbose"})
SWIFT_VALUE = {"--filter", "--skip", "--num-workers", "--configuration", "-c"}
CARGO_VALUE = {"-p", "--package", "--test", "--features", "--exclude", "--test-threads"}
SWIFT_OFFLINE = ("--disable-automatic-resolution", "--force-resolved-versions",
                 "--only-use-versions-from-resolved-file")
# xcodebuild's flags are single-dash words: those that take the next word as their value, and those that take none.
XCODE_VALUE = {"-scheme", "-destination", "-project", "-workspace", "-configuration", "-testPlan", "-sdk"}
XCODE_NOVALUE = {"-quiet", "-skipPackageUpdates", "-disableAutomaticPackageResolution",
                 "-onlyUsePackageVersionsFromResolvedFile"}
DOTNET_VALUE = {"--filter", "--configuration", "-c", "--verbosity", "-v", "--framework", "-f"}
DOTNET_NOVALUE = {"--no-restore", "--no-build", "--nologo"}
MVN_NOVALUE = {"-o", "--offline", "-q", "--quiet", "-B", "--batch-mode"}
MVN_VALUE = {"-pl", "--projects"}
MVN_PROPERTIES = ("-Dtest=", "-DfailIfNoTests=", "-Dsurefire.failIfNoSpecifiedTests=")
GRADLE_NOVALUE = {"--offline", "-q", "--quiet", "--info", "--continue"}
GRADLE_VALUE = {"--tests"}
NPX_RUNNERS = {"vitest", "jest", "mocha"}

ENV_OK = {"MIX_ENV=test", "GOPROXY=off"}


class Refused(Exception):
    pass


def refuse(reason):
    raise Refused(reason)


# --- reading the command the way the shell would ------------------------------
def tokenize(cmd):
    """Split the command into words and separators, refusing every form the shell
    would rewrite or run after this check reads it."""
    if "\n" in cmd or "\r" in cmd:
        refuse("a command of more than one line; send one line, and write files with the Write tool")
    tokens, word, in_word, i, n = [], "", False, 0, len(cmd)

    def push():
        nonlocal word, in_word
        if in_word:
            tokens.append(("word", word))
        word, in_word = "", False

    while i < n:
        c = cmd[i]
        if c in " \t":
            push()
            i += 1
        elif c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                refuse("an unterminated quote")
            word += cmd[i + 1:j]
            in_word = True
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and cmd[j] != '"':
                if cmd[j] in "$`\\!":
                    refuse(f"'{cmd[j]}' inside double quotes is expanded by the shell; use single quotes")
                j += 1
            if j >= n:
                refuse("an unterminated quote")
            word += cmd[i + 1:j]
            in_word = True
            i = j + 1
        elif c in "|;&":
            push()
            if cmd.startswith("&&", i) or cmd.startswith("||", i):
                tokens.append(("sep", cmd[i:i + 2]))
                i += 2
            elif c == "&":
                refuse("& runs a command out of sight; run it in the foreground")
            else:
                tokens.append(("sep", c))
                i += 1
        elif c == ">":
            # Only 2>&1, >&2, >/dev/null and 2>/dev/null.
            if in_word and word not in ("1", "2"):
                refuse(f"a redirect into a file ('{word}>'); this shell writes no file")
            rest = cmd[i + 1:]
            m = re.match(r"&[12](?=[\s|;&]|$)|[ \t]*/dev/null(?=[\s|;&]|$)", rest)
            if not m:
                refuse("a redirect into a file; this shell writes no file (only 2>&1 and >/dev/null)")
            word, in_word = "", False
            i += 1 + m.end()
        elif c in "$`\\(){}<*?[]":
            refuse(f"'{c}' is rewritten by the shell after this check reads the command "
                   "(a variable, substitution, backslash, subshell, brace, input redirect or glob); "
                   "write the literal words, quoting a pattern")
        elif (c in "#!" and not in_word) or (c in "~=" and word == ""):
            # zsh, the Bash tool's shell on macOS, turns =name into the full path of a program on PATH and
            # ~ into the home folder, even after an empty quote (''=name), so it is the first character
            # of the word's text that counts, not the first character typed.
            refuse(f"a word starting with '{c}' is rewritten by the shell; quote it")
        else:
            word += c
            in_word = True
            i += 1
    push()
    commands, current = [], []
    for kind, value in tokens:
        if kind == "sep":
            if not current:
                refuse(f"'{value}' with no command before it")
            commands.append(current)
            current = []
        else:
            current.append(value)
    if not current:
        if commands:
            refuse("a separator with no command after it")
        refuse("an empty command")
    commands.append(current)
    return commands


# --- flags ------------------------------------------------------------------------
def judge_flags(prog, words, spec, numbers=False):
    """Refuse any word starting with - that is not a flag in spec. A lone -- is
    passed but does not end the judging, since git takes it as a value after a
    flag that wants one."""
    short_novalue, short_value, long_names = spec
    for w in words:
        if w == "--" or not w.startswith("-") or w == "-":
            continue
        if w.startswith("--"):
            name = w[2:].split("=", 1)[0]
            if name not in long_names:
                refuse(f"'{prog} {w}' is not one of the flags this shell allows for {prog}")
            continue
        body = w[1:]
        if numbers and body.isdigit():
            continue
        for k, ch in enumerate(body):
            if ch in short_value:
                break
            if ch not in short_novalue:
                refuse(f"'{prog} {w}': -{ch} is not one of the flags this shell allows for {prog}")


def inside(path, cwd):
    """The path normalised against the checkout, or None when it leaves it."""
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))
    root = os.path.normpath(cwd)
    if full == root or full.startswith(root + os.sep):
        return full
    return None


def script_path(prog, path, cwd):
    if path.startswith("-"):
        refuse(f"'{prog} {path}': {prog} runs here only as '{prog} <script in the checkout>', with no flag of its own")
    if inside(path, cwd) is None:
        refuse(f"'{path}' is outside the checkout under review")


def own_path(prog, word, cwd):
    """A path a runner is given stays in the checkout, so it runs the repository's tests, not the system's."""
    if inside(word.split("::", 1)[0], cwd) is None:
        refuse(f"'{prog} {word}' names a path outside the checkout under review")


def take_value(prog, words, k):
    """The word after the flag at k, which the program reads as that flag's value. A value that looks like
    a flag is refused: the program would read a switch written there as the value, not as the switch."""
    flag = words[k]
    if k + 1 >= len(words):
        refuse(f"'{prog} {flag}' with no value")
    value = words[k + 1]
    if value.startswith("-"):
        refuse(f"'{prog} {flag} {value}': {flag} takes the next word as its value, so a flag cannot go there")
    return value


def flags_as_read(prog, words, value_flags):
    """The flags the program reads, as it reads them: up to a lone --, after which every word is passed on
    to something else, and with the word after a value flag read as its value. A switch the shell requires
    counts only when it is in this list."""
    flags, k = [], 0
    while k < len(words) and words[k] != "--":
        t = words[k]
        if t.startswith("-"):
            flags.append(t)
            if t in value_flags:
                take_value(prog, words, k)
                k += 1
        k += 1
    return flags


def judge_pytest(words, cwd):
    """pytest: the flags it allows, and paths in the checkout. -k, -m and -r take the next word as a value."""
    k = 0
    while k < len(words):
        t = words[k]
        if t in ("-k", "-m", "-r"):
            take_value("pytest", words, k)
            k += 2
            continue
        if t.startswith("-") and t != "--":
            judge_flags("pytest", [t], PYTEST)
        elif t != "--":
            own_path("pytest", t, cwd)
        k += 1


def judge_single_words(prog, words, novalue, value, cwd, paths):
    """Runners whose flags are whole words (no bundles): each flag is listed, a value flag takes the next word,
    and what is left is returned. With paths, what is left must be paths in the checkout."""
    rest, k = [], 0
    while k < len(words):
        t = words[k]
        if t in value:
            take_value(prog, words, k)
            k += 2
            continue
        if t.startswith("-"):
            if t not in novalue:
                refuse(f"'{prog} {t}' is not one of the flags this shell allows for {prog}")
        else:
            if paths:
                own_path(prog, t, cwd)
            rest.append(t)
        k += 1
    return rest


def judge_xcodebuild(w, cwd):
    """xcodebuild test, with its package fetching off."""
    actions, flags, k = [], [], 1
    while k < len(w):
        t = w[k]
        if t in XCODE_VALUE:
            value = take_value("xcodebuild", w, k)
            if t in ("-project", "-workspace"):
                own_path("xcodebuild", value, cwd)
            k += 2
            continue
        if t.startswith("-only-testing:") or t.startswith("-skip-testing:") or t in XCODE_NOVALUE:
            flags.append(t)
        elif t.startswith("-"):
            refuse(f"'xcodebuild {t}' is not one of the flags this shell allows for xcodebuild")
        else:
            actions.append(t)
        k += 1
    if "-skipPackageUpdates" not in flags or not ("-disableAutomaticPackageResolution" in flags
                                                  or "-onlyUsePackageVersionsFromResolvedFile" in flags):
        refuse("xcodebuild fetches packages over the network unless given -skipPackageUpdates and "
               "-disableAutomaticPackageResolution")
    if actions != ["test"]:
        refuse("xcodebuild runs here only the test action, with no build setting")


# --- each command -------------------------------------------------------------------
def judge_git(w, cwd):
    i = 1
    if i < len(w) and w[i] == "--no-pager":
        i += 1
    if i >= len(w):
        refuse("git with no subcommand")
    sub = w[i]
    if sub not in GIT_SUBS:
        if sub.startswith("-"):
            refuse(f"'git {sub}': nothing but --no-pager may come between git and its subcommand")
        refuse(f"'git {sub}' is not allowed; only git {', '.join(sorted(GIT_SUBS))}")
    short_novalue, short_value = GIT_SHORT[sub]
    judge_flags(f"git {sub}", w[i + 1:], (short_novalue, short_value, GIT_LONG),
                numbers=sub in ("log", "show", "shortlog", "grep"))


def judge_find(w):
    k = 1
    while k < len(w) and not w[k].startswith("-") and w[k] != "!":
        k += 1
    while k < len(w):
        t = w[k]
        if t in FIND_NOVALUE:
            k += 1
        elif t in FIND_VALUE:
            if k + 1 >= len(w):
                refuse(f"find {t} with no value")
            k += 2
        else:
            refuse(f"'find {t}' is not allowed; find only searches here (no -exec, -execdir, -ok, -delete or -fprint)")


def judge_semgrep(prog, w, cwd):
    judge_flags(prog, w[1:], SEMGREP)
    flags = flags_as_read(prog, w[1:], SEMGREP_VALUE)
    if prog == "semgrep" and "--metrics=off" not in flags:
        refuse("semgrep sends usage metrics to its server unless given --metrics=off")
    if any(t.startswith("--metrics") and t != "--metrics=off" for t in w):
        refuse(f"{prog} takes --metrics only as --metrics=off")
    if "--disable-version-check" not in flags:
        refuse(f"{prog} asks its server for the newest version unless given --disable-version-check")
    configs = []
    for k, t in enumerate(w):
        if t == "--config" and t in flags:
            configs.append(take_value(prog, w, k))
        elif t.startswith("--config=") and t in flags:
            configs.append(t.split("=", 1)[1])
    if not configs:
        refuse(f"{prog} with no --config; name a rules file in the checkout")
    for value in configs:
        full = inside(value, cwd) if value else None
        if not full or not os.path.isfile(full) or not value.endswith((".yml", ".yaml")):
            refuse(f"{prog} --config '{value}' is not a rules file in the checkout; a registry name or URL reaches the server")


def judge_scratch_rm(w, cwd, state):
    flags = [t for t in w[1:] if t.startswith("-")]
    for t in flags:
        if t not in ("-f", "-r", "-rf", "-fr"):
            refuse(f"'rm {t}' is not allowed; only rm, rm -f and rm -r of your own scratch files")
    paths = [t for t in w[1:] if not t.startswith("-")]
    if not paths:
        refuse("rm with nothing to remove")
    # The shell follows a symlink where the text of a path does not, so the check reads the disk: no ..,
    # no symlink on the way to the scratch folder or at the path, and the path resolves inside it.
    root = os.path.realpath(cwd)
    scratch = os.path.join(root, state, "review", "scratch")
    if os.path.realpath(scratch) != scratch:
        refuse(f"{state}/review/scratch/ is or sits under a symlink, so nothing in it may be removed")
    for p in paths:
        where = f"'rm {p}': only your own files under {state}/review/scratch/ may be removed"
        if ".." in p.replace("\\", "/").split("/"):
            refuse(where + ", named without ..")
        full = os.path.normpath(p if os.path.isabs(p) else os.path.join(cwd, p))
        if os.path.islink(full) or not os.path.realpath(full).startswith(scratch + os.sep):
            refuse(where + ", never through a symlink")


def judge_command(w, cwd, state):
    for t in w:
        low = t.lower()
        if "://" in low:
            refuse(f"'{t}' is a URL; this shell does not reach the network")
        if "/dev/tcp" in low or "/dev/udp" in low:
            refuse(f"'{t}' opens a network socket")
    k = 0
    envs = []
    while k < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[k]):
        if w[k] not in ENV_OK:
            refuse(f"setting '{w[k]}' is not allowed; only {' and '.join(sorted(ENV_OK))}, each before its own runner")
        envs.append(w[k])
        k += 1
    w = w[k:]
    if not w:
        refuse("a setting with no command after it")
    prog = w[0]
    if envs:
        need = {"MIX_ENV=test": "mix", "GOPROXY=off": "go"}
        for e in envs:
            if need[e] != prog:
                refuse(f"'{e}' goes only before {need[e]}")
    sub = w[1] if len(w) > 1 else ""

    if prog.startswith("./") and len(prog) > 2:
        script_path(prog, prog, cwd)
        return
    if "/" in prog:
        refuse(f"'{prog}' runs a program by path; run the tools this shell names, or ./<script in the checkout>")
    if prog == "git":
        return judge_git(w, cwd)
    if prog in ("bash", "sh"):
        if len(w) < 2:
            refuse(f"{prog} with no script; this shell runs no interactive shell")
        return script_path(prog, w[1], cwd)
    if prog in ("python3", "python"):
        if sub == "-m":
            mod = w[2] if len(w) > 2 else ""
            if mod == "pytest":
                return judge_pytest(w[3:], cwd)
            # Not -m unittest: it turns every name, path and start folder into an import, and each check of
            # those read the name differently from Python (MAST-43 re-verify round 2; Robert, November 15).
            # A unittest suite still runs through pytest, or as python3 <test file>.
            refuse(f"'python3 -m {mod}' is not allowed; only -m pytest. A unittest suite runs through "
                   "python3 -m pytest, or as python3 <test file in the checkout>")
        if not sub:
            refuse("python3 with no script; this shell runs no interactive interpreter")
        return script_path(prog, sub, cwd)
    if prog == "pytest":
        return judge_pytest(w[1:], cwd)
    if prog == "mix":
        if sub != "test":
            refuse(f"'mix {sub}' is not allowed; only mix test (no compile, deps or database task)")
        judge_flags("mix test", w[2:], MIX_TEST)
        for t in w[2:]:
            if not t.startswith("-"):
                own_path("mix test", re.sub(r":\d+$", "", t), cwd)
        return
    if prog == "cargo":
        if sub != "test":
            refuse(f"'cargo {sub}' is not allowed; only cargo test --offline")
        # After a lone --, cargo passes every word to the test program, so --offline counts only before it.
        if "--offline" not in flags_as_read("cargo test", w[2:], CARGO_VALUE):
            refuse("cargo test fetches crates over the network unless given --offline, before any --")
        return judge_flags("cargo test", w[2:], CARGO_TEST)
    if prog == "go":
        if sub != "test":
            refuse(f"'go {sub}' is not allowed; only GOPROXY=off go test")
        if "GOPROXY=off" not in envs:
            refuse("go test fetches modules over the network unless GOPROXY=off comes first")
        # go's own flags are single-dash words, such as -run and -count; a package is the repository's own (./...).
        k = 2
        while k < len(w):
            t = w[k]
            if t.startswith("-") and t != "--":
                name = t.lstrip("-").split("=", 1)[0]
                if name not in GO_TEST[2]:
                    refuse(f"'go test {t}' is not one of the flags this shell allows for go test")
                if name in GO_VALUE and "=" not in t:
                    take_value("go test", w, k)
                    k += 1
            elif t != "--":
                if not (t == "." or t.startswith("./")):
                    refuse(f"'go test {t}': a package here is the repository's own, written ./<path>")
                own_path("go test", t, cwd)
            k += 1
        return
    if prog == "swift":
        if sub != "test":
            refuse(f"'swift {sub}' is not allowed; only swift test --skip-update --disable-automatic-resolution")
        flags = flags_as_read("swift test", w[2:], SWIFT_VALUE)
        if "--skip-update" not in flags or not any(t in SWIFT_OFFLINE for t in flags):
            refuse("swift test fetches packages over the network unless given --skip-update and --disable-automatic-resolution")
        return judge_flags("swift test", w[2:], SWIFT_TEST)
    if prog == "xcodebuild":
        return judge_xcodebuild(w, cwd)
    if prog == "dotnet":
        if sub != "test":
            refuse(f"'dotnet {sub}' is not allowed; only dotnet test --no-restore")
        if "--no-restore" not in w:
            refuse("dotnet test restores packages over the network unless given --no-restore")
        return judge_single_words("dotnet test", w[2:], DOTNET_NOVALUE, DOTNET_VALUE, cwd, paths=True)
    if prog == "mvn":
        if "-o" not in w and "--offline" not in w:
            refuse("mvn fetches plugins and packages over the network unless given -o (--offline)")
        rest = [t for t in w[1:] if not t.startswith(MVN_PROPERTIES)]
        goals = judge_single_words("mvn", rest, MVN_NOVALUE, MVN_VALUE, cwd, paths=False)
        if not goals or any(g not in ("test", "verify") for g in goals):
            refuse("mvn runs here only the test or verify goal")
        return
    if prog == "gradle":
        if "--offline" not in w:
            refuse("gradle fetches plugins and packages over the network unless given --offline")
        tasks = judge_single_words("gradle", w[1:], GRADLE_NOVALUE, GRADLE_VALUE, cwd, paths=False)
        if not tasks or any(t not in ("test", "check") for t in tasks):
            refuse("gradle runs here only the test or check task")
        return
    if prog == "npx":
        if sub not in ("--no-install", "--no"):
            refuse("npx installs a missing package from the network unless given --no-install first")
        runner = w[2] if len(w) > 2 else ""
        if runner not in NPX_RUNNERS:
            refuse(f"'npx {sub} {runner}': npx runs here only {', '.join(sorted(NPX_RUNNERS))}")
        for t in w[3:]:
            if t.startswith("-"):
                refuse(f"'npx {runner} {t}': {runner} takes no flag here")
            own_path(f"npx {runner}", t, cwd)
        return
    if prog in ("npm", "pnpm", "yarn"):
        if sub in ("test", "t"):
            rest = w[2:]
        elif sub in ("run", "run-script") and len(w) > 2 and (w[2] == "test" or w[2].startswith("test:")):
            rest = w[3:]
        else:
            refuse(f"'{prog} {sub}' is not allowed; only {prog} test, or {prog} run test")
        for t in rest:
            if t.startswith("-") and t != "--":
                refuse(f"'{prog} test {t}': {prog} takes no flag here")
        return
    if prog == "make":
        if sub not in ("test", "check") or len(w) > 2:
            refuse("make runs only as 'make test' or 'make check', with nothing after")
        return
    if prog == "bundle":
        if sub != "exec" or (w[2] if len(w) > 2 else "") != "rspec":
            refuse("bundle runs only as 'bundle exec rspec'")
        w = w[2:]
        prog = "rspec"
    if prog == "rspec":
        for t in w[1:]:
            if t.startswith("-"):
                refuse(f"'rspec {t}': rspec takes paths only here")
        return
    if prog in ("semgrep", "opengrep"):
        if sub == "scan":
            w = [prog] + w[2:]
        elif sub and not sub.startswith("-"):
            refuse(f"'{prog} {sub}': {prog} runs here only as a scan, with its flags first")
        return judge_semgrep(prog, w, cwd)
    if prog == "rm":
        return judge_scratch_rm(w, cwd, state)
    if prog == "find":
        return judge_find(w)
    if prog in ("egrep", "fgrep"):
        return judge_flags(prog, w[1:], READERS["grep"])
    if prog in READERS:
        judge_flags(prog, w[1:], READERS[prog], numbers=prog in ("head", "tail"))
        # A lone - is a file name too (standard input), so uniq - OUT writes OUT.
        if prog == "uniq" and len([t for t in w[1:] if t == "-" or not t.startswith("-")]) > 1:
            refuse("uniq with a second file writes that file; this shell writes no file")
        if prog == "printf" and len(w) > 1 and w[1].startswith("-"):
            refuse("printf takes no flag here")
        return
    refuse(f"'{prog}' is not one of the commands this shell runs")


def state_folder(cwd):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from project_fact import state_dir
        return state_dir(cwd)
    except Exception:
        return ".claude/state"


def main(argv):
    if argv == ["--summary"]:
        print(SUMMARY)
        return 0
    cwd = os.getcwd()
    if len(argv) == 2 and argv[0] == "--cwd" and argv[1]:
        cwd = argv[1]
    cmd = sys.stdin.read()
    try:
        state = state_folder(cwd)
        for command in tokenize(cmd.strip()):
            judge_command(command, cwd, state)
    except Refused as why:
        print(str(why))
        print(f"Allowed: {SUMMARY}. The full list is at the top of hooks/reviewer_shapes.py. Read files with "
              "Read, Glob and Grep, and write your findings with the Write tool.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
