#!/usr/bin/env bash
# hard-gate.sh -- the done gate for every stack: a PreToolUse hook on Bash that runs on `git push` and `gh pr create`.
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
  *push*|*"pr create"*|*create-pr*) ;;
  *) exit 0 ;;
esac
# Parse the payload in one python3 call: the cwd on the first line, the command after it.
_PARSED="$(printf '%s' "$_PAYLOAD" | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
print(d.get("cwd",""))
print((d.get("tool_input") or {}).get("command",""))' 2>/dev/null || true)"
_CWD="$(printf '%s\n' "$_PARSED" | head -1)"
_CMD="$(printf '%s\n' "$_PARSED" | tail -n +2)"
# Pass the command unless it is a git push, a `gh pr create` or a create-pr.sh run; a here-string avoids a SIGPIPE false pass.
if ! grep -Eq '(^|[^[:alnum:]_./-])git([[:space:]]+[^;&|[:space:]]+)*[[:space:]]+push([[:space:]]|$|[;&|])|gh[[:space:]]+pr[[:space:]]+create|create-pr\.sh' <<<"$_CMD"; then
  exit 0
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
          printf "%d:%s\n", NR, line
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
        printf "%s: %s\n", file, line
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

  # The local-tests rung at the end covers the tests.
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
        if [ -e "$d/$marker" ]; then found="$d"; break; fi
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

[ -n "$SECRETSCAN" ] && gate_secrets
[ -n "$ELIXIR" ] && each_root gate_elixir "mix.lock mix.exs" ELIXIR
[ -n "$NODE" ]   && each_root gate_node package.json NODE
# No Rust rung; CI runs it.
[ -n "$SWIFT" ]  && each_root gate_swift Package.swift SWIFT
[ -n "$KOTLIN" ] && each_root gate_kotlin gradlew KOTLIN
[ -n "$TF" ]     && gate_tf

# Local tests: require the push-check script's receipt for HEAD, and refuse a push of any other commit.
gate_local_tests() {
  check_script="$(project_fact "$TOP" --path PROJECT_PUSH_CHECK)"
  [ -n "$check_script" ] && [ -f "$check_script" ] || return 0
  check_rel="${check_script#"$TOP"/}"
  sends="$(python3 - "$_CMD" "$(git rev-parse --verify -q 'HEAD^{tree}' 2>/dev/null)" <<'PYEOF' 2>/dev/null || echo check
import re, shlex, subprocess, sys
cmd, head_tree = sys.argv[1], sys.argv[2]
VALUED = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
verdict = "skip"
for seg in re.split(r"\n|;|&&|\|\||\|", cmd):
    try:
        words = shlex.split(seg)
    except ValueError:
        words = seg.split()
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words.pop(0)
    if not words:
        continue
    joined = " ".join(words)
    if re.search(r"(^|\s)gh\s+pr\s+create(\s|$)|create-pr\.sh", joined):
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
)"
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
gate_local_tests

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "Nothing was pushed. Fix the failures above and push again; the gate re-runs on the branch." >&2
  exit 2
fi

exit 0
