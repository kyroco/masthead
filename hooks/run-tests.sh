#!/usr/bin/env bash
# Run every test suite for the shared hooks in this folder; nothing runs these in CI.
# Usage: bash hooks/run-tests.sh (CLAUDE_PROJECT_DIR is unset so the calling repo cannot make a hook stand down).

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
unset CLAUDE_PROJECT_DIR
cd "${TMPDIR:-/tmp}" || exit 1

failed=0
suites=0
run() {
  local label="$1"
  shift
  suites=$((suites + 1))
  local out
  if out="$("$@" 2>&1)"; then
    printf 'ok    %-28s %s\n' "$label" "$(printf '%s' "$out" | tail -1 | cut -c1-90)"
  else
    failed=$((failed + 1))
    printf 'FAIL  %-28s\n' "$label"
    printf '%s\n' "$out" | tail -15
  fi
}

run "install options"        bash "$here/tests/run-sh-test.sh"
run "brief gates"            python3 "$here/test-brief-gates.py"
run "shared safety gates"    python3 "$here/test-shared-safety-gates.py"
run "commit attribution"     python3 "$here/test-commit-attribution-gate.py"
run "redundant grep"         bash "$here/test-redundant-grep-gate.sh"
run "code search judge down" bash "$here/tests/gate-discovery-judge-down-test.sh"
run "code search index judge" bash "$here/tests/korium-index-judge-test.sh"
run "code search index hint" bash "$here/tests/korium-index-hint-test.sh"
run "model choice"           bash "$here/tests/model-choice-gate-test.sh"
run "reviewer shell scope"   bash "$here/tests/bash-scope-reviewer-test.sh"
run "diagnoser shell scope"  bash "$here/tests/bash-scope-diagnoser-test.sh"
run "review write fence"     bash "$here/tests/review-write-fence-test.sh"
run "secret fetch cases"     python3 "$here/tests/run-block-secret-fetches-cases.py"
run "secret read gate"       python3 "$here/test-secret-gate.py"
run "masked reader"          python3 "$here/tests/read-redacted-test.py"
run "work gates"             python3 "$here/test-work-gates.py"
run "ADR structure gate"     bash "$here/tests/adr-structure-gate-test.sh"
run "Elixir hooks"           bash "$here/tests/elixir-hooks-test.sh"
run "wiki refresh"           bash "$here/tests/wiki-refresh-test.sh"
run "push gate"              bash "$here/tests/hard-gate-test.sh"
run "push check script"      bash "$here/tests/push-check-test.sh"
run "abilities file"         bash "$here/tests/abilities-test.sh"
run "scope gate"             bash "$here/tests/scope-gate-test.sh"
run "verdict gate"           bash "$here/tests/verdict-gate-test.sh"
run "index on stop"          bash "$here/tests/korium-index-on-stop-test.sh"
run "tool output scan"       python3 "$here/tests/run-scan-tool-output-cases.py"
run "tool output incident"   python3 "$here/tests/incident-shape-probe.py"
run "instruction rules"      bash "$here/tests/instruction-rules-test.sh"
run "pictures fit"           python3 "$here/../scripts/svgcheck.py" "$here"/../docs/images/*.svg
run "issue edit gate"        python3 "$here/tests/issue-edit-gate-test.py"
run "proof: brief gates"     bash "$here/proof/brief-gates-selftest.sh"
run "proof: discovery"       bash "$here/proof/gate-discovery-bash-selftest.sh"
run "proof: mark codesearch" bash "$here/proof/mark-codesearch-selftest.sh"
run "proof: mark grep"       bash "$here/proof/mark-grep-selftest.sh"

echo
if [ "$failed" -gt 0 ]; then
  echo "$failed suite(s) failed"
  exit 1
fi
echo "all $suites suites pass"
