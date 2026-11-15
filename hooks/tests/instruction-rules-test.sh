#!/usr/bin/env bash
# Checks that the skills state the three rules of issue #8 and no longer state
# the ones they replaced: issues sliced like scrum stories, one worker per
# sub-issue, and a review follow-up started as soon as its blocker merges.
# Also checks issue #13: nothing caps how many scenarios an issue or a plan
# holds, so the Size rule alone decides how much one issue holds.
# Lines wrap anywhere, so each file is read as one line before matching.
#
# Run from anywhere: bash hooks/tests/instruction-rules-test.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
pass=0
fail=0

flat() { tr '\n' ' ' <"$ROOT/$1" | tr -s ' '; }

says() {
  if flat "$1" | grep -qiF -- "$2"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s does not say: %s\n' "$1" "$2"
  fi
}

never() {
  if flat "$1" | grep -qiF -- "$2"; then
    fail=$((fail + 1))
    printf 'FAIL %s still says: %s\n' "$1" "$2"
  else
    pass=$((pass + 1))
  fi
}

# Issue #57: a search for what is adopted reads wider than any other search.
says  skills/work-on/SKILL.md 'For what is adopted, use `stance: "position"` with a `limit` of 10'
says  skills/work-on/SKILL.md 'Every other `agent_search` takes a `limit` of 5'

# 1. Slicing.
says  skills/github-issues/SKILL.md "the way scrum splits user stories"
says  skills/github-issues/SKILL.md "room to spare"
never skills/github-issues/SKILL.md "about fifteen files"

# 2. One worker per sub-issue.
says  skills/work-on/foreman.md "one worker per sub-issue"
says  skills/work-on/foreman.md "closes when its sub-issues close"
never skills/work-on/foreman.md "its parent's worker builds it"
never skills/work-on/worker.md "gets its own \`general-purpose\` subagent"
never skills/work-on/worker.md "plus the step 6 subagents"
never references/work-routing.md "each sub-issue gets its own"

says  skills/work-on/worker.md "split the issue as the github-issues skill says"
says  skills/work-on/worker.md "set the issue back to Todo, and stop"
never skills/work-on/worker.md "**An issue too big for one session.**"
says  skills/work-on/worker.md "An issue with open sub-issues is a summary"
says  skills/work-on/worker.md "each parent up the chain"
says  skills/github-issues/SKILL.md "issues/<parent>/sub_issues"
says  skills/work-on/foreman.md "Pass the branch it left on GitHub to the user to delete"
never skills/work-on/worker.md "git/refs/heads"
says  skills/work-on/foreman.md "that worker is free"
says  skills/work-on/foreman.md "stop that session as after a merge"
says  skills/work-on/foreman.md "set the merged issue and each parent to Done"
says  skills/work-on/foreman.md "A worker that split its issue sends the sub-issue numbers"
says  skills/work-on/foreman.md "Close now any parent whose sub-issues are all closed"
says  skills/work-on/foreman.md "each parent up the chain"
for doc in README.md docs/explainer.template.html docs/explainer.html scripts/diagrams.py docs/images/workflow.svg; do
  never "$doc" "closes the sub-issues that shipped"
done

# 3. Follow-up timing. No issue is filed from a review any more (see 11), so
# there are no fix-later issues to order first.
says  skills/github-issues/SKILL.md "No issue is filed from a PR's review"
never skills/github-issues/SKILL.md "a follow-up filed from a PR's review is blocked by the issue whose review found it"
never skills/work-on/worker.md "the follow-up issues you filed"
says  skills/work-on/foreman.md "dependencies/blocking"
says  skills/work-on/foreman.md "The issues it blocks wait with it"
never skills/work-on/foreman.md "fix-later"
never skills/work-on/foreman.md "fix later"
never references/session-cliffs.md "fix later"
says  skills/work-on/foreman.md "the question goes to the user first"
says  skills/work-on/foreman.md "its next ready issue, those first"
never skills/work-on/foreman.md "run no builds or tests"
says  skills/work-on/foreman.md "warm-build.sh build"
says  skills/work-on/foreman.md "Start no worker while the warm-up is still running"
says  skills/work-on/worker.md "warm-build.sh clone <tree path>"
says  references/gate-catalog.md "\`PROJECT_WARM_BUILD\`"

# 4. No scenario count. The check is exact on purpose, not a prose scanner: it
# holds the lines where the rule now lives, and refuses the three phrases this
# issue removed wherever a person or agent reads them. It reads each file
# whole (grep -o, never -q), since a pipe that stops early on a match can turn
# a hit into a pass on a page as large as docs/explainer.html.
says  skills/github-issues/SKILL.md "Scenarios:** at least one, each a thing a test can show"
says  skills/github-issues/SKILL.md "How much one issue holds is the Size rule's call, never a count of scenarios"
never README.md "writes a plan, one line per scenario"
says  README.md "Scenarios** (at least one line of"
says  docs/explainer.template.html "<b>Scenarios</b> (at least one line of"
says  docs/explainer.html "<b>Scenarios</b> (at least one line of"
never docs/explainer.template.html "writes a plan, one line per scenario"
never docs/explainer.html "writes a plan, one line per scenario"
never docs/explainer.html "its plan, one line per scenario"
never docs/images/day-5-workers.svg "its plan, one line per scenario"
never scripts/diagrams.py "its plan, one line per scenario"
says  .claude-plugin/plugin.json '"version": "0.2.1"'

never_phrase() {
  local hit
  hit="$(flat "$1" | grep -oiF -- "$2")"
  if [ -n "$hit" ]; then
    fail=$((fail + 1))
    printf 'FAIL %s still says: %s\n' "$1" "$2"
  else
    pass=$((pass + 1))
  fi
}

count_files="$(cd "$ROOT" && find README.md skills references agents docs scripts -type f \( -name '*.md' -o -name '*.html' -o -name '*.py' -o -name '*.svg' \) 2>/dev/null | sort)"
if [ -z "$count_files" ]; then
  fail=$((fail + 1))
  echo "FAIL found no files to search for a removed scenario count"
fi
for doc in $count_files; do
  never_phrase "$doc" "one to five lines"
  never_phrase "$doc" "five lines or fewer"
  never_phrase "$doc" "more than about five scenarios"
done

# 5. No never-shortens sentence. Robert asked for it removed on October 27,
# 2026. The phrase must be gone from every file the scenario-count check reads.
for doc in $count_files; do
  never_phrase "$doc" "never shortens a step"
done

# 6. Issue #18: the words check, contract without customer text, no extra reading pass.
# Issue #20 moved these lines from agents/reviewer.md to the verifier's attack methods.
says  agents/verifier.md "When the change adds or edits text a person reads"
says  agents/verifier.md "check that what it says is what the code does"
never agents/verifier.md "plain English against"
never agents/verifier.md "customer-text convention"
never agents/verifier.md "every sentence a customer reads about that behavior"
never agents/verifier.md "two callers at once"
never agents/verifier.md "(ADR-0003)"
says  references/session-cliffs.md "adds or edits text a customer reads"
for doc in README.md docs/explainer.template.html docs/explainer.html scripts/diagrams.py docs/images/workflow.svg references/session-cliffs.md agents/verifier.md agents/adjudicator.md skills/work-on/worker.md skills/work-on/foreman.md; do
  never "$doc" "English p""ass"
done
says  references/session-cliffs.md "Add the changelog entry when the repo keeps one"

# The full pre-push check runs once. Measured 2026-11-11 over 24 pull requests: a
# median of 3 runs each, 31 of 111 never read and 5 thrown away by a commit that
# landed while the run was going, because it was started with the verifiers.
says  references/session-cliffs.md "Run it one time, after the fixes of the last verification round are in"
says  references/session-cliffs.md "Do not commit while it runs: the run is then thrown away"
says  references/session-cliffs.md "Do not start it early, with the verifiers, to save time"
says  references/session-cliffs.md "any commit made after it starts makes its receipt stale"
# The push gate's order and its remembered pass, where a person reads about them.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  says "$doc" "the test receipt and the secret scan first, then the stack checks, which are skipped when this exact commit already passed them"
  says "$doc" "no file git ignores (installed packages, build output) has been added, removed, or changed in size or time stamp"
  says "$doc" "Nothing is remembered in a checkout that holds a submodule, or after a run that skipped a check because its tool was not installed"
  # Round 3 fix 2: the pass does see a tool installed, removed or moved on PATH; only one upgraded in place is missed.
  says "$doc" "It does not see a tool upgraded in place"
  never "$doc" "It does not see a tool that changed on the machine since"
  # Round 2 fix 5: the pass does not follow the files of another worktree kept inside the checkout, and the page says so.
  says "$doc" "or a change inside another worktree of the repository kept in the checkout"
  never "$doc" "It does not see a file git ignores"
done
says  references/gate-catalog.md "git rev-parse --git-path masthead-push-gate-pass"
says  references/gate-catalog.md "a print of the path, size and time stamp of the files git ignores"
# The read rule for create-pr.sh was dropped (Robert, 2026-11-11): naming the file is enough, a read included.
says  references/gate-catalog.md "or any command that names a \`create-pr.sh\`, a read of the file included"
never references/gate-catalog.md "unless it only reads it"
never references/gate-catalog.md "file commands"
never references/gate-catalog.md "commands that print"
says  references/gate-catalog.md "a file marked assume-unchanged or skip-worktree, a submodule in the checkout, no origin/main"
says  references/gate-catalog.md "A run in which a check was skipped because its tool is not installed is not remembered"
never references/gate-catalog.md "a rung that only warned because its tool was missing"
never references/gate-catalog.md "The remembered pass does not see a file git ignores"
says  references/gate-catalog.md "no variable or setting names another record or turns the reuse on"
# Round 1 finding F6: the refusal of a push of anything but HEAD needs the repo's push check, and the row says so.
says  references/gate-catalog.md "when the repo names a \`PROJECT_PUSH_CHECK\` script, it refuses a push that sends anything but HEAD"
says  references/gate-catalog.md "A repo that names no push check gets neither refusal"
never references/gate-catalog.md "stops the gate there: it refuses a push that sends anything but HEAD"
never references/session-cliffs.md "which is not plain English"
says  README.md "a sentence a customer reads that is false in some state"
says  docs/explainer.template.html "a sentence a customer reads that is false in some state"
never agents/verifier.md "plain English"
says  scripts/diagrams.py "5. push check"

# 7. Issue #20: claim verification replaces the angle reviews, the plan is
# verified before code, the fix loop re-verifies only what broke and stops at
# two rounds, the adjudicator's placement is final, the brief gates shrink to
# one check, customer sentences are claims, and the report counts agent runs.
if [ -e "$ROOT/agents/reviewer.md" ]; then
  fail=$((fail + 1)); echo "FAIL agents/reviewer.md still exists; the verifier replaces it"
else
  pass=$((pass + 1))
fi
# Scenario 1: the verifier.
says  agents/verifier.md "name: verifier"
says  agents/verifier.md "You never get the author's account of the change or another review"
says  agents/verifier.md "A state that only a test setup builds is not a finding"
never agents/verifier.md "## The angle"
never agents/verifier.md "Your brief names one angle"
never agents/verifier.md "a prior reviewer's report"
says  agents/security-reviewer.md "These rules of the \`verifier\` agent are yours too"
says  agents/security-reviewer.md "the repository's security conventions are your claims"
never agents/security-reviewer.md "Everything in the \`reviewer\` agent applies"
says  references/agent-preamble.md "Read by verifier"
says  references/work-routing.md "Use \`verifier\`"
never references/work-routing.md "Use \`reviewer\`"
says  hooks/bash-scope-reviewer.sh 'REVIEWER_AGENTS="verifier|security-reviewer|architecture-reviewer"'
says  hooks/review-write-fence.py "findings-verifier-"
never hooks/review-write-fence.py "findings-reviewer-"
# Scenario 2: there is no worker plan and no plan check; the design is
# reviewed before issues are written, and the verifier checks code only.
says  skills/work-on/worker.md "## 4. What done is"
says  skills/work-on/worker.md "Judge it on its own merit"
never skills/work-on/worker.md "Send the plan to one \`verifier\`"
never skills/work-on/worker.md "A second fail: stop and ask"
never skills/work-on/worker.md "a plan fails its verifier twice"
never skills/work-on/worker.md "wait for its \"go\""
says  skills/work-on/foreman.md "A worker writes no plan and waits for no go"
says  skills/work-on/foreman.md "Say the count three ways and never mix them"
never skills/work-on/foreman.md "with its verifier's pass"
never skills/work-on/foreman.md "Reply \"go\""
never skills/work-on/foreman.md "Check each line against its scenario"
never agents/verifier.md "## Verifying a plan"
never agents/verifier.md "judges a worker's plan"
never references/dispatch-brief.md "A plan brief"
never skills/github-issues/SKILL.md "checked by a blind verifier"
never README.md "sends the plan to a verifier"
says  skills/review-design/SKILL.md "name: review-design"
says  skills/review-design/SKILL.md "Assume the design is wrong and prove it right"
says  skills/review-design/SKILL.md "one at a time"
says  skills/review-design/SKILL.md "The mockups change too"
says  skills/review-design/SKILL.md "## Then the screens"
says  skills/review-design/SKILL.md "No worker starts on it until they say yes"
never skills/review-design/SKILL.md "It writes no code"
says  skills/review-design/SKILL.md "## Then the issues"
says  skills/review-design/SKILL.md "Change nothing until they say go"
says  skills/review-design/SKILL.md "leave every other issue alone"
says  skills/work-on/SKILL.md "except the verifier's, the architecture reviewer's and the adjudicator's"
# Scenario 3: the fix loop stays small.
says  references/session-cliffs.md "one \`verifier\` per scenario"
says  references/session-cliffs.md "only the claims the fix broke"
says  references/session-cliffs.md "At most two re-verify rounds"
says  references/session-cliffs.md "Re-verify: round"
never references/session-cliffs.md "one \`reviewer\` per angle"
never references/session-cliffs.md "a \`words\` reviewer"
never references/session-cliffs.md "At most three fix checks"
never references/session-cliffs.md "A finding stays unfixed only when the adjudicator is wrong"
says  hooks/dispatch-record-gate.sh "re-verify"
# Scenario 4: the adjudicator confirms and places, finally.
says  agents/adjudicator.md "Do not run its test again"
never agents/adjudicator.md "run the reproduction"
says  agents/adjudicator.md "a path from a real production entry point"
says  agents/adjudicator.md "nobody moves a finding after you"
never agents/adjudicator.md "or that is not plain English"
never agents/adjudicator.md "each finding you could not place"
never skills/work-on/worker.md "never fixed in this PR"
never skills/work-on/foreman.md "never fixed in this PR"
never skills/work-on/foreman.md "each finding it could not place"
# Scenario 5: one brief check.
says  hooks/agent-brief-gates.sh "gate-verify-brief"
never hooks/agent-brief-gates.sh "gate-fix-evidence"
never hooks/agent-brief-gates.sh "gate-wave-brief"
never hooks/agent-brief-gates.sh "gate-brief-inference"
never hooks/agent-brief-gates.sh "gate-agent"
says  hooks/engram-protocol.sh "gate-verify-brief)"
never hooks/engram-protocol.sh "gate-fix-evidence"
never hooks/engram-protocol.sh "gate-wave-brief"
never hooks/engram-protocol.sh "gate-brief-inference"
never hooks/engram-protocol.sh "gate-agent)"
says  references/dispatch-brief.md "Claims:"
says  references/dispatch-brief.md "Re-verify: round"
says  references/gate-catalog.md "gate-verify-brief"
for doc in references/dispatch-brief.md references/gate-catalog.md README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "gate-fix-evidence"
  never "$doc" "gate-wave-brief"
  never "$doc" "gate-brief-inference"
  never "$doc" "the code outside the diff the change depends on; a brief asking for a fix"
done
# Scenario 7: the docs and pictures say the new flow.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  says  "$doc" "For each scenario it sends one verifier"
  says  "$doc" "That placement is final"
  says  "$doc" "only the claims the fix broke"
  never "$doc" "one angle each"
  never "$doc" "The foreman holds that plan against"
done
says  scripts/diagrams.py "verifier: scenario 1"
says  docs/images/review.svg "verifier: scenario 1"
says  docs/images/workflow.svg "one verifier per scenario, then the judge"
for doc in scripts/diagrams.py docs/images/review.svg docs/images/workflow.svg docs/images/day-5-workers.svg docs/explainer.html; do
  never "$doc" "reviewer: bugs"
  never "$doc" "the foreman checks it and says go"
done
# Scenario 7, the foreman's addition for issue #21: analyze-issues checks an issue and edits only what fails.
never skills/work-on/foreman.md "It rewrites each issue into its four parts"
says  skills/work-on/foreman.md "It checks each issue against its four parts"
never skills/work-on/worker.md "not yet rewritten"
# Scenario 8: the report counts agent runs, and a refused dispatch is not a run.
says  skills/work-on/worker.md "how many agents you ran"
says  skills/work-on/worker.md "dispatches.tsv"
says  skills/work-on/worker.md "not counting"
says  references/session-cliffs.md "not refused"
says  references/dispatch-brief.md "not refused"
says  skills/work-on/foreman.md "agent-run count"
# Review round 1 of issue #20: the docs say what the hooks do.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "a brief that hides what memory found"
done
says  docs/explainer.template.html "out, when it doesn't hold or is noise"
says  docs/explainer.html "out, when it doesn't hold or is noise"
for doc in scripts/diagrams.py docs/images/review.svg docs/explainer.html; do
  never "$doc" "could not be confirmed by running it"
  never "$doc" "not real, not confirmed, or not worth"
done
says  references/session-cliffs.md "the security reviewer's dispatch does not spend a round"
# Fix check 1 of issue #20: the count is of agents sent, and a declined one is in it.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "the count of agent runs it took"
  never "$doc" "the count of agents it sent"
  says  "$doc" "the number of agent dispatches it took"
done
# Fix check 2 of issue #20: the form is exact, and the refusal names it.
says  references/dispatch-brief.md "at least four words"
says  references/dispatch-brief.md "exactly \`Claims:\`"
says  hooks/engram-protocol.sh "under the first Claims: line"
says  references/gate-catalog.md "at least four words"
# Fix check 3 of issue #20: no awk interval, since the mawk on Debian 12 and Ubuntu 22.04 lacks them.
never hooks/engram-protocol.sh "{3}"
never hooks/engram-protocol.sh "{n}"
says  references/dispatch-brief.md "declined at a permission prompt"
says  references/gate-catalog.md "A dead or declined verifier still spends its round"
# 7. Issue #21: analyze-issues verifies each issue against its sources and
# changes only what fails. The per-issue brief is a checklist, a passing issue
# is untouched, size is a milestone finding, a hook guards the edit, and the
# rewrite wording is gone from every page a person or agent reads.
says  skills/analyze-issues/issue-check.md "edit only the part that fails"
says  skills/analyze-issues/issue-check.md "a verdict for each with its evidence"
says  skills/analyze-issues/issue-check.md "Every check passes: change nothing on GitHub. No edit, no comment."
says  skills/analyze-issues/issue-check.md "looked in:"
says  skills/analyze-issues/issue-check.md "fits one worker session by the Size rule"
says  skills/analyze-issues/issue-check.md "without its \"looked in:\" part fails check 3"
never skills/analyze-issues/issue-check.md "Rewrite issue #<n>"
never skills/analyze-issues/issue-check.md "Rewritten by /analyze-issues"
says  skills/analyze-issues/SKILL.md "## 2. Verify each issue, in parallel"
says  skills/analyze-issues/SKILL.md "An issue that passes every check is untouched: no edit and no comment."
says  skills/analyze-issues/SKILL.md "edits only the part that fails"
says  skills/analyze-issues/SKILL.md "a verdict per check with its evidence"
says  skills/analyze-issues/SKILL.md "does not fit one worker session by the Size rule"
never skills/analyze-issues/SKILL.md "Rewritten by /analyze-issues"
never skills/analyze-issues/SKILL.md "## 2. Rewrite each issue"
never skills/analyze-issues/SKILL.md "Check every rewrite"
says  skills/analyze-issues/milestone-check.md "6. Size:"
says  skills/analyze-issues/milestone-check.md "does not fit one worker session by the Size rule"
says  skills/analyze-issues/milestone-check.md "Nothing else is a finding: not wording, not a design you would prefer."
never skills/analyze-issues/milestone-check.md "not size"
never skills/analyze-issues/milestone-check.md "rewritten today"
says  skills/github-issues/SKILL.md "looked in:"
says  README.md "checks it against its sources"
says  README.md "fixes only the part that fails"
says  README.md "\`issue-edit-gate.py\`"
says  docs/explainer.template.html "checks it against its sources"
says  docs/explainer.template.html "fix only the part that fails"
says  docs/explainer.template.html "<code>issue-edit-gate.py</code>"
says  docs/explainer.html "<code>issue-edit-gate.py</code>"
says  scripts/diagrams.py "fixes only what fails"
says  docs/images/day-3-check.svg "fixes only what fails"
says  docs/images/workflow.svg "fixes only what fails"
says  hooks/run-tests.sh "issue-edit-gate-test.py"
# MAST-4 review F-S6: a Linear save that changes no text is not refused, so
# the rows say which Linear edits are checked.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "and every Linear edit, is checked"
  says  "$doc" "and every Linear edit of an issue's text, is checked"
done
never references/gate-catalog.md "and every Linear edit, is checked"
says  references/gate-catalog.md "and every Linear edit of an issue's text, is checked"
for doc in README.md docs/explainer.template.html docs/explainer.html scripts/diagrams.py docs/images/workflow.svg docs/images/day-3-check.svg skills/analyze-issues/SKILL.md skills/analyze-issues/issue-check.md skills/analyze-issues/milestone-check.md; do
  never "$doc" "rewrites it on GitHub"
  never "$doc" "rewrites its issue"
  never "$doc" "checks every rewrite"
  never "$doc" "every rewritten issue"
  never "$doc" "rewrote them"
  never "$doc" "Rewritten by /analyze-issues"
done
says  README.md "drops a line quoted as yours"
never README.md "drops a line you wrote"
never docs/explainer.template.html "drops a line you wrote"
never scripts/diagrams.py "What would a builder have to guess?"
never docs/images/day-3-check.svg "What would a builder have to guess?"
says  references/gate-catalog.md "hooks/issue-edit-gate.py\`"
says  references/gate-catalog.md "trusts whoever can comment on the issue"
says  README.md "three or more words in quotes, with your name on the line or on a heading above it"
says  docs/explainer.template.html "three or more words in quotes, with your name on the line or on a heading above it"
says  README.md "or adds a \`[NEEDS CLARIFICATION]\` question"
says  docs/explainer.template.html "or adds a <code>[NEEDS CLARIFICATION]</code> question"
never README.md "or carries a \`[NEEDS CLARIFICATION]\` question"
never docs/explainer.template.html "or carries a <code>[NEEDS CLARIFICATION]</code> question"
says  README.md "when it is the one speaking"
says  docs/explainer.template.html "when it is the one speaking"
never README.md "or the words \"the user\""
never docs/explainer.template.html "or the words \"the user\""
says  README.md "reads the body from \`--body-file <path>\` only"
says  docs/explainer.template.html "reads the body from <code>--body-file &lt;path&gt;</code> only"
says  skills/analyze-issues/issue-check.md "gh issue edit <n> --body-file <path>"
says  skills/analyze-issues/milestone-check.md "gh issue edit <n> --body-file <path>"
says  skills/analyze-issues/SKILL.md "gh issue edit <n> --body-file <path>"
never skills/analyze-issues/issue-check.md "--body-file - <<"
never skills/analyze-issues/milestone-check.md "--body-file - <<"
# The GitHub connector is used where it is loaded, gh is the fallback, and git and the merge queue stay off it (issue #27).
says  skills/github-issues/SKILL.md "## Which tool makes the call"
says  skills/github-issues/SKILL.md "**Commits and pushes go through git.**"
says  skills/github-issues/SKILL.md "**The merge queue goes through \`gh\`.**"
says  skills/work-on/foreman.md "That goes through \`gh api graphql\` even where the GitHub"
says  skills/github-issues/SKILL.md "\`labels\` replaces the issue's whole set"
says  skills/github-issues/SKILL.md "No single connector call says which projects an issue is in, so find them"
never skills/github-issues/SKILL.md "the run's own project, the number in its URL"
says  skills/github-issues/SKILL.md "a project under another account needs \`gh\`"
never skills/github-issues/SKILL.md "A blocked-by link and a new milestone or"
says  skills/work-on/SKILL.md "and \`gh\` is the fallback"
says  skills/analyze-issues/issue-check.md "send the whole body with \`issue_write\` (method \`update\`)"
says  skills/analyze-issues/milestone-check.md "send the whole new body with \`issue_write\` (method \`update\`)"
says  skills/analyze-issues/SKILL.md "send the whole new body with \`issue_write\` (method \`update\`)"
says  README.md "| \`connector-commit-gate.py\` | before a GitHub connector call |"
says  docs/explainer.template.html "<tr><td><code>connector-commit-gate.py</code></td>"
never README.md "skill rewrites issues into this shape"
never docs/explainer.template.html "skill rewrites issues into this shape"

# 8. Issue #25: the README, the explainer, the reference pages and the
# pictures say what the 0.1.6 skills, agents and hooks do. Each sentence that
# was wrong is pinned with the wording it replaced; the pictures already
# matched scripts/diagrams.py and are pinned by sections 6 and 7 above. The
# foreman widened the issue by one line: the analyze-issues skill's sentence
# on who checks a worker's plan.
says  docs/explainer.template.html "whether to keep a code index in Korium (off)"
says  docs/explainer.html "whether to keep a code index in Korium (off)"
says  README.md "the judge (the \`adjudicator\` agent)"
says  references/agent-preamble.md "Read by verifier, security-reviewer, architecture-reviewer, adjudicator, diagnoser and reader"
never references/agent-preamble.md "security-reviewer, diagnoser and reader, in every repo"
says  references/work-routing.md "differs from all five"
never references/work-routing.md "differs from all four"
says  references/dispatch-brief.md "Two hooks read every"
never references/dispatch-brief.md "Three hooks read every"
says  references/dispatch-brief.md "diagnoser and adjudicator name opus; the reader names haiku"
# MAST-41: the adjudicator moved from Haiku to Opus.
never references/dispatch-brief.md "the adjudicator and reader name haiku"
never references/dispatch-brief.md "diagnoser name opus; reader names haiku"
says  references/session-cliffs.md "every sentence of it is a claim of the scenario it belongs to"
never references/session-cliffs.md "that the diff adds or edits text a customer reads in"
says  references/gate-catalog.md "hooks/prime-context.py"
says  references/gate-catalog.md "hooks/capture-finding-reminder.py"
says  references/gate-catalog.md "hooks/korium-index-on-stop.sh"
never skills/analyze-issues/SKILL.md "checked by a blind verifier before any code is written"
never skills/analyze-issues/SKILL.md "checked by the foreman"

# 9. Issue #25, verification round 1: seventeen sentences the adjudicator
# placed on the fix list, each pinned with the wording it replaced.
# The foreman reads memory first (foreman.md step 1).
says  README.md "What earlier sessions wrote down in memory first"
never README.md "Then what earlier sessions wrote down in memory"
says  docs/explainer.template.html "What earlier sessions wrote down in memory first"
never docs/explainer.template.html "Then what earlier sessions wrote down in memory"
# After a merge, the terminal starts a fresh session (foreman.md section 4).
says  README.md "in a fresh session in the terminal"
never README.md "gives that worker its next issue"
says  docs/explainer.template.html "in a fresh session in the terminal"
never docs/explainer.template.html "gives that worker its next issue"
# The worker writes no design sheet; started by the person, it says what it
# will build and waits for the go (worker.md section 5).
says  README.md "The worker tells you in a few lines what it will build"
never README.md "one-page sheet"
says  docs/explainer.template.html "The worker tells you in a few lines what it will build"
never docs/explainer.template.html "one-page sheet"
# Setup asks more than three questions in some repos (setup SKILL.md 6 and 7).
says  README.md "one or two more when it finds a folder of decision records"
never README.md "asks three questions about the repository and writes nothing"
says  docs/explainer.template.html "one or two more when it finds a folder of decision records"
never docs/explainer.template.html "asks three questions about the repository and writes nothing"
# The model option skips a helper whose file names a model (model-choice-gate.sh).
never README.md "Helpers run on the small model unless"
never docs/explainer.template.html "Helpers run on the small model unless"
# What the irreversible-action gate refuses (its header and lines 399 to 430).
says  README.md "deleting a remote branch, skipping the checks with"
never README.md "history rewrites, deleting unmerged branches"
never README.md "pushing without the push check"
says  docs/explainer.template.html "deleting a remote branch, skipping the checks with"
never docs/explainer.template.html "history rewrites, deleting unmerged branches"
never docs/explainer.template.html "pushing without the push check"
never references/gate-catalog.md "and unproven pushes"
# The push gate and the ADR gates run in part with no fact (hard-gate.sh 430, adr-sections-gate.py 45).
says  README.md "Fully on once the repository states the fact setup writes"
never README.md "On when the repository states the fact setup writes"
says  docs/explainer.template.html "Fully on once the repository states the fact setup writes"
never docs/explainer.template.html "On when the repository states the fact setup writes"
says  README.md "nothing for the secret scan and the stack checks"
never README.md "| the test command from setup (\`PROJECT_PUSH_CHECK\`) |"
says  docs/explainer.template.html "nothing for the secret scan and the stack checks"
never docs/explainer.template.html "<td>the test command from setup</td>"
# MAST-40: the ADR gates hold nothing until a folder is named; there is no docs/adr fallback.
says  README.md "nothing is held in a repository that named none"
never README.md "or \`docs/adr\` when none is named"
never README.md "a decision records folder (\`ADR_DIR\`) |"
says  docs/explainer.template.html "nothing is held in a repository that named none"
never docs/explainer.template.html "<code>docs/adr</code> when none is named"
never docs/explainer.template.html "<td>a decision records folder</td>"
says  references/gate-catalog.md "with no folder named it holds nothing"
# The code index gates refuse before the first lookup and a whole-file read (engram-protocol.sh).
says  README.md "until the index is asked"
never README.md "already answered; otherwise nothing"
says  docs/explainer.template.html "until the index is asked"
never docs/explainer.template.html "already answered; otherwise nothing"
# An unsettled security finding reaches the user through the foreman (issue #29 changed this from "goes to the foreman").
says  docs/explainer.template.html "goes to you the same way"
says  scripts/diagrams.py "goes to you"
says  docs/images/review.svg "goes to you"
# The worker box numbers six steps with no gap, and has no plan step.
says  scripts/diagrams.py "6. one pull request"
never scripts/diagrams.py "7. one pull request"
never docs/images/workflow.svg "7. one pull request"
never scripts/diagrams.py "a change and a test per scenario"
says  docs/explainer.template.html "the same six steps"
never docs/explainer.template.html "the same eight steps"
# The catalog says which install options switch its gates on (run.sh, agent-brief-gates.sh).
says  references/gate-catalog.md "runs only with the Korium memory install option on"
says  references/gate-catalog.md "since the previous Stop"
never references/gate-catalog.md "since the user last spoke"
says  references/gate-catalog.md "with the Korium memory option on, prints"
says  references/gate-catalog.md "or a scratch file under"
for doc in docs/explainer.html docs/images/review.svg docs/images/workflow.svg; do
  never "$doc" "the same nine steps"
done

# 10. Issue #25, re-verify round 1: five sentences the adjudicator placed.
# The brief check runs outside run.sh, so the Korium option does not switch it off.
says  references/gate-catalog.md "except \`gate-verify-brief\`"
never references/gate-catalog.md "none of these refuses anything"
# A model named on the call is checked whatever the agent's file says.
says  README.md "a call that names no model is not asked for a helper whose file in the project's or the plugin's agents folder names one"
never README.md "A helper with no model in its own file"
says  docs/explainer.template.html "a call that names no model is not asked for a helper whose file in the project's or the plugin's agents folder names one"
never docs/explainer.template.html "A helper with no model in its own file"
says  references/gate-catalog.md "are not covered when the call names no model"
says  references/dispatch-brief.md "Not covered when the call names no model"
# A signed-out korium-cli refuses every grep until the index is asked.
says  README.md "every grep while korium-cli is signed out"
says  docs/explainer.template.html "every grep while korium-cli is signed out"
# The wiki refresh has no docs/adr fallback.
says  README.md "the refresh only with"
says  docs/explainer.template.html "the refresh only with"
# Setup asks three questions when a memory is already connected (four with the
# tracker question, MAST-1).
says  README.md "or three when a memory is already connected"
says  docs/explainer.template.html "or three when a memory is already connected"

# 11. Issue #29: nobody files work from a review. Robert, October 28, 2026:
# "Why are you filing anything?", "No means don't build it." Then, November
# 12, 2026, on the extras the judge and the worker find: "If an Extra is
# scored 8 or more we fix it now. If an extra is under 8 we drop it. They're
# both right in the wrong way". So 8 or more is fixed in the same PR and
# under 8 is dropped, never brought to the person and never filed.
says  skills/work-on/foreman.md "What the product does, what it says, what it charges, and who may do what are the person's to decide"
says  skills/work-on/foreman.md "one question at a time; never fill the gap yourself"
never skills/work-on/foreman.md "**Proceed**"
never skills/work-on/foreman.md "This is the only issue a foreman files"
says  skills/work-on/foreman.md "sessions alive, the ones waiting for the merge queue"
says  skills/work-on/foreman.md "Some things are not yours to settle and go to the person as they stand"
says  skills/work-on/foreman.md "and file no issue."
never skills/work-on/foreman.md "file no issue except"
never skills/work-on/foreman.md "answer it from the sources above, in order, with the line quoted, or ask the user"
never skills/work-on/foreman.md "tell the worker to fix it, file it or leave it"
never skills/work-on/foreman.md "a finding it placed as a new issue is filed"
never agents/adjudicator.md "the worker decides whether it reaches the person"
says  agents/adjudicator.md "**Extras**"
never agents/adjudicator.md "**Seen, not done**"
never agents/adjudicator.md "the fix you propose"
never agents/adjudicator.md "**New issue**"
never agents/adjudicator.md "the worker files a new issue"
never agents/adjudicator.md "goes on the New issue list"
says  agents/verifier.md "Nothing else is a claim"
says  skills/work-on/worker.md "An extra that scores 8 or more is fixed in this PR, test first when it is a bug"
says  skills/work-on/worker.md "One that scores under 8 is dropped: you bring it to no one"
never skills/work-on/worker.md "Then the extras you are bringing"
never skills/work-on/worker.md "Bring them the rest"
never skills/work-on/worker.md "is filed, blocked by this issue"
never references/session-cliffs.md "fix none of them here and file none"
says  references/session-cliffs.md "Log nothing and file nothing"
never references/session-cliffs.md "File each finding on its New issue list"
never skills/github-issues/SKILL.md "by answering \"fix later\""
never skills/github-issues/SKILL.md "checked by a blind verifier"
never skills/github-issues/SKILL.md "checked by the foreman"
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  says  "$doc" "nobody files anything"
  never "$doc" "fix now, fix later, or proceed"
  says  "$doc" "No issue is ever filed from a review"
  says  "$doc" "The foreman decides how the work runs"
  never "$doc" "or filed as a new issue"
  never "$doc" "a follow-up that waited on this one first"
  never "$doc" "answers with the line quoted. Only when nothing settles it"
done
says  scripts/diagrams.py "a high score is fixed in this PR"
never docs/images/review.svg "fix later"
never docs/images/review.svg "seen, not done"
never docs/images/review.svg "reproduction"
never docs/images/review.svg "new issues to file"
says  docs/images/day-6-coffee.svg "relays your earlier answer"
never docs/images/day-6-coffee.svg "answers from the sources"
never docs/images/workflow.svg "the extras each worker brings"
never README.md "seen, not done"
never docs/explainer.template.html "seen, not done"

# 12. Masthead issue #31: the foreman and worker speak in a plain voice, say
# what matters and leave the how to the session, never set a reply format,
# and never show the person effort levels or a whole-milestone table. Robert,
# October 28, 2026: "the foreman must not override the style a user set,
# period", "#3333 high means nothing", "this is what we need".
says  skills/work-on/foreman.md "How you talk to the person is set by their own instructions and output style"
says  skills/work-on/foreman.md "Nothing here fixes a format, a shape or a batch size for a reply"
says  skills/work-on/foreman.md "say in one sentence what you are about to do and ask how many workers"
says  skills/work-on/foreman.md "so do not show it to them"
says  skills/work-on/foreman.md "how far the queue of issues with no open question runs behind them"
says  skills/work-on/foreman.md "go to the person as they stand, one at a time"
never skills/work-on/foreman.md "numbered line"
never skills/work-on/foreman.md "each issue's effort level with a one-clause reason"
never skills/work-on/foreman.md "give the user one plan, as a table"
says  skills/work-on/worker.md "How you talk to the person is set by their own instructions and output style"
says  skills/work-on/worker.md "Time matters. Do not spend time that can be avoided"
never skills/work-on/worker.md "numbered lines"
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  says  "$doc" "asks how many workers"
  says  "$doc" "one item at a time"
  never "$doc" "hands you one table"
  never "$doc" "numbered line"
done
# Issue #39: a screen starts from the template its accepted mockup page became,
# and review-design asks about each undrawn state before a page becomes one.
says  skills/work-on/worker.md "starts from the template its mockup page became"
says  skills/work-on/worker.md "change none of its words or layout"
says  skills/work-on/worker.md "is a question, not a redraw"
says  skills/work-on/foreman.md "the templates the screens became"
says  skills/review-design/SKILL.md "name each state it does not draw (empty, error, refused) and ask the user"
says  skills/review-design/SKILL.md "The PR body lists each page and the template file it became"
says  skills/work-on/foreman.md "the review-design PR lists them"
never scripts/diagrams.py "the foreman's plan, one table"
never docs/images/day-4-plan.svg "effort"
# Issue #9: step 10 of Opening a PR hands the remote branch to the user,
# since the irreversible-action gate refuses every way a session deletes one.
says  references/session-cliffs.md "delete the branch locally, and name the remote branch for the user to delete"
never references/session-cliffs.md "locally and on the remote"
never references/session-cliffs.md "push origin --delete"
never references/session-cliffs.md "refs/heads"
# Issue #55: no tracked file names the removed check, its setting, its script or
# the library it needed. The words are split so this file names none of them.
named="$(git -C "$ROOT" grep -il -w -e "abil""ities" -e "PROJECT_ABIL""ITIES" -e "Py""YAML" -- .)"
case $? in
  1) pass=$((pass + 1)) ;;
  *) fail=$((fail + 1)); printf 'FAIL these still name the removed check: %s\n' "$named" ;;
esac

# Linear issue MAST-1: a repository says its issues live in GitHub or Linear,
# never both, and every skill that touches an issue follows that one answer.
says  skills/setup/SKILL.md "Where do this repository's issues live: GitHub or Linear?"
says  skills/setup/SKILL.md '"ISSUE_TRACKER": "linear"'
says  skills/setup/SKILL.md '"LINEAR_TEAM_KEY"'
says  skills/setup/SKILL.md "never both"
# Review fixes 1 and 3: one answer in one file, written where skills read it.
says  skills/setup/SKILL.md "also remove both from settings.local.json"
says  skills/setup/SKILL.md "leave the shared file alone"
says  skills/setup/SKILL.md "run \`/masthead:setup\` from the repository's main checkout"
says  skills/setup/SKILL.md "It needs to know five things about this repository"
never skills/setup/SKILL.md "It needs to know four things about this repository"
never skills/setup/SKILL.md "It needs to know three things about this repository"
never skills/setup/SKILL.md "Three short questions"
says  skills/github-issues/SKILL.md "project_fact.py --tracker"
says  skills/github-issues/SKILL.md "never look in GitHub issues"
says  skills/github-issues/SKILL.md "Masthead cannot work Linear issues yet"
never skills/github-issues/SKILL.md "# GitHub issues GitHub is the tracker."
for skill in skills/work-on/SKILL.md skills/analyze-issues/SKILL.md skills/review-design/SKILL.md; do
  says  "$skill" "project_fact.py --tracker"
  says  "$skill" "Masthead cannot work Linear issues yet"
done
says  README.md "whether its issues live in GitHub or Linear"
never README.md "asks three questions about the repository"
says  docs/explainer.template.html "whether its issues live in GitHub or Linear"
never docs/explainer.template.html "asks three questions about the repository"

# Linear issue MAST-2: the linear-issues skill says how work is laid out in
# Linear and names the Linear call for each action github-issues names.
L=skills/linear-issues/SKILL.md
# Scenario 1: the layout.
says  "$L" "The project description is the whole brief"
says  "$L" "Four parts, in this order"
for part in "**Why:**" "**Scenarios:**" "**Out of scope:**" "**Questions:**"; do
  says  "$L" "$part"
done
says  "$L" "Order lives in the issues, through blocked-by links"
says  "$L" "Milestones only where a project has real stages"
# Scenario 2: one Linear call for each action in the github-issues table.
says  "$L" "| Read an issue with its comments | \`gh issue view <n> --comments\` | \`get_issue\` with \`id\` the key, then \`list_comments\`"
says  "$L" "| Search | \`gh issue list --search \"<words>\" --state all\` | \`list_issues\` with \`query\`"
says  "$L" "| Create | \`gh issue create\` | \`save_issue\` with no \`id\`"
says  "$L" "| Edit the body | \`gh issue edit <n> --body-file <path>\` | \`get_issue\` first, then \`save_issue\` with \`id\` and \`patch\`"
says  "$L" "| Set the status | \`set-status.sh <n> \"<Status>\"\` | \`save_issue\` with \`id\` and \`state\`"
says  "$L" "| Add a blocked-by link | \`gh api .../dependencies/blocked_by\` | \`save_issue\` with \`id\` the waiting issue and \`blockedBy\`"
says  "$L" "| Add a sub-issue | \`gh api .../sub_issues\` | \`save_issue\` with \`id\` the child and \`parentId\`"
says  "$L" "| Comment | \`gh issue comment <n>\` | \`save_comment\` with \`issueId\`"
says  "$L" "| List what an issue blocks | \`gh api .../dependencies/blocking\` | \`get_issue\` with \`includeRelations\` true; the answer's \`relations.blocks\`"
# Scenario 3: an open question is the Needs Human status, not a label.
says  "$L" "An issue with an open question has the status Needs Human**, not a label"
never "$L" "needs-decision"
never "$L" "parked"
# Scenario 4: a GitHub repository is sent to github-issues, which still answers.
says  "$L" "project_fact.py --tracker"
says  "$L" "On \`github\`, this skill does not apply: read the \`github-issues\` skill instead"
says  skills/github-issues/SKILL.md "read the \`linear-issues\` skill instead of this one"
says  README.md "\`linear-issues\` (the same for Linear)"

# Linear issue MAST-3: /work-on works one Linear issue, from branch to merged PR.
W=skills/work-on/worker.md
# Scenario 1: a Linear key makes a worker, and "dispatched" a dispatched one.
says  skills/work-on/SKILL.md "**A Linear key** such as \`KOR-12\`"
says  skills/work-on/SKILL.md "\`KOR-12 dispatched\` makes a dispatched worker, the same as \`#1418 dispatched\`"
says  skills/work-on/SKILL.md "never read as a project or milestone name"
# Review fix: a team key may hold digits, such as K8S, as project_fact.py accepts.
says  skills/work-on/SKILL.md "letters and digits, such as \`K8S-12\`"
never skills/work-on/SKILL.md "the team's letters, a hyphen, a number"
says  "$W" "## On Linear"
# Scenario 2: the issue with every comment, its parent, and the project description as the brief.
says  "$W" "\`get_issue\` with \`id\` the key, then \`list_comments\` with \`issueId\` the key"
says  "$W" "its parent (\`parentId\`) the same way"
says  "$W" "the Linear project's description is the brief, in place of the project README"
# Scenario 3: worktree KOR-12-issue, branch named by Linear and holding the key.
says  "$W" "the worktree for KOR-12 is \`KOR-12-issue\`"
says  "$W" "the branch is the one \`get_issue\` returns as \`gitBranchName\`"
says  "$W" "\`git switch -c <gitBranchName>\`, then \`git push -u origin <gitBranchName>\`"
says  "$W" "never \`gh issue develop\`"
# Scenario 4: In Progress through the Linear connector, never set-status.sh.
says  "$W" "\`save_issue\` with \`id\` the key and \`state\` \`In Progress\`"
says  "$W" "never \`set-status.sh\`, which knows only GitHub projects"
# Scenario 5: the PR body says Fixes KOR-12, and merging moves it to Done.
says  references/session-cliffs.md "\`Fixes <key>\`, such as \`Fixes KOR-12\`, when the issue lives in Linear"
says  "$W" "the PR body says \`Fixes KOR-12\`"
says  "$W" "set \`In Review\` the same way once the PR is open"
says  "$W" "check its status reads Done, and set it with \`save_issue\` if not"
# Scenario 6: a question nothing answers sets Needs Human until the answer comes.
says  "$W" "set the issue's status to \`Needs Human\` with \`save_issue\` before you ask"
says  "$W" "put the answer on the issue as a comment in the words it came in, and set the status back to \`In Progress\`"
# Scenario 7: a GitHub repository works as today; the GitHub steps stand unchanged.
says  "$W" "gh issue develop 1418 --name <user>/1418-<short-slug> --base main"
says  "$W" "Work in a worktree named after the issue, so #1418 is \`1418-issue\`."
says  "$W" "Status to In Progress with \`\${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh\` unless a foreman already did."
says  "$W" "set the Status to In Review with \`set-status.sh\`"
says  "$W" "On a repository whose issues live on GitHub, none of this section applies"
says  skills/work-on/SKILL.md "- **\`#1418\`**: you are the **worker** for that issue"
says  references/session-cliffs.md "\`Fixes #<issue>\`"
says  README.md "\`/work-on KOR-12\`"
says  docs/explainer.template.html "<code>/work-on KOR-12</code>"
says  docs/explainer.html "<code>/work-on KOR-12</code>"

# Linear issue MAST-5: /analyze-issues and /review-design read and fix Linear issues.
A=skills/analyze-issues/SKILL.md
IC=skills/analyze-issues/issue-check.md
MC=skills/analyze-issues/milestone-check.md
RD=skills/review-design/SKILL.md
for f in "$A" "$IC" "$MC" "$RD"; do
  says  "$f" "## On Linear"
  says  "$f" "On a repository whose issues live on GitHub, none of this section applies"
done
# Scenario 1: each issue is read with every comment and the project description,
# and checked against the same four parts and Size rule.
says  "$A" "find the project's open issues with \`list_issues\` with \`project\` the project name"
says  "$IC" "the issue with every comment (\`get_issue\` with \`id\` <key>, then \`list_comments\` with \`issueId\` <key>)"
says  "$IC" "the project description (\`get_project\` with \`query\` the project name), which is the brief in place of the project README"
says  "$A" "checks the same four parts and the same Size rule"
# Scenario 2: the fix edits the Linear description and keeps every line the user said.
says  "$IC" "edit only the failing part with \`save_issue\` with \`id\` <key> and \`patch\`, after reading the issue with \`get_issue\` in this session"
says  "$A" "refuses a Linear edit that drops a line quoted as the user's"
says  "$MC" "fix it with \`save_issue\` with \`id\` the key and \`patch\`, after reading the issue with \`get_issue\`"
# Scenario 3: an open question sets the status Needs Human, not a label.
says  "$A" "sets the issue's status to \`Needs Human\` with \`save_issue\`, never a label"
says  "$IC" "set the issue's status to \`Needs Human\` with \`save_issue\` instead of adding a label"
says  "$A" "sets the status back to \`Todo\` once no question is left"
# Scenario 4: a split makes Linear sub-issues in the same project.
says  "$IC" "each part a sub-issue with \`save_issue\` with \`parentId\` <key>, in the same project"
says  "$A" "each part a Linear sub-issue in the same project"
# Scenario 5: a project with no milestones is checked as one set.
says  "$MC" "A project with no milestones is checked as one set: every open issue of the project"
says  "$A" "A project with no milestones is checked as one set"
says  "$MC" "duplicates, contradictions, gaps and order"
# Scenario 6: /review-design finds and fixes Linear issues that quote a changed line.
says  "$RD" "the Linear projects whose description names the decision record"
says  "$RD" "\`list_issues\` with \`project\` each of those projects"
says  "$RD" "fix each stale issue with \`save_issue\` with \`id\` the key and \`patch\`, after reading it with \`get_issue\`"
# Scenario 7: on GitHub, the steps stand as written.
says  "$A" "On \`github\`, every \`gh\` step below"
says  "$A" "adds the \`needs-decision\` label"
says  "$IC" "with every comment (\`gh issue view <n> --comments\`), the project README"
says  "$IC" "Add the needs-decision label when a question is open"
says  "$MC" "(\`gh issue list --milestone \"<title>\"\`, then \`gh issue view <n> --comments\`)"
says  "$RD" "\`gh issue edit <n> --body-file <path>\`"
# Review S2-1: a Linear question names the project description rule, and the
# edit line says the check refuses a question without its "looked in:" part.
says  "$IC" "<project description rule>"
says  "$IC" "or a question without its \"looked in:\" part naming the decision record, the project description rule and the Korium query"
# Review S5-1: the whole-set check reads each issue's blocked-by links.
says  "$MC" "\`get_issue\` with \`includeRelations\` true"

# Linear issue MAST-6: the foreman runs a Linear project.
F=skills/work-on/foreman.md
says  "$F" "## On Linear"
# Scenario 1: the project description is the brief, every issue with its
# comments, ordered by Linear blocked-by links.
says  "$F" "read the project description with \`get_project\` with \`query\` the project name, in place of the project README"
says  "$F" "\`list_issues\` with \`project\` the project name, then each issue with \`get_issue\` with \`id\` the key and \`includeRelations\` true, and \`list_comments\` with \`issueId\` the key"
says  "$F" "order them by \`relations.blockedBy\`"
# Scenario 2: an issue in Needs Human is not ready.
says  "$F" "an issue in \`Needs Human\` is not ready, and no worker starts on it"
# Scenario 3: the answer goes on the issue as a comment, and the issue leaves Needs Human.
says  "$F" "goes on the issue as a comment with \`save_comment\`, in the person's words"
says  "$F" "the issue moves to \`Todo\` with \`save_issue\` once no \`[NEEDS CLARIFICATION]\` line is left"
# Re-verify 2: a question answered before a worker starts is taken out of the
# body, so the issue can leave Needs Human.
says  "$F" "the answered \`[NEEDS CLARIFICATION]\` line is taken out of the body with \`save_issue\` and \`patch\` after reading it with \`get_issue\`"
# Review S3-answer: on a worker's question the worker posts the answer and
# sets In Progress, so the foreman's helper posts no second comment and
# never moves a building issue to Todo.
says  "$F" "the worker puts the answer on the issue and sets it back to \`In Progress\` itself"
says  "$F" "posts no comment and changes no status"
never "$F" "sets the status to \`Todo\` with \`save_issue\` once no"
# Review S7-readme-gate: on Linear a worker's report quotes the project description.
says  "$F" "a worker's report quotes a line from the project description, in place of the project README"
# Scenario 4: a park moves the issue to Needs Human with one comment.
says  "$F" "a second failure sets the issue's status to \`Needs Human\` with \`save_issue\` and adds one comment saying what happened, never a \`parked\` label"
# Scenario 5 is gone: no issue is filed from a review, on Linear either (see 11).
never "$F" "**Fix later.**"
# Scenario 6: merge sets Done up the chain and lists what it blocked from Linear.
says  "$F" "set the merged issue to \`Done\` with \`save_issue\` if the \`Fixes\` line did not, then each parent up the chain with no open sub-issue left"
says  "$F" "list what it blocked from \`get_issue\` with \`includeRelations\` true, its \`relations.blocks\`"
# Scenario 7: the merge queue stays on GitHub.
says  "$F" "Queuing the PR is unchanged: it goes to GitHub's merge queue"
# Workers start on the Linear key and the status is set through Linear.
says  "$F" "\`/work-on KOR-12 dispatched\`"
says  "$F" "\`--name \"KOR-12-issue\"\`"
says  "$F" "\`save_issue\` with \`id\` the key and \`state\` \`In Progress\`, never \`set-status.sh\`"
# Scenario 8: a GitHub project runs as today.
says  "$F" "On a repository whose issues live on GitHub, none of this section applies"
says  "$F" "gh issue edit <n> --add-label parked"
says  "$F" "gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocking"
says  "$F" "\`\${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh <n> \"In Progress\"\`"
says  "$F" "claude --bg --model opus --effort <level> --name \"<n>-issue\" \"/work-on #<n> dispatched\""

# Review S1-pagination: every page of issues and comments is read.
says  "$F" "while the answer says \`hasNextPage\` true, call again with its \`cursor\` until no page is left"

# Review helpers start no database and no container, copy no code tree and
# compile nothing. Robert's decisions on 2026-11-11, word for word: "Yes, bar
# them", then "Yes, bar that too", then "ship text only": the rules are stated
# to each helper and no hook enforces them, so no sentence may say one does.
for helper in agents/verifier.md agents/security-reviewer.md agents/adjudicator.md; do
  says  "$helper" "never start, restart or migrate a database, a cache such as Valkey, Docker, Colima or any container"
  says  "$helper" "never source or run a script the repo uses to bring one up"
  says  "$helper" "never run a test that needs one"
  says  "$helper" "never copy, clone, archive or check out the repository, or a large part of it"
  says  "$helper" "never compile"
  says  "$helper" "No hook enforces"
  never "$helper" "throwaway worktree"
  never "$helper" "bash-scope-reviewer.sh\` refuses"
  never "$helper" "PROJECT_SUBSTRATE_SCRIPTS"
  never "$helper" "ensure-substrates"
done
says  agents/verifier.md "## What you never run"
says  agents/verifier.md "You read the code where it is, in the worker's own tree"
says  agents/verifier.md "no \`mix compile\`, \`mix deps.get\`, \`mix deps.compile\`, \`swift build\` or \`cargo build\`"
says  agents/verifier.md "run the tests that need no database"
says  agents/verifier.md "when that changes no tracked file"
says  agents/verifier.md "A small file of your own (a probe script, a test file)"
says  agents/verifier.md "Two kinds of claim you answer a third way"
says  agents/verifier.md "not proven here, needs the database run"
says  agents/verifier.md "a planted fault in a private copy"
says  agents/verifier.md "When only a run of the tests without the change could show that, it is not proven here"
says  agents/security-reviewer.md "as the verifier's \"Where to run a test\" says"
never agents/security-reviewer.md "Running a claim"
says  agents/security-reviewer.md "not proven here, needs the database run"
says  agents/security-reviewer.md "are the two exceptions"
says  agents/adjudicator.md "**Not proven here**"
says  agents/adjudicator.md "is not a finding and is never thrown out"
says  agents/adjudicator.md "a database or a private copy"
says  references/dispatch-brief.md "A review helper starts no database and copies no code tree"
says  references/dispatch-brief.md "never ask a helper to run a database test or to prove a claim by breaking the code in a copy"
says  references/dispatch-brief.md "Nothing enforces this"
never references/dispatch-brief.md "ensure-substrates"
says  references/session-cliffs.md "lists as not proven here"
# Round 1 fix F1: the network hook already refuses two of the copy commands for two of the helpers, and the text says so.
says  agents/verifier.md "except that the network hook, while it is on and the machine has jq, refuses \`git clone\` and \`rsync\`"
says  agents/security-reviewer.md "except that the network hook, while it is on and the machine has jq, refuses \`git clone\` and \`rsync\`"
says  references/dispatch-brief.md "except that the network hook, while it is on and the machine has jq, refuses a verifier's or a security reviewer's \`git clone\` and \`rsync\`"
never references/dispatch-brief.md "no hook checks it"
# Round 1 fix F2: no run takes the change out, so a claim that needed a private copy is settled by nobody and is listed as not proven.
says  references/session-cliffs.md "This run settles each claim the verdict lists as not proven here for want of a database"
says  references/session-cliffs.md "every claim that needed a private copy"
says  references/dispatch-brief.md "no run settles that one, so it goes on your did-not-prove list"
says  agents/verifier.md "No run settles the second"
never agents/verifier.md "Say with each what the worker's run"
never agents/security-reviewer.md "each with what the worker's run has to show"
says  hooks/review-write-fence.py "never a copy of the tree"
never hooks/review-write-fence.py "make a throwaway worktree"
says  hooks/bash-scope-reviewer.sh 'REVIEWER_AGENTS="verifier|security-reviewer|architecture-reviewer"'
never hooks/bash-scope-reviewer.sh "DATABASE_BARRED_AGENTS"
for doc in README.md docs/explainer.template.html docs/explainer.html references/gate-catalog.md; do
  never "$doc" "a scratch copy under"
  never "$doc" "PROJECT_SUBSTRATE_SCRIPTS"
done
# The blind reviewer confirms the scenario's test and the bug's test, and stops
# there. Robert's rulings on 2026-11-11, word for word. On what the blind
# reviewer is for: "6 relates to 1&2", where line 1 of the floor is "Every
# scenario in the issue, written given, when, then, has a test that passes",
# line 2 is "A bug gets its test first, then the fix" and line 6 is "A blind
# reviewer has confirmed lines 1 and 2". On the rest of the review: "I mean all
# 3 choices of what we do today is correct, what you proposed is incorrect", so
# one blind pass, up to two re-checks, the judge on every round and a finding
# fixed test first all stay.
# 1. The verifier's job is two questions per scenario. The first keeps the
# probing: the parent session found on 2026-11-11 that "two questions and no
# others" cut a safeguard Robert never gave up. His yardstick for a cut, word
# for word: "could this catch a bug a customer would hit? If yes, it stays,
# however slow" (his answer: "yes that's exactly right"). Trying each Then in
# the states production can reach can catch such a bug, so it stays.
says  agents/verifier.md "You take one scenario's claims and try to make each one false"
says  agents/verifier.md "it needs to be adversarial and assume the architecture and code is shit and prove it's right by looking. It's not about always finding something."
says  agents/verifier.md "A claim you could not make false, with the run that shows it, is as much your result as one you could"
says  agents/verifier.md "You answer two questions about the scenario. You are not a general review of the code"
says  agents/verifier.md "Is each Then true in every state production can reach, and does a test exist that really proves it and passes"
says  agents/verifier.md "## The first question: is each Then true, and does a test prove it"
says  agents/verifier.md "Before you build a state to test, find the production code that reaches it from a real entry point"
says  agents/verifier.md "The author's claims are suspect until you prove otherwise"
says  agents/verifier.md "does the code make each Then true in each state the Given allows"
says  agents/verifier.md "For each claim, try the states production can reach: the ordinary case, empty or missing input, the same call arriving twice where production really repeats it (for example a retry, a webhook, a job), and data left from before the change"
says  agents/verifier.md "Prove each answer with a test that reaches the state the way production does, through a real entry point"
says  agents/verifier.md "A Then that is false in a state production can reach is a no, whether or not a test exists for the ordinary case"
says  agents/verifier.md "true in every state"
says  agents/verifier.md '"Could happen" and "looks risky" are not states'
says  agents/verifier.md "If you are not sure a claim is false, it is not false; never return one to show you found something"
says  agents/verifier.md "## Ways to look"
says  agents/verifier.md "These are ways to look at the scenario's own claims, not a list to fill"
says  agents/verifier.md "ask what is left if it fails halfway or is retried"
says  agents/verifier.md "the other copies of that rule the change now disagrees with"
says  agents/verifier.md "an input production can send that the change does not handle"
says  agents/verifier.md "ask the code index (\`code_locate\`) before you call it new"
says  agents/verifier.md "A breach of the repository's written rules (CLAUDE.md, \`docs/conventions/\`) is a finding only when it makes one of the claims false"
says  agents/verifier.md "Quote it as a false claim"
for doc in agents/verifier.md agents/adjudicator.md references/dispatch-brief.md references/session-cliffs.md README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "and no others"
done
says  agents/verifier.md "it would fail if the behavior were missing"
says  agents/verifier.md "For a bug fix: was the test written first, and did it fail before the fix"
says  agents/verifier.md "The commit that adds the failing test comes before the commit that fixes the bug"
says  agents/verifier.md "## The second question: a bug's test came first"
says  agents/verifier.md "A Then with no test is a no"
says  agents/verifier.md 'Read the two commits with `git log` and `git show`. You check out nothing'
never agents/verifier.md "the author's claim and unproven lists"
says  references/dispatch-brief.md "It answers two questions: is each Then true in every state production can reach, and is there a test that really proves it and passes"
says  references/dispatch-brief.md "It is not a general review of the code"
says  references/dispatch-brief.md "was the test written first and did it fail before the fix"
says  references/session-cliffs.md "A verifier answers two questions: is each Then true in every state production can reach, with a test that really proves it and passes"
says  agents/adjudicator.md "is each Then true in every state production can reach, with a test that really proves it and passes"
# 2. The brief asks for no claim beyond the scenario.
never references/dispatch-brief.md "each thing the author claims works"
says  references/dispatch-brief.md "Claims: - <each Then line of the scenario> - <each sentence a customer reads that the diff adds or edits> Not proven: <list>."
says  references/dispatch-brief.md 'Bug fix: <the commit that adds the failing test, then the commit that fixes the bug>, or "not a bug fix".'
says  references/dispatch-brief.md "Add no claim of your own"
never hooks/engram-protocol.sh "what the author claims works"
says  hooks/engram-protocol.sh "List under it the scenario's Then lines and every sentence a customer reads that the change adds or edits, and no claim of your own"
never references/session-cliffs.md "what you claim works"
never references/session-cliffs.md "both lists"
says  references/session-cliffs.md "Its claims are the scenario's Then lines and nothing you add"
says  references/session-cliffs.md "A bug gets its test first: the failing test in a commit of its own, then the fix"
# 3. It flags what it notices outside the scenario in one line, and does not chase it.
says  agents/verifier.md "## Outside the scenario"
never agents/verifier.md "## Outside your two questions"
never agents/verifier.md "a write that could fail halfway, an input nobody handles"
says  agents/verifier.md "code the change did not touch, the design, style, names"
says  agents/verifier.md "Nothing else is a claim"
says  agents/verifier.md "Do not chase it"
says  agents/verifier.md 'write one line under `For the judge`, a heading of its own apart from your answers, with its `file:line` and what looks wrong, and move on'
says  agents/adjudicator.md 'A line under a verifier'"'"'s `For the judge` heading'
says  agents/adjudicator.md "Read the code from that line yourself"
says  agents/adjudicator.md "no test that passes really proves it"
says  agents/adjudicator.md "a bug fix's test did not come first"
# 4. The rest of the review is as it was, and the security reviewer keeps its own scope.
says  agents/security-reviewer.md "The verifier's two questions about its scenario are not yours"
never agents/security-reviewer.md "The verifier's limit to two questions about a scenario's test is not yours"
never agents/security-reviewer.md "Everything in the \`verifier\` agent applies"
says  agents/security-reviewer.md "You review one change for the ways it can be attacked"
says  agents/adjudicator.md "Do these six steps in this order and never skip one"
says  references/session-cliffs.md "then the \`adjudicator\` on that round's findings files as in step 3"
says  references/session-cliffs.md "in two commits of its own: a test that reproduces it and fails, then the fix"
# 5. Nothing proves a test by breaking code on purpose. Robert's ruling, word
# for word: "'Breaking the code on purpose to watch the test go red' No. that
# proves nothing". The line he accepted ("this is what I think is right, yes"):
# "The proof a test works is that it failed before the change and passes after.
# Nothing breaks code on purpose to prove a test, not once and not on every run."
says  references/session-cliffs.md "The proof a test works is that it failed before the change and passes after. Nothing breaks code on purpose to prove a test, not once and not on every run."
says  agents/verifier.md "never by taking the change out or planting a fault"
says  agents/verifier.md "The proof a test works is that it failed before the change and passes after"
never references/session-cliffs.md "To undo a mutation"
never references/session-cliffs.md "Commit before mutating"
never references/session-cliffs.md "mutated tree"
never hooks/test-commit-attribution-gate.py "mutation proof"
never hooks/test-commit-attribution-gate.py "mutate a copy"
says  hooks/test-commit-attribution-gate.py "it failed against the hook before the change and passes after"
# The pages a person reads say the same job.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  says  "$doc" "Is each Then true in every state production can reach, and does a test really prove it"
  says  "$doc" "It tries only states production can reach"
  says  "$doc" "it writes one line for the judge, with the file and line, and moves on"
  never "$doc" "what it claims works"
done
for doc in scripts/diagrams.py docs/images/review.svg docs/explainer.html; do
  never "$doc" "tries to make every claim false"
  never "$doc" "each false claim's path"
  never "$doc" "each one answers two questions about the tests"
  says  "$doc" "each one tries to make each Then false, and checks its test"
done
# Round 1 fix 1 made a sentence a customer reads need a test of its own, to
# keep "no others" true. With "no others" gone, the sentence check is as it
# was on main: what it says is what the code does, in the states tried.
never agents/verifier.md "it gets the same first question"
never agents/verifier.md "A sentence no test shows to be true is a no"
never references/dispatch-brief.md "a sentence no test shows to be true comes back as a no"
never agents/adjudicator.md "or the sentence a person reads"
never agents/adjudicator.md "or no test that passes shows it"
never agents/adjudicator.md "such as a sentence a person reads that is false or a security finding"
says  agents/adjudicator.md "A finding that a claim is false holds when it names the \`file:line\`, the state, the wrong result, and a path from a real production entry point to that state"
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "it also checks that the sentence says what the code does"
done
# Round 1 fix 2: the verifier's new text and its older "What you never run"
# text gave opposite rules for a test that should fail once the change is taken
# out. One rule now: a yes rests on what the test plainly checks or on the
# commits, and what is left is not proven here, never a yes from reading alone.
says  agents/verifier.md "you judge from what the test checks and from the commits, never by taking the change out or planting a fault"
says  agents/verifier.md "is not a yes from reading alone"
says  agents/verifier.md 'it is not proven here, as "What you never run" says'
never agents/verifier.md "you judge by reading the test and the code it reaches"
says  agents/verifier.md "Where you cannot tell from reading, it is not proven here"
# Round 1 fix 3: the security reviewer got its way of testing a claim by
# pointing at verifier sections this change removed, so it now carries those
# rules itself, word for word as they stood at ac86e48.
says  agents/security-reviewer.md "## How you test a claim"
says  agents/security-reviewer.md "find the production code that reaches it from a real entry point"
says  agents/security-reviewer.md "A state that only a test setup builds is not a finding, and will be rejected by the adjudicator"
says  agents/security-reviewer.md "the ordinary case, empty or missing input, the same call arriving twice where production really repeats it (for example a retry, a webhook, a job), and data left from before the change"
says  agents/security-reviewer.md "Prove each answer with a test that reaches the state the way production does, through a real entry point"
says  agents/security-reviewer.md '"Could happen" and "looks risky" are not states'
says  agents/security-reviewer.md "If you are not sure a claim is false, it is not false; never return one to show you found something"
says  agents/security-reviewer.md "These are ways to look at a claim, not a list to fill"
says  agents/security-reviewer.md "ask what is left if it fails halfway or is retried"
says  agents/security-reviewer.md "the other copies of that rule the change now disagrees with"
says  agents/security-reviewer.md "an input production can send that the change does not handle"
says  agents/security-reviewer.md "ask the code index (\`code_locate\`) before you call it new"
says  agents/security-reviewer.md "Comments, module docs and internal docs are not verified"
# Re-verify round 1 fix: the copy left lines out, so the security reviewer's
# scope grew. It now carries every line it took from the verifier at ac86e48,
# word for word: what counts as a claim, the stance, and how it reports.
says  agents/security-reviewer.md "A breach of the repository's written rules (CLAUDE.md, \`docs/conventions/\`) is a finding only when it makes one of the claims false"
says  agents/security-reviewer.md "it needs to be adversarial and assume the architecture and code is shit and prove it's right by looking. It's not about always finding something."
says  agents/security-reviewer.md "A claim you could not make false, with the run that shows it, is as much your result as one you could"
says  agents/security-reviewer.md "The author's claims are suspect until you prove otherwise"
says  agents/security-reviewer.md "A claim that a test covers something is false when no test fails without the change"
says  agents/security-reviewer.md "Never write that file with a shell command. If the write is refused, put the findings in your final reply and say so"
says  agents/security-reviewer.md "Quote it as a false claim"
says  agents/security-reviewer.md "Your final message is the report: each claim with its answer, false ones first"
# Linear issue MAST-39: the old copies of rules left by the move to one
# verifier per scenario are gone, and each rule is written once.
# Scenario 1: no line tells a verifier to report faults outside its claims
# (October 27 design: "anything outside the claims is a follow-up by construction").
never references/agent-preamble.md "A bug you find is reported with file:line, even outside your question"
never references/agent-preamble.md "even outside your question"
says  references/agent-preamble.md "What you do with a fault outside your question is your agent file's to say"
says  agents/diagnoser.md "A bug you find outside your case is reported with \`file:line\` too"
says  agents/verifier.md "Nothing else is a claim: a fault in code the change did not touch is not a finding"
# Scenario 2: the security reviewer's claims are the repo's security conventions,
# and nothing in its file makes the scenario's Then lines its only claims.
never agents/security-reviewer.md "Nothing else is a claim"
never agents/security-reviewer.md "are the standard"
never agents/security-reviewer.md "Then true in each state the Given allows"
says  agents/security-reviewer.md "the repository's security conventions are your claims"
says  agents/security-reviewer.md "A fault the change brings in that breaks one of your claims is a finding wherever its lines are"
# Scenario 3: the extras rule is written once, in the worker's "What done is",
# and the pre-push rule once, in step 8 of Opening a PR; every other file points.
says  skills/work-on/worker.md "An extra that scores 8 or more is fixed in this PR, test first when it is a bug"
says  skills/work-on/worker.md "One that scores under 8 is dropped: you bring it to no one"
for f in references/session-cliffs.md agents/adjudicator.md skills/work-on/foreman.md skills/github-issues/SKILL.md skills/linear-issues/SKILL.md README.md docs/explainer.template.html docs/explainer.html docs/images/review.svg; do
  never "$f" "8 or more"
  never "$f" "8 or higher"
  never "$f" "under 8"
done
says  references/session-cliffs.md "as the worker's \"What done is\" says (\`skills/work-on/worker.md\`)"
says  agents/adjudicator.md "the worker settles it as its \"What done is\" says (\`skills/work-on/worker.md\`)"
says  skills/work-on/foreman.md "settled by its worker, as \`worker.md\` **What done is** says"
says  skills/github-issues/SKILL.md "an extra is settled as the worker's \"What done is\" says"
never skills/linear-issues/SKILL.md "by answering \"fix later\""
says  skills/linear-issues/SKILL.md "an extra is settled as the worker's \"What done is\" says"
says  README.md "the rule is in \`skills/work-on/worker.md\`"
says  docs/explainer.template.html "the rule is in <code>skills/work-on/worker.md</code>"
says  docs/explainer.html "the rule is in <code>skills/work-on/worker.md</code>"
says  references/session-cliffs.md "Run it one time, after the fixes of the last verification round are in"
never skills/work-on/worker.md "Run the repo's pre-push check one time"
never skills/work-on/worker.md "Do not commit while it runs"
never skills/work-on/worker.md "Do not start it when you send out the verifiers"
never references/session-cliffs.md "Do not start the repo's pre-push check now to save time"
says  references/session-cliffs.md "Step 8 runs the pre-push check, once"
says  skills/work-on/worker.md "Its step 8 says when to run the pre-push check"
# Scenario 4: the worker reads the PR steps the hook injects, the repo's own
# lead when its session-cliffs has one (prime-context.py cliff_source).
says  skills/work-on/worker.md "prime-context.py show \"Opening a PR\""
says  skills/work-on/SKILL.md "prime-context.py show \"Opening a PR\""
never skills/work-on/worker.md "Follow **Opening a PR** in \`\${CLAUDE_PLUGIN_ROOT}/references/session-cliffs.md\`"
never skills/work-on/SKILL.md "The PR steps themselves are **Opening a PR** in"
# Scenario 5: a split does not stop a foreman run (reviews file nothing).
never skills/work-on/foreman.md "filed exceeds closed"
never skills/work-on/foreman.md "issues filed"
says  skills/work-on/foreman.md "A split is not a stop"
says  skills/work-on/foreman.md "start one worker per sub-issue, in blocked-by order"
# Scenario 6: a thrown-out finding is not saved where the worker searches.
never agents/adjudicator.md "and so does each thrown-out finding"
never agents/adjudicator.md "A thrown-out finding's memory"
says  agents/adjudicator.md "A thrown-out finding is never captured"
# Round 1 fix: a verifier's and a security reviewer's own capture holds no
# finding either, since the adjudicator may throw any of them out.
says  agents/verifier.md "Your capture holds no finding"
never agents/verifier.md "Capture it to Korium and return the thought id"
says  agents/security-reviewer.md "one short capture to Korium before you finish, holding no finding"
never agents/security-reviewer.md "and the report captured to Korium before you finish"
# Scenario 7: the foreman rules on no disagreement between review rounds.
never skills/work-on/foreman.md "a disagreement between review rounds"
never skills/work-on/foreman.md "one round placed a finding on the fix list and the next among its extras"
says  skills/work-on/foreman.md "what the second re-verify round left on the fix list"
# The retired design sheet no longer ships.
if [ -e "$ROOT/references/design-sheet.md" ]; then
  fail=$((fail + 1)); echo "FAIL references/design-sheet.md still ships"
else
  pass=$((pass + 1))
fi
# Scenario 8: the docs and option text match the code.
says  skills/work-on/worker.md "Done is four things"
never skills/work-on/worker.md "Done is three things"
never .claude-plugin/plugin.json "Subagents run on Haiku unless"
says  .claude-plugin/plugin.json "\"title\": \"Ask for a reason before a helper runs on the biggest model\""
says  .claude-plugin/plugin.json "a call that names no model is not asked for a helper whose file in the project's or the plugin's agents folder names one, or for another plugin's helper"
never .claude-plugin/plugin.json "for a helper whose own file names one"
for f in README.md docs/explainer.template.html docs/explainer.html; do
  says  "$f" "a call that names no model is not asked for a helper whose file in the project's or the plugin's agents folder names one, or for another plugin's helper"
  never "$f" "for a helper whose own file names one"
done
says  docs/explainer.html "<td><code>model-choice-gate.sh</code></td><td>Ask for a reason before a helper runs on the biggest model</td>"
never .claude-plugin/plugin.json "before a subagent runs on Opus"
says  README.md "| \`model-choice-gate.sh\` | Ask for a reason before a helper runs on the biggest model |"
never README.md "Ask for a reason before the biggest model"
says  docs/explainer.template.html "<td><code>model-choice-gate.sh</code></td><td>Ask for a reason before a helper runs on the biggest model</td>"
never hooks/run-tests.sh "nothing runs these in CI"
says  hooks/run-tests.sh "CI runs this on Linux and macOS"
never skills/work-on/SKILL.md "Nothing else in this skill or its files is checked by a hook"
says  skills/work-on/SKILL.md "\`agent-brief-gates.sh\` refuses a verifier brief with no claims list and a third re-verify round"


# MAST-30: setup finds or starts the architecture doc and records where it lives.
# Scenario 1: name the doc found, ask, record on yes.
says  skills/setup/SKILL.md 'architecture-doc.py find'
says  skills/setup/SKILL.md 'Name the file and ask: "I found `<path>`. Is this the project'"'"'s architecture doc?"'
says  skills/setup/SKILL.md 'once the doc passes, add `"ARCHITECTURE_DOC": "<path>"`'
# Scenario 2: offer a draft from the code, show it, write only on yes.
says  skills/setup/SKILL.md 'Shall I draft one from the code?'
says  skills/setup/SKILL.md 'the one module each body of data is reached through and what it hands back, the rules between the core and its extensions, and what each build ships'
says  skills/setup/SKILL.md 'Show the whole draft and ask "Shall I write this to'
says  skills/setup/SKILL.md 'Write nothing to it, and record nothing, before the person says yes.'
# Scenarios 3 and 6: the check runs on every doc before it is shown or recorded.
says  skills/setup/SKILL.md 'Either way, check it before showing it or recording it.'
says  skills/setup/SKILL.md 'architecture-doc.py check <doc> <principles file>'
says  skills/setup/SKILL.md 'For a draft you made from the template, run it as `check --draft`'
says  skills/setup/SKILL.md 'cites the project'"'"'s principles by number, such as P9, and copies none of their text'
# Re-verify round 1, finding s6.1: a doc that fails the check is never recorded.
says  skills/setup/SKILL.md 'If they say no, do not record the doc'
never skills/setup/SKILL.md 'record the doc anyway'
# Scenario 4: a repository set up before is offered the doc alone.
says  skills/setup/SKILL.md 'before and no `ARCHITECTURE_DOC` is recorded, offer the architecture doc on its own'
says  skills/setup/SKILL.md 'ask none of the other questions unless the person asks to change an answer'
# Round 1, finding s4.j1: the rerun does not ask the .gitignore question again either.
says  skills/setup/SKILL.md 'On such a run, step 9 does not ask the `.gitignore` question again'
# Round 1, finding s2.j2: a recorded doc that is no longer there is offered again, not skipped.
says  skills/setup/SKILL.md 'When `ARCHITECTURE_DOC` is recorded but `project_fact.py --architecture-doc` prints nothing, the doc has moved or gone'
# Scenario 5: the path comes from the facts reader every other fact comes from.
says  skills/setup/SKILL.md 'project_fact.py --architecture-doc'
# MAST-34: one architecture reviewer on every PR, in place of the ADR check
# nothing ran. Robert, November 14, 2026, on whether this replaces "at no other
# time": "yes it does".
# Scenario 1: one reviewer per change, sent with the first verification.
says  references/session-cliffs.md 'one `architecture-reviewer` for the whole change, never one per scenario'
says  references/session-cliffs.md 'The architecture reviewer goes out once per change: never on a re-verify round'
# Scenario 2: only the lines the change touched, the seven lenses, and what a finding names.
says  agents/architecture-reviewer.md 'name: architecture-reviewer'
says  agents/architecture-reviewer.md 'You review only the lines the change touched'
# Round 1, fix F7: what the touched lines are held to.
says  agents/architecture-reviewer.md 'Hold each touched line to the ADR'"'"'s alignment lines, the architecture doc and the principles'
for lens in 'Direction' 'One way in and out' 'Call shape' 'Seams' 'What each build carries' 'Leftovers' 'Tests and checks'; do
  says agents/architecture-reviewer.md "| $lens |"
done
says  agents/architecture-reviewer.md 'Each finding names its `file:line`, the lens, the smell, and the rule or build it breaks'
# Scenario 2a: two scores on every finding.
says  agents/architecture-reviewer.md 'a customer score from 1 to 10'
says  agents/architecture-reviewer.md 'drift, yes or no'
says  agents/architecture-reviewer.md 'does it break one of the seven rules as this project'"'"'s architecture doc states them'
# Scenario 3: blind, as the verifier is.
says  agents/architecture-reviewer.md 'You never get the author'"'"'s account of the change or another review'
says  agents/architecture-reviewer.md 'You do not search Korium'"'"'s memory'
# Re-verify round 1, fixes V1 and N2: the README promises only what the fences do.
never README.md 'None of them can reach the network'
never README.md 'None of them can edit anything'
says  README.md 'refuse the common network programs'
says  references/gate-catalog.md 'a denylist of network programs, not an allowlist'
# Re-verify round 2 (Robert, November 15): the README and catalog claim only
# the exact shapes the architecture reviewer's shell allows, and no fence they
# do not have.
never README.md 'the architecture reviewer'"'"'s shell can only read'
says  README.md 'The architecture reviewer'"'"'s shell runs only `git diff`, `git show` and `git log` with plain revisions and paths'
says  README.md 'and refuses every other command'
never references/gate-catalog.md 'refuses git'"'"'s `-O` in any spelling'
says  references/gate-catalog.md 'a wrapper it does not see through (`timeout`, `stdbuf`, `nice -n 5`, `exec -a y`, a shell'"'"'s bundled `-lc`), a git alias set with `-c`, or git run from `find -exec`, still gets through for the verifier and security reviewer (MAST-43)'
# Re-verify round 3, fixes V1 and S1, and the judge's N1: the hook-table row
# names --comments, and neither the catalog nor the README claims a refusal a
# wrapper gets past.
says  README.md '`gh issue view <n>`, bare or with `--comments` | scoped by the agent'"'"'s type |'
never references/gate-catalog.md 'refuses git'"'"'s `-O` written after git in the same command'
says  references/gate-catalog.md 'refuses git'"'"'s `-O` when git is the first word or follows a wrapper it steps over'
says  README.md 'though one run through a wrapper the fence does not see through, such as `timeout 5 curl`, still gets through (MAST-43)'
says  references/gate-catalog.md 'the `architecture-reviewer` shell to exact command shapes'
says  agents/architecture-reviewer.md 'Your shell runs only these exact commands'
never agents/architecture-reviewer.md 'with `--comments` or `--json`'
# Re-verify round 1, fix T1: the reviewer's grant is pinned whole, so any tool
# added to it fails here.
WANT_TOOLS="Read Glob Grep Bash ToolSearch Write mcp__korium__code_locate mcp__claude_ai_korium__code_locate mcp__korium__agent_capture mcp__claude_ai_korium__agent_capture mcp__Linear__get_issue mcp__Linear__list_comments mcp__linear__get_issue mcp__linear__list_comments mcp__claude_ai_Linear__get_issue mcp__claude_ai_Linear__list_comments mcp__plugin_linear_linear__get_issue mcp__plugin_linear_linear__list_comments mcp__github__issue_read mcp__claude_ai_GitHub__issue_read mcp__plugin_github_github__issue_read"
GOT_TOOLS="$(sed -n 's/^tools: //p' "$ROOT/agents/architecture-reviewer.md" | tr ',' '\n' | tr -d ' ' | sort | tr '\n' ' ')"
if [ "$GOT_TOOLS" = "$(printf '%s\n' $WANT_TOOLS | sort | tr '\n' ' ')" ]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1)); echo "FAIL agents/architecture-reviewer.md tools differ from the pinned grant: $GOT_TOOLS"
fi
# Every tool the verifier is denied, the architecture reviewer is denied too.
VERIFIER_DENY="$(sed -n 's/^disallowedTools: //p' "$ROOT/agents/verifier.md" | tr ',' '\n' | tr -d ' ')"
ARCH_DENY_ALL="$(sed -n 's/^disallowedTools: //p' "$ROOT/agents/architecture-reviewer.md" | tr ',' '\n' | tr -d ' ')"
for tool in $VERIFIER_DENY; do
  if printf '%s\n' "$ARCH_DENY_ALL" | grep -qx "$tool"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL agents/architecture-reviewer.md does not deny $tool, which the verifier denies"; fi
done
# Round 1, fix F5: the brief shape itself carries nothing of the author's account.
says  references/dispatch-brief.md 'nothing of your account of the change: no claims, no did-not-prove list, no summary'
says  references/session-cliffs.md 'the principles file and the mockup pages, and nothing of your account'
# Round 1, fix F6: the agent's own tool grant holds no memory search and no tracker write.
ARCH_TOOLS="$(sed -n 's/^tools: //p' "$ROOT/agents/architecture-reviewer.md" | tr ',' '\n' | tr -d ' ')"
ARCH_DENY="$(sed -n 's/^disallowedTools: //p' "$ROOT/agents/architecture-reviewer.md" | tr ',' '\n' | tr -d ' ')"
for tool in mcp__korium__agent_search mcp__claude_ai_korium__agent_search mcp__korium__korium_browse mcp__claude_ai_korium__korium_browse; do
  if printf '%s\n' "$ARCH_DENY" | grep -qx "$tool" && ! printf '%s\n' "$ARCH_TOOLS" | grep -qx "$tool"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1)); echo "FAIL agents/architecture-reviewer.md does not deny $tool"
  fi
done
for tool in Edit MultiEdit NotebookEdit Agent WebFetch; do
  if printf '%s\n' "$ARCH_DENY" | grep -qx "$tool"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL agents/architecture-reviewer.md does not deny $tool"; fi
done
if printf '%s\n' "$ARCH_TOOLS" | grep -E '__(save_|create_|delete_|update_|issue_write|add_|merge_|push_)' >/dev/null; then
  fail=$((fail + 1)); echo "FAIL agents/architecture-reviewer.md grants a tracker write: $(printf '%s\n' "$ARCH_TOOLS" | grep -E '__(save_|create_|delete_|update_|issue_write|add_|merge_|push_)' | tr '\n' ' ')"
else
  pass=$((pass + 1))
fi
# Scenario 4: foreman runs too.
says  references/session-cliffs.md 'in a foreman run as in one the user started'
says  agents/architecture-reviewer.md 'and in a foreman run as in one the user started'
# Scenario 5: the issue through the repository's own tracker, never the other.
says  agents/architecture-reviewer.md 'project_fact.py --tracker'
says  agents/architecture-reviewer.md '`get_issue` with `id` the key, then `list_comments`'
says  agents/architecture-reviewer.md '`issue_read`, method `get`, then method `get_comments`'
says  agents/architecture-reviewer.md 'else `gh issue view <n> --comments`'
says  agents/architecture-reviewer.md 'never fall back from one tracker to the other'
# Scenario 6: the write fence and the brief gate.
says  hooks/review-write-fence.py 'findings-architecture-reviewer'
says  references/dispatch-brief.md 'ADR alignment:'
says  references/dispatch-brief.md 'Architecture doc:'
# Scenario 7: the ADR check is gone and no file names it.
if [ -e "$ROOT/skills/work-on/adr-check.md" ]; then
  fail=$((fail + 1)); echo "FAIL skills/work-on/adr-check.md still exists; the architecture reviewer replaces it"
else
  pass=$((pass + 1))
fi
if git -C "$ROOT" grep -lF 'adr-check' -- . ':!hooks/tests/instruction-rules-test.sh' >/dev/null 2>&1; then
  fail=$((fail + 1)); echo "FAIL a file still names adr-check: $(git -C "$ROOT" grep -lF 'adr-check' -- . ':!hooks/tests/instruction-rules-test.sh' | tr '\n' ' ')"
else
  pass=$((pass + 1))
fi
# Scenario 8: with no doc recorded it still runs, on the principles alone.
says  agents/architecture-reviewer.md 'When the brief says `Architecture doc: none recorded`, you review against the principles alone'
says  references/session-cliffs.md 'whether or not the project records an architecture doc'
# Scenarios 9 to 11: the ADR check's two jobs, and a disagreement between the ADR and the mockup.
says  agents/architecture-reviewer.md 'each requirement of that part (each decision, acceptance criterion and rule) is in the code as the ADR says'
says  agents/architecture-reviewer.md 'a requirement not built is a finding'
# Round 1, fix F4: the evidence for each requirement found built.
says  agents/architecture-reviewer.md 'Quote the ADR line and give the code'"'"'s `file:line`'
says  agents/architecture-reviewer.md 'anything in the code that contradicts the mockup is a finding, with the mockup line quoted'
says  agents/architecture-reviewer.md 'report the disagreement itself as a finding for the person, quoting both'
says  agents/architecture-reviewer.md 'do not pick one to check the code against'
# Round 1, fix F3: the ADR comes as a path the reviewer can read, never a link.
says  references/dispatch-brief.md 'never a link, which the reviewer cannot open'
says  agents/architecture-reviewer.md 'that no requirement of it was checked is a finding for the person'
# Round 1, extra scored 8: the ADR check's other job, a changed line that
# contradicts any line of the ADR (Robert, November 14, "yes" to keeping both jobs).
says  agents/architecture-reviewer.md 'a changed line that contradicts any line of the ADR, such as an option it rejected, is a finding, with that line quoted'
# MAST-36: /setup brings an existing project in line with its architecture doc,
# by a targeted review or a full sweep.
# Scenario 1: setup asks, when there is code and a doc, targeted, sweep or neither.
says  skills/setup/SKILL.md '## 10. Bring the code in line with the doc'
says  skills/setup/SKILL.md 'ask whether the person wants a targeted review, a full sweep, or neither'
says  skills/setup/SKILL.md 'Ask on every run of `/masthead:setup`'
says  skills/setup/SKILL.md 'skills/setup/architecture-review.md'
says  skills/setup/architecture-review.md 'I can do a targeted review of the parts you name, or a full sweep of the whole codebase, or neither'
says  skills/setup/architecture-review.md '`parts` exits 3 when it holds none, and then you say nothing of a review'
# Scenarios 2 and 3: the named parts, or everything, through the same reviewer and lenses.
says  skills/setup/architecture-review.md 'Only the code under what they named is reviewed'
says  skills/setup/architecture-review.md 'every code file in the repository is reviewed'
says  skills/setup/architecture-review.md 'the same agent and the same seven lenses and two scores every pull request gets: there is no second set'
for family in boundaries calls-seams builds-upkeep; do
  says skills/setup/architecture-review.md "| $family |"
done
says  agents/architecture-reviewer.md '## A review of existing code'
says  agents/architecture-reviewer.md 'Your brief then has a `Sweep:` line in place of a diff'
says  agents/architecture-reviewer.md '`Lenses:` names the ones you hold the batch to'
says  references/dispatch-brief.md 'This is an architecture review of existing code; you change no code.'
says  references/dispatch-brief.md 'findings-architecture-reviewer-sweep-<batch id>-<family>.json'
# Scenario 4: judged by reading the code, both scores, kept or dropped as project rule 5 says.
says  agents/adjudicator.md 'This is a judging job for a review of existing code'
says  references/dispatch-brief.md 'This is a judging job for a review of existing code; you change no code.'
says  agents/adjudicator.md 'Read the code at the finding'"'"'s `file:line`'
says  agents/adjudicator.md 'customer, 1 to 10'
says  agents/adjudicator.md 'drift, yes only when it breaks one of the seven rules as the architecture doc states them'
says  agents/adjudicator.md 'that is broken today'
says  agents/adjudicator.md 'that makes a build the doc names behave wrongly'
says  agents/adjudicator.md 'A build the doc does not name is no reason to keep it'
says  agents/adjudicator.md 'Drop design cost with no drift'
# Scenario 5: one row per cause, before anything is filed.
says  agents/adjudicator.md 'Findings that one change would fix share a cause'
says  skills/setup/architecture-review.md 'one row per cause, before anything is filed'
# Scenario 6: one issue per approved cause in the project's tracker, quoting the doc, a scenario per build.
says  skills/setup/architecture-review.md 'project_fact.py --tracker'
says  skills/setup/architecture-review.md 'Each approved cause is one issue, never one per finding'
says  skills/setup/architecture-review.md 'one for each build the doc names'
says  skills/setup/architecture-review.md 'quoted word for word from `rules <doc>`'
# Scenario 7: no to every cause, nothing filed.
says  skills/setup/architecture-review.md 'On none: say "Nothing filed," and end'
says  skills/setup/architecture-review.md 'You file only what the person names'
# Scenario 8: one session's share, and what was left unreviewed.
says  skills/setup/architecture-review.md 'exit 6 means this session has reviewed its share'
says  skills/setup/architecture-review.md 'say which parts were not reviewed (`left`)'
says  agents/architecture-reviewer.md 'so the session that sent you keeps its room for the next batch'
# MAST-36 round 1, F-4: every one of the seven lenses goes to a reviewer, by name.
for lens in "Direction" "One way in and out" "Call shape" "Seams" "What each build carries" "Leftovers" "Tests and checks"; do
  if sed -n '/^| Family | Lenses |$/,/^$/p' "$ROOT/skills/setup/architecture-review.md" | grep -qF -- "$lens"; then
    pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL skills/setup/architecture-review.md's family table leaves out the lens: $lens"; fi
  if grep '^Lenses: ' "$ROOT/references/dispatch-brief.md" | grep -qF -- "$lens"; then
    pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL references/dispatch-brief.md's Lenses: line leaves out the lens: $lens"; fi
done
# F-5: a new review over a part-done one replaces it, on purpose.
says  skills/setup/architecture-review.md 'run `plan` with `--fresh`'
# F-6: a principle counts through the doc's rules, and design cost alone is dropped even when it quotes one.
never agents/adjudicator.md 'that breaks a principle the brief'"'"'s principles file numbers'
says  agents/adjudicator.md 'design cost alone is dropped even when it quotes a principle'
# F-8: a doc that names no build still gets a scenario for each build.
says  skills/setup/architecture-review.md 'When `builds` prints nothing, ask the person which builds the project ships'
# F-10: the judge gets every batch reviewed and not judged, from any run.
says  skills/setup/architecture-review.md 'findings --ledger <L>'
says  skills/setup/architecture-review.md 'judged --ledger <L>'
# F-2 and F-3: the reviewer gets the batch's exact file list, never a pattern.
says  agents/architecture-reviewer.md 'names the file that lists the batch'
says  references/dispatch-brief.md 'Sweep: the files listed in <the list path next prints>'
# F-1: setup says why when there is no code to review.
says  skills/setup/architecture-review.md 'say you found no code to review'
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
