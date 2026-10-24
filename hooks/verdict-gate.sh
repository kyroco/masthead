#!/usr/bin/env bash
# Verdict-discipline validator, wired on Stop and SubagentStop: block (exit 2) when a changed case file lacks a file:line verdict or two numbered observations.
# Exit 0 passes and stderr is the feedback; CASE_FILE_GLOB names the case file (default last-case-file.md).

set -uo pipefail

CASE_GLOB="${CASE_FILE_GLOB:-last-case-file.md}"

fail=0

# Check one case file and set fail=1 on any violation.
check_case_file() {
  cf_path="$1"      # path as the pipeline sees it (used in the feedback)
  cf_file="$2"      # path to actually read

  if [ ! -r "$cf_file" ]; then
    echo "BLOCK: $cf_path - case file changed but is not readable at $cf_file, so the gate cannot verify it and fails closed. Fix the path (CASE_FILE_GLOB) or the file." >&2
    fail=1
    return
  fi

  # Require the Verdict section to name a file:line token.
  verdict_block="$(awk '/^## *Verdict/{grab=1; next} /^## /{grab=0} grab{print}' "$cf_file")"
  if [ -z "$(printf '%s' "$verdict_block" | tr -d '[:space:]')" ]; then
    echo "BLOCK: $cf_path - no '## Verdict' section, or it is empty. A hunt ends in a verdict that names a mechanism AT a location." >&2
    fail=1
  elif ! printf '%s\n' "$verdict_block" | grep -Eq '[A-Za-z0-9_./-]+:[0-9]+'; then
    echo "BLOCK: $cf_path - Verdict section names no file:line. A root cause is a mechanism AT a location (Iron Law: specific file:line + mechanism)." >&2
    fail=1
  fi

  # (b) Evidence section must list >=2 numbered observations.
  evidence_block="$(awk '/^## *Evidence/{grab=1; next} /^## /{grab=0} grab{print}' "$cf_file")"
  obs_count="$(printf '%s\n' "$evidence_block" | grep -Ec '^[[:space:]]*[0-9]+[.)]' || true)"
  if [ "${obs_count:-0}" -lt 2 ]; then
    echo "BLOCK: $cf_path - Evidence lists ${obs_count:-0} numbered observation(s); the two-observation rule requires AT LEAST TWO independent observations before a verdict. One observation is a hypothesis - keep hunting or move it to Unknowns." >&2
    fail=1
  fi
}

# Find the case files changed in this session and check each one.
repo_root=""
if git rev-parse --show-toplevel >/dev/null 2>&1; then
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
fi

if [ -n "$repo_root" ]; then
  matched=0
  # Read git status line by line (-uall so new directories show) and resolve each path against the repo root.
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    status_code="$(printf '%s' "$line" | cut -c1-2)"
    path="$(printf '%s' "$line" | cut -c4-)"
    case "$path" in *" -> "*) path="${path##* -> }" ;; esac
    path="${path#\"}"
    path="${path%\"}"
    # only case files are this gate's business
    case "$path" in
      *"$CASE_GLOB"|*case-file*.md) ;;
      *) continue ;;
    esac
    # a deleted case file has no verdict left to hold to the law
    case "$status_code" in *D*) continue ;; esac
    matched=1
    check_case_file "$path" "$repo_root/$path"
  done <<EOF
$(git status --porcelain -uall 2>/dev/null)
EOF

  [ "$matched" -eq 0 ] && exit 0   # no case file changed this session -> nothing for this gate to hold
else
  # Without git, check the configured case file directly when it exists.
  echo "WARN: not a git repo - cannot delta-scope; falling back to checking $CASE_GLOB directly." >&2
  [ -e "$CASE_GLOB" ] || exit 0
  check_case_file "$CASE_GLOB" "$CASE_GLOB"
fi

if [ "$fail" -ne 0 ]; then
  echo "Verdict-discipline gate FAILED - the case file does not clear the two-observations verdict-gate. Do not declare the hunt done until it does." >&2
  exit 2
fi
exit 0
