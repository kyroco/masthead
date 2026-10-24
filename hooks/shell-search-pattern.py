#!/usr/bin/env python3
"""Print the pattern and path of the first codebase search in a shell command read from stdin, as JSON, for gate-discovery."""
import json
import re
import shlex
import sys

SEARCHERS = {"rg", "grep", "egrep", "fgrep"}

# Words that run the word after them, possibly with options of their own.
WRAPPERS = {"time", "env", "nohup", "command", "exec", "nice", "xargs", "sudo",
            "timeout", "if", "while", "until", "do", "then", "else", "elif", "!", "{"}

PUNCTUATION = ";&|()"
PIPES = {"|", "|&"}

# Options that take their value as the next argument, per program; long options also accept --opt=value.
GREP_SHORT = set("ABCmfedD")
GREP_LONG = {"--after-context", "--before-context", "--context", "--max-count",
             "--file", "--regexp", "--include", "--exclude", "--exclude-dir",
             "--exclude-from", "--label", "--binary-files", "--directories",
             "--devices", "--group-separator"}
RG_SHORT = set("ABCmgtTjMrEfed")
RG_LONG = {"--after-context", "--before-context", "--context", "--max-count",
           "--glob", "--iglob", "--type", "--type-not", "--type-add", "--type-clear",
           "--threads", "--max-columns", "--replace", "--encoding", "--file",
           "--regexp", "--sort", "--sortr", "--max-depth", "--max-filesize",
           "--path-separator", "--colors", "--context-separator",
           "--field-match-separator", "--field-context-separator", "--pre",
           "--pre-glob", "--ignore-file", "--dfa-size-limit", "--regex-size-limit",
           "--engine", "--hostname-bin", "--hyperlink-format", "--generate",
           "--color"}
# Options whose value says which files are searched, passed to the judge.
FILTERS = {"-g", "--glob", "--iglob", "-t", "--type", "--include"}
# Options that make the command something other than a content search.
NOT_A_SEARCH = {"--files", "--type-list", "--help", "--version", "-V", "-h"}
# Options that read patterns from a file; no pattern is on the command line, so the search is allowed.
PATTERN_FILE = {"-f", "--file"}

HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SUBSHELL = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
REDIRECT = re.compile(r"^\d*(>>?|<<?|&>>?|>&|<&)")


def drop_heredocs(cmd):
    """Remove every heredoc body, keeping the line that opens it."""
    lines, out, end = cmd.split("\n"), [], None
    for line in lines:
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            end = m.group(2)
    return "\n".join(out)


def pieces(cmd):
    """The command line and every `$( )` or backtick body, each on its own."""
    found = []
    while True:
        m = SUBSHELL.search(cmd)
        if not m:
            break
        found.append(m.group(1) if m.group(1) is not None else m.group(2))
        cmd = cmd[:m.start()] + " X " + cmd[m.end():]
    return [cmd] + found


def unquote(tok):
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"":
        return tok[1:-1]
    return tok


def commands(cmd):
    """Yield (tokens, reads_pipe) for each simple command in one piece."""
    # Split with shlex in non-POSIX mode so a quoted operator stays one token, after removing 2>&1 and &>file.
    cmd = re.sub(r"\d*[<>]&[\d-]", " ", cmd)
    cmd = re.sub(r"&>", ">", cmd)
    lexer = shlex.shlex(cmd.replace("\n", " ; "), posix=False, punctuation_chars=PUNCTUATION)
    lexer.whitespace_split = True
    lexer.commenters = ""
    current, piped, skip_next = [], False, False
    for tok in lexer:
        if skip_next:
            skip_next = False
            continue
        if tok[0] not in "'\"" and all(c in PUNCTUATION for c in tok):
            if current:
                yield current, piped
            # `cmd | (grep x)` still reads the pipe.
            current, piped = [], tok in PIPES or (tok == "(" and piped)
            continue
        m = REDIRECT.match(tok)
        if m and tok[0] not in "'\"":
            # A redirection with its target after a space: skip the target.
            skip_next = tok == m.group(0) and not tok.endswith("&")
            continue
        current.append(unquote(tok))
    if current:
        yield current, piped


def program(tokens):
    """Strip wrappers and assignments; return (searcher, args) or None."""
    def is_program(word):
        return word.rsplit("/", 1)[-1] in SEARCHERS | {"git"}

    i, wrapped = 0, False
    while i < len(tokens):
        word = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            i += 1
        elif word in WRAPPERS:
            i, wrapped = i + 1, True
        else:
            break
    # After a wrapper, skip its own options and take the first searcher within the next several words.
    if wrapped and i < len(tokens) and not is_program(tokens[i]):
        for k in range(i, min(i + 8, len(tokens))):
            if is_program(tokens[k]):
                i = k
                break
    rest = tokens[i:]
    if len(rest) >= 2 and rest[0].rsplit("/", 1)[-1] == "git" and rest[1] == "grep":
        return "grep", rest[2:]
    if rest and rest[0].rsplit("/", 1)[-1] in SEARCHERS:
        name = rest[0].rsplit("/", 1)[-1]
        return ("rg" if name == "rg" else "grep"), rest[1:]
    return None


def search_args(tokens):
    """Return (pattern, path) for one search command, or None."""
    found = program(tokens)
    if not found:
        return None
    name, argv = found
    short = RG_SHORT if name == "rg" else GREP_SHORT
    long_ = RG_LONG if name == "rg" else GREP_LONG
    patterns, positional, filters = [], [], []
    it = iter(argv)
    options_done = False
    for arg in it:
        if options_done or arg == "-" or not arg.startswith("-"):
            positional.append(arg)
            continue
        if arg == "--":
            options_done = True
            continue
        if arg in NOT_A_SEARCH or arg.split("=", 1)[0] in NOT_A_SEARCH | PATTERN_FILE:
            return None
        if not arg.startswith("--") and "f" in arg[1:] and not any(
                c in short and c != "f" for c in arg[1:arg.index("f")]):
            # `-f pats.txt` or `-nf pats.txt`: a pattern file, read above.
            return None
        if arg.startswith("--"):
            key, eq, val = arg.partition("=")
            if not eq and key in long_:
                val = next(it, "")
            if key == "--regexp" and (eq or key in long_):
                patterns.append(val)
            elif key in FILTERS and val:
                filters.append(val)
            continue
        # Read a cluster of short options one letter at a time; the first letter that takes a value takes the rest.
        for j, ch in enumerate(arg[1:], start=1):
            if ch in short:
                val = arg[j + 1:] or next(it, "")
                if ch == "e":
                    patterns.append(val)
                elif "-" + ch in FILTERS and val:
                    filters.append(val)
                break
    if patterns:
        pattern = " ".join(p for p in patterns if p)
        paths = positional
    elif positional:
        pattern, paths = positional[0], positional[1:]
    else:
        return None
    path = " ".join(([paths[0]] if paths else []) + ["(files: %s)" % f for f in filters])
    return (pattern, path) if pattern else None


def main():
    cmd = drop_heredocs(sys.stdin.read())
    try:
        for piece in pieces(cmd):
            for tokens, piped in commands(piece):
                # Skip a command that reads a pipe, except xargs, which searches the piped file names.
                if piped and tokens[0] != "xargs":
                    continue
                hit = search_args(tokens)
                if hit:
                    print(json.dumps({"pattern": hit[0], "path": hit[1]}))
                    return
    except ValueError:
        return


if __name__ == "__main__":
    main()
