#!/usr/bin/env bash
# review-write-fence-test.sh - behavioural test for review-write-fence.py.
#
# Feeds the hook real PreToolUse payloads against a throwaway checkout and
# asserts which writes it refuses, then checks it is wired in settings.json.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$SCRIPT_DIR/../review-write-fence.py"
SETTINGS="$SCRIPT_DIR/../hooks.json"
pass=0
fail=0

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
W="$(cd "$W" && pwd -P)"
mkdir -p "$W/repo/.git" "$W/repo/.claude/state/review" "$W/repo/lib/sub" "$W/norepo/.claude/state/review"
echo x > "$W/repo/lib/a.ex"
ln -s "$W/repo/lib/a.ex" "$W/repo/.claude/state/review/findings-verifier-planted.json"
mkdir -p "$W/repo2/.git" "$W/repo2/.claude/state" "$W/repo2/lib"
ln -s "$W/repo2/lib" "$W/repo2/.claude/state/review"
# Facts are read from the session's own repository, so pin it to this one; it
# states no PROJECT_STATE_DIR, so the default folder is in play.
export CLAUDE_PROJECT_DIR="$W/repo"

# case_ <expect: allow|deny> <label> <json>
case_() {
  local expect="$1" label="$2" json="$3" hook="${4:-$HOOK}" out got
  out="$(printf '%s' "$json" | python3 "$hook")"
  if printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then got=deny; else got=allow; fi
  if [ "$got" = "$expect" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL  %s: expected %s, got %s\n      %s\n' "$label" "$expect" "$got" "$out" >&2
  fi
}

# p <tool> <agent-field> <agent-value> <path> [cwd] [agent_id]
p() {
  local field="" id=""
  [ -n "$2" ] && field="\"$2\": \"$3\","
  [ -n "${6:-}" ] && id="\"agent_id\": \"$6\","
  printf '{"tool_name": "%s", %s %s "cwd": "%s", "tool_input": {"file_path": "%s", "content": "[]"}}' "$1" "$field" "$id" "${5:-$W/repo}" "$4"
}

R="$W/repo/.claude/state/review"
case_ allow "verifier writes its findings file"        "$(p Write agent_type verifier "$R/findings-verifier-contract.json")"
case_ allow "verifier edits its findings file"         "$(p Edit agent_type verifier "$R/findings-verifier-contract.json")"
case_ allow "security-reviewer writes its findings"    "$(p Write agent_type security-reviewer "$R/findings-security-reviewer.json")"
case_ allow "a relative findings path from the root"   "$(p Write agent_type verifier ".claude/state/review/findings-verifier-omission.json")"
case_ deny  "verifier writes source"                   "$(p Write agent_type verifier "$W/repo/lib/a.ex")"
case_ deny  "verifier edits source"                    "$(p Edit agent_type verifier "$W/repo/lib/a.ex")"
case_ deny  "verifier writes the security findings"    "$(p Write agent_type verifier "$R/findings-security-reviewer.json")"
case_ deny  "security-reviewer writes an angle file"   "$(p Write agent_type security-reviewer "$R/findings-verifier-contract.json")"
case_ deny  "verifier writes validity.json"            "$(p Write agent_type verifier "$R/validity.json")"
case_ deny  "security-reviewer writes source"          "$(p Write agent_type security-reviewer "$W/repo/lib/a.ex")"
case_ allow "verifier still writes any angle file"     "$(p Write agent_type verifier "$R/findings-verifier-adversarial.json")"
case_ deny  "a dispatch label names the verifier"      "$(p Write agent_name verifier-contract "$W/repo/lib/a.ex")"
case_ deny  "a label with an underscore"               "$(p Write agent_type verifier_contract "$W/repo/lib/a.ex")"
case_ deny  "a label with a dot"                       "$(p Write agent_type verifier.contract "$W/repo/lib/a.ex")"
case_ deny  "masthead's namespaced verifier"          "$(p Write agent_type masthead:verifier "$W/repo/lib/a.ex")"
case_ allow "another plugin's verifier is not fenced"  "$(p Write agent_type otherplugin:verifier "$W/repo/lib/a.ex")"
case_ deny  "masthead's verifier in a subfolder"      "$(p Write agent_type masthead:review:verifier "$W/repo/lib/a.ex")"
case_ deny  "a masthead subfolder named for the verifier" "$(p Write agent_type masthead:verifier:contract "$W/repo/lib/a.ex")"
case_ deny  "a verifier in a folder named for the other" "$(p Write agent_type masthead:security-reviewer:verifier "$R/findings-security-reviewer.json")"
case_ allow "a security verifier in a verifier folder"  "$(p Write agent_type masthead:verifier:security-reviewer "$R/findings-security-reviewer.json")"
case_ deny  "subagent_type names the verifier"         "$(p Write subagent_type verifier "$W/repo/lib/a.ex")"
case_ deny  "a traversal out of the review folder"     "$(p Write agent_type verifier "$R/../../lib/findings-verifier-x.json")"
case_ deny  "a findings name two folders into source"  "$(p Write agent_type verifier "$W/repo/lib/sub/findings-verifier-x.json")"
case_ deny  "a symlinked findings file"                "$(p Write agent_type verifier "$R/findings-verifier-planted.json")"
case_ deny  "a review folder that is a symlink"        "$(p Write agent_type verifier "$W/repo2/.claude/state/review/findings-verifier-x.json" "$W/repo2")"
case_ deny  "a review folder outside any checkout"     "$(p Write agent_type verifier "$W/norepo/.claude/state/review/findings-verifier-x.json")"
case_ deny  "a differently named json"                 "$(p Write agent_type verifier "$R/union.json")"
case_ deny  "a notebook edit by a verifier"            "{\"tool_name\": \"NotebookEdit\", \"agent_type\": \"verifier\", \"tool_input\": {\"notebook_path\": \"$W/repo/lib/n.ipynb\"}}"
case_ deny  "a tool_input that is not an object"       "{\"tool_name\": \"Write\", \"agent_type\": \"verifier\", \"tool_input\": \"x\"}"
case_ deny  "an unparseable payload"                   "not json"

# A security review names its own file, so one round does not overwrite the last.
case_ allow "security-reviewer writes a named file"    "$(p Write agent_type security-reviewer "$R/findings-security-reviewer-devop.json")"
case_ deny  "a named security file in capitals"        "$(p Write agent_type security-reviewer "$R/findings-security-reviewer-DevOp.json")"
case_ deny  "an empty name after the dash"             "$(p Write agent_type security-reviewer "$R/findings-security-reviewer-.json")"
case_ deny  "verifier writes a named security file"    "$(p Write agent_type verifier "$R/findings-security-reviewer-devop.json")"

# The scratch folder: a throwaway copy a verifier may change to run a test,
# never the checkout under review.
mkdir -p "$W/repo/.claude/state/review/scratch/wt/lib"
ln -s "$W/repo/lib" "$W/repo/.claude/state/review/scratch/out"
ln -s "$W/repo/lib/a.ex" "$W/repo/.claude/state/review/scratch/planted.ex"
case_ allow "verifier writes a scratch script"         "$(p Write agent_type verifier "$R/scratch/run.sh")"
case_ allow "verifier edits a scratch copy's source"   "$(p Edit agent_type verifier "$R/scratch/wt/lib/a.ex")"
case_ allow "security-reviewer writes a scratch file"  "$(p Write agent_type security-reviewer "$R/scratch/probe.exs")"
case_ allow "a scratch folder not made yet"            "$(p Write agent_type verifier "$R/scratch/new/deep/x.exs")"
case_ deny  "a scratch path through a symlinked folder" "$(p Write agent_type verifier "$R/scratch/out/a.ex")"
case_ deny  "a symlinked scratch file"                 "$(p Write agent_type verifier "$R/scratch/planted.ex")"
case_ deny  "a traversal out of scratch"               "$(p Write agent_type verifier "$R/scratch/../../../lib/a.ex")"
case_ deny  "a folder named like scratch"              "$(p Write agent_type verifier "$R/scratchy/run.sh")"
case_ deny  "scratch outside any checkout"             "$(p Write agent_type verifier "$W/norepo/.claude/state/review/scratch/run.sh")"

# No claim outlives a review: a second verifier sent for the same file writes it.
case_ allow "agent one writes the exercise findings"   "$(p Write agent_type verifier "$R/findings-verifier-exercise.json" "" agent-one)"
case_ allow "a later verifier writes the same file"    "$(p Write agent_type verifier "$R/findings-verifier-exercise.json" "" agent-two)"
[ ! -e "$R/.writers.json" ] && pass=$((pass + 1)) \
  || { fail=$((fail + 1)); echo "FAIL  the fence wrote a claims ledger" >&2; }

# The agent list is read from bash-scope-verifier.sh. Without it, a call that
# names any agent is refused, and the main session still passes.
mkdir -p "$W/lonely"
cp "$HOOK" "$W/lonely/review-write-fence.py"
case_ deny  "no agent list: a named agent is refused"  "$(p Write agent_type verifier "$R/findings-verifier-lone.json")" "$W/lonely/review-write-fence.py"
case_ allow "no agent list: the main session passes"   "$(p Write "" "" "$W/repo/lib/a.ex")" "$W/lonely/review-write-fence.py"

case_ allow "the main session writes source"           "$(p Write "" "" "$W/repo/lib/a.ex")"

case_ allow "another agent writes source"              "$(p Write agent_type diagnoser "$W/repo/lib/a.ex")"
case_ allow "a look-alike name is not governed"        "$(p Write agent_type verifierlookalike "$W/repo/lib/a.ex")"
case_ allow "a verifier's Read is not this gate's"     "{\"tool_name\": \"Read\", \"agent_type\": \"verifier\", \"tool_input\": {\"file_path\": \"$W/repo/lib/a.ex\"}}"

# THE STATE FOLDER IS THE REPO'S CHOICE: a repo whose settings state
# PROJECT_STATE_DIR keeps its review folder there, and the default path is refused.
mkdir -p "$W/repo3/.git" "$W/repo3/.kyroco/review" "$W/repo3/.claude/state/review"
echo '{"env": {"PROJECT_STATE_DIR": ".kyroco"}}' > "$W/repo3/.claude/settings.json"
export CLAUDE_PROJECT_DIR="$W/repo3"
case_ allow "a repo's own state folder takes the findings"   "$(p Write agent_type verifier "$W/repo3/.kyroco/review/findings-verifier-x.json" "$W/repo3")"
case_ deny  "and the default folder is refused there"        "$(p Write agent_type verifier "$W/repo3/.claude/state/review/findings-verifier-x.json" "$W/repo3")"
case_ allow "scratch under the repo's own state folder"      "$(p Write agent_type verifier "$W/repo3/.kyroco/review/scratch/run.sh" "$W/repo3")"
export CLAUDE_PROJECT_DIR="$W/repo"

if jq -e '.hooks.PreToolUse[] | select((.matcher // "") | test("Write") and test("Edit") and test("MultiEdit") and test("NotebookEdit"))
          | .hooks[] | select(.command | contains("review-write-fence.py"))' "$SETTINGS" >/dev/null 2>&1; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  echo "FAIL  review-write-fence.py is not wired on Write, Edit, MultiEdit and NotebookEdit in settings.json" >&2
fi

printf '[review-write-fence-test] %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
