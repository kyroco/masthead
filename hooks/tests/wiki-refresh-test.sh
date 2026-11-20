#!/usr/bin/env bash
# wiki-refresh-test.sh: the wiki token goes only to GitHub, only for the remote the repo names, and never into some other clone.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/../wiki-refresh.sh"
pass=0; fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL  $1" >&2; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
# A fake git that records every call and answers config --get remote.origin.url from FAKE_ORIGIN.
mkdir -p "$T/bin"
cat > "$T/bin/git" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_LOG"
case "$*" in *"config --get remote.origin.url"*) printf '%s\n' "${FAKE_ORIGIN:-}" ;; esac
exit 0
SH
chmod +x "$T/bin/git"
export PATH="$T/bin:$PATH" FAKE_LOG="$T/git.log" WIKI_GIT_TOKEN="fake-token-for-the-test"
repo() { # $1 folder, $2 ADR_DIR, $3 ADR_REMOTE
  mkdir -p "$1/.claude" "$1/.git"
  printf '{"env": {"ADR_DIR": "%s", "ADR_REMOTE": "%s"}}\n' "$2" "$3" > "$1/.claude/settings.json"
}
run() { : > "$FAKE_LOG"; printf '{"hook_event_name":"SessionStart"}' | env CLAUDE_PROJECT_DIR="$1" HOME="$T/home" bash "$HOOK"; sleep 1; }
mkdir -p "$T/home"

# 1. A remote on another host never receives the token.
repo "$T/r1" "$T/home/wiki-a/ADR" "https://evil.example.com/x/wiki.git"
run "$T/r1"
if grep -q "extraHeader" "$FAKE_LOG" 2>/dev/null; then bad "the token was sent to a host that is not GitHub"; else ok; fi
grep -q "clone" "$FAKE_LOG" 2>/dev/null && ok || bad "a plain clone of a non-GitHub remote should still happen, without the token"

# 2. A GitHub remote gets the token with its clone.
repo "$T/r2" "$T/home/wiki-b/ADR" "https://github.com/example/wiki.git"
run "$T/r2"
grep -q "extraHeader" "$FAKE_LOG" 2>/dev/null && ok || bad "a GitHub remote should get the token: $(cat "$FAKE_LOG")"

# 3. ADR_DIR inside an existing clone of some other repository: nothing is pulled and no token is written.
mkdir -p "$T/home/other/.git" "$T/home/other/ADR"
repo "$T/r3" "$T/home/other/ADR" "https://github.com/example/wiki.git"
FAKE_ORIGIN="https://github.com/someone/else.git" run "$T/r3"
if grep -q -e "pull" -e "extraHeader" "$FAKE_LOG" 2>/dev/null; then bad "an unrelated clone was pulled or given the token: $(cat "$FAKE_LOG")"; else ok; fi

# 4. ADR_DIR inside the clone of the named remote: pulled, token kept.
FAKE_ORIGIN="https://github.com/example/wiki.git" run "$T/r3"
grep -q "pull" "$FAKE_LOG" 2>/dev/null && ok || bad "the right clone should be pulled: $(cat "$FAKE_LOG")"

# 5. MAST-48: a cloud thread's first start, with the repository in the clones folder and no list of attached
# repositories yet. wiki-refresh runs beside attached-repos.py, in no set order, so it must find the repository
# itself: the repository's wiki is cloned though no other hook wrote the list first.
mkdir -p "$T/cloud/home" "$T/cloud/config"
repo "$T/cloud/home/app" "$T/home/wiki-c/ADR" "https://github.com/example/wiki-c.git"
: > "$FAKE_LOG"
printf '{"hook_event_name":"SessionStart","source":"startup"}' | env CLAUDE_CODE_REMOTE=true \
  CLAUDE_PROJECT_DIR="$T/cloud/home" CLAUDE_CONFIG_DIR="$T/cloud/config" HOME="$T/home" bash "$HOOK" 2>"$T/err"; sleep 1
grep -q "clone.*wiki-c" "$FAKE_LOG" 2>/dev/null && ok || bad "a cloud thread's first start should clone its repository's wiki: $(cat "$FAKE_LOG")"
# The fake git leaves no .git/config, so keep_header's chmod complains; only the missing list matters here.
grep -q "cloud-session-repos" "$T/err" && bad "a cloud thread's first start printed: $(cat "$T/err")" || ok

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
