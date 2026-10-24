#!/usr/bin/env bash
# Test for korium-index-on-stop.sh. Proves it runs `korium-cli index` for any
# change, a YAML-only one included, and stays quiet only when switched off.
# Self-contained: a throwaway git repo and a stub korium-cli that records how it
# was called.
#
# Run from anywhere: bash ~/.claude/hooks/tests/korium-index-on-stop-test.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="${HOOK:-$HERE/../korium-index-on-stop.sh}"
TMPROOT="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/korium-index-on-stop-test.XXXXXX")" && pwd -P)"
trap 'rm -rf "$TMPROOT"' EXIT

pass=0
failures=0

mkdir -p "$TMPROOT/bin"
cat > "$TMPROOT/bin/korium-cli" <<'STUB'
#!/usr/bin/env bash
printf '%s %s\n' "$(pwd -P)" "$*" >> "$KORIUM_STUB_LOG"
STUB
chmod +x "$TMPROOT/bin/korium-cli"

new_repo() {
  repo="$TMPROOT/$1"
  mkdir -p "$repo"
  git -C "$repo" init -q
  git -C "$repo" config user.email t@example.com
  git -C "$repo" config user.name t
  printf 'seed\n' > "$repo/seed.txt"
  git -C "$repo" add -A
  git -C "$repo" commit -qm seed
  echo "$repo"
}

# run_hook <repo> <log> [env assignments...]: run the hook, then give the
# background index a moment to write its line.
run_hook() {
  repo="$1"; log="$2"; shift 2
  : > "$log"
  env PATH="$TMPROOT/bin:$PATH" CLAUDE_PROJECT_DIR="$repo" KORIUM_STUB_LOG="$log" "$@" \
    bash "$HOOK" </dev/null >/dev/null 2>&1
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -s "$log" ] && break
    sleep 0.2
  done
}

check() {
  label="$1"; expected="$2"; actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "ok   - $label"
    pass=$((pass + 1))
  else
    echo "FAIL - $label (expected '$expected', got '$actual')"
    failures=$((failures + 1))
  fi
}

ran() { grep -c "index --from-hook --no-wait" "$1" 2>/dev/null | tr -d ' '; }

repo="$(new_repo yaml-only)"
printf 'key: value\n' > "$repo/config.yml"
run_hook "$repo" "$TMPROOT/yaml.log" MASTHEAD_INDEX_ON_STOP=
check "a YAML-only change runs the index" 1 "$(ran "$TMPROOT/yaml.log")"
check "and runs it in the checkout" 1 "$(grep -c "^$repo " "$TMPROOT/yaml.log" | tr -d ' ')"

repo="$(new_repo clean)"
run_hook "$repo" "$TMPROOT/clean.log" MASTHEAD_INDEX_ON_STOP=
check "a clean tree runs it too, so committed work is indexed" 1 "$(ran "$TMPROOT/clean.log")"

repo="$(new_repo switched-off)"
run_hook "$repo" "$TMPROOT/off.log" MASTHEAD_INDEX_ON_STOP=off
check "MASTHEAD_INDEX_ON_STOP=off runs nothing" 0 "$(ran "$TMPROOT/off.log")"

repo="$(new_repo git-off)"
git -C "$repo" config korium.indexOnStop false
run_hook "$repo" "$TMPROOT/gitoff.log" MASTHEAD_INDEX_ON_STOP=
check "git config korium.indexOnStop false runs nothing" 0 "$(ran "$TMPROOT/gitoff.log")"

repo="$(new_repo busy)"
sleep 30 &
busy=$!
echo "$busy" > "$(git -C "$repo" rev-parse --absolute-git-dir)/korium-index-stop.pid"
run_hook "$repo" "$TMPROOT/busy.log" MASTHEAD_INDEX_ON_STOP=
kill "$busy" 2>/dev/null
check "a run still going is left alone" 0 "$(ran "$TMPROOT/busy.log")"

echo
echo "$pass passed, $failures failed"
[ "$failures" -eq 0 ]
