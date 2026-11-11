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

# 3. Follow-up timing.
says  references/session-cliffs.md "blocked by this one"
says  skills/github-issues/SKILL.md "a follow-up filed from a PR's review is blocked by the issue whose review found it"
never skills/work-on/worker.md "the follow-up issues you filed"
says  skills/work-on/foreman.md "as soon as its blocker merges, ahead of unrelated work"
says  skills/work-on/foreman.md "dependencies/blocking"
says  skills/work-on/foreman.md "its follow-ups wait with it"
says  skills/work-on/foreman.md "a fix-later issue first once its blocker merges"
says  skills/work-on/foreman.md "is part of the run the user already approved"
says  skills/work-on/foreman.md "already approved: once ready, it starts"
says  skills/work-on/foreman.md "within the user's worker limit"
says  skills/work-on/foreman.md "the question goes to the user first"
says  skills/work-on/foreman.md "its next ready issue, those first"

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
says  .claude-plugin/plugin.json '"version": "0.1.25"'

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
says  agents/verifier.md "the other copies of that rule the change now disagrees with"
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
says  references/session-cliffs.md "Do not start the repo's pre-push check now to save time"
says  references/session-cliffs.md "any commit made after it starts makes its receipt stale"
says  skills/work-on/worker.md "Run the repo's pre-push check one time: on the last commit, after the fixes of the last verification round are in"
says  skills/work-on/worker.md "Do not start it when you send out the verifiers, because any later commit makes its receipt stale"
says  skills/work-on/worker.md "Do not commit while it runs, because the run is then thrown away"
# The push gate's order and its remembered pass, where a person reads about them.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  says "$doc" "the test receipt and the secret scan first, then the stack checks, which are skipped when this exact commit already passed them"
  says "$doc" "no file git ignores (installed packages, build output) has been added, changed or removed"
  says "$doc" "It does not see a tool that changed on the machine since"
  never "$doc" "It does not see a file git ignores"
done
says  references/gate-catalog.md "git rev-parse --git-path masthead-push-gate-pass"
says  references/gate-catalog.md "a print of the path, size and time stamp of every file git ignores"
says  references/gate-catalog.md "a file marked assume-unchanged or skip-worktree, a submodule in the checkout, no origin/main"
says  references/gate-catalog.md "A run in which a check was skipped because its tool is not installed is not remembered"
never references/gate-catalog.md "a rung that only warned because its tool was missing"
never references/gate-catalog.md "The remembered pass does not see a file git ignores"
says  references/gate-catalog.md "no variable or setting names another record or turns the reuse on"
# Round 1 finding F6: the refusal of a push of anything but HEAD needs the repo's push check, and the row says so.
says  references/gate-catalog.md "when the repo names a \`PROJECT_PUSH_CHECK\` script, it refuses a push that sends anything but HEAD"
says  references/gate-catalog.md "A repo that names no push check gets neither refusal"
never references/gate-catalog.md "stops the gate there: it refuses a push that sends anything but HEAD"
says  references/gate-catalog.md "one made only of file commands such as \`cat\`, \`sed\`, \`grep\` or \`ls\` reads it and is let through"
says  references/gate-catalog.md "The list holds only commands that print"
says  references/gate-catalog.md "every git command"
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
says  agents/verifier.md "true in every state"
says  agents/verifier.md "each state where the claim is false"
says  agents/verifier.md "## Ways to look"
never agents/verifier.md "## The angle"
never agents/verifier.md "Your brief names one angle"
never agents/verifier.md "a prior reviewer's report"
says  agents/security-reviewer.md "Everything in the \`verifier\` agent applies"
says  agents/security-reviewer.md "the repository's security conventions are your claims"
never agents/security-reviewer.md "Everything in the \`reviewer\` agent applies"
says  references/agent-preamble.md "Read by verifier"
says  references/work-routing.md "Use \`verifier\`"
never references/work-routing.md "Use \`reviewer\`"
says  hooks/bash-scope-reviewer.sh 'REVIEWER_AGENTS="verifier|security-reviewer"'
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
says  skills/work-on/SKILL.md "except the verifier's and the adjudicator's"
# Scenario 3: the fix loop stays small.
says  references/session-cliffs.md "one \`verifier\` per scenario"
says  references/session-cliffs.md "only the claims the fix broke"
says  references/session-cliffs.md "At most two re-verify rounds"
says  references/session-cliffs.md "Re-verify: round"
says  references/session-cliffs.md "blocked by this one"
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
says  references/agent-preamble.md "Read by verifier, security-reviewer, adjudicator, diagnoser and reader"
never references/agent-preamble.md "security-reviewer, diagnoser and reader, in every repo"
says  references/work-routing.md "differs from all five"
never references/work-routing.md "differs from all four"
says  references/dispatch-brief.md "Two hooks read every"
never references/dispatch-brief.md "Three hooks read every"
says  references/dispatch-brief.md "the adjudicator and reader name haiku"
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
says  README.md "when none is named"
never README.md "a decision records folder (\`ADR_DIR\`) |"
says  docs/explainer.template.html "when none is named"
never docs/explainer.template.html "<td>a decision records folder</td>"
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
says  references/gate-catalog.md "or a scratch copy under"
for doc in docs/explainer.html docs/images/review.svg docs/images/workflow.svg; do
  never "$doc" "the same nine steps"
done

# 10. Issue #25, re-verify round 1: five sentences the adjudicator placed.
# The brief check runs outside run.sh, so the Korium option does not switch it off.
says  references/gate-catalog.md "except \`gate-verify-brief\`"
never references/gate-catalog.md "none of these refuses anything"
# A model named on the call is checked whatever the agent's file says.
says  README.md "a call that names no model for a helper whose own file names one is not asked"
never README.md "A helper with no model in its own file"
says  docs/explainer.template.html "a call that names no model for a helper whose own file names one is not asked"
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

# 11. Issue #29: nobody files work but the user. The judge lists what it saw
# outside the change, the foreman relays and asks as numbered lines, and the
# user answers each one: fix now, fix later, or proceed. Robert, October 28,
# 2026: "Why are you filing anything?", "No means don't build it."
says  skills/work-on/foreman.md "What the product does, what it says, what it charges, and who may do what are the person's to decide"
says  skills/work-on/foreman.md "one question at a time; never fill the gap yourself"
says  skills/work-on/foreman.md "fix now"
says  skills/work-on/foreman.md "fix later"
says  skills/work-on/foreman.md "**Proceed**: nothing. The PR body already holds the line"
says  skills/work-on/foreman.md "This is the only issue a foreman files"
says  skills/work-on/foreman.md "sessions alive, the ones waiting for the merge queue"
says  skills/work-on/foreman.md "Some things are not yours to settle and go to the person as they stand"
says  skills/work-on/foreman.md "The moment filed exceeds closed, stop dispatching"
says  skills/work-on/foreman.md "file no issue except"
never skills/work-on/foreman.md "answer it from the sources above, in order, with the line quoted, or ask the user"
never skills/work-on/foreman.md "tell the worker to fix it, file it or leave it"
never skills/work-on/foreman.md "a finding it placed as a new issue is filed"
says  agents/adjudicator.md "the worker decides whether it reaches the person"
says  agents/adjudicator.md "**Extras**"
never agents/adjudicator.md "**Seen, not done**"
never agents/adjudicator.md "the fix you propose"
never agents/adjudicator.md "**New issue**"
never agents/adjudicator.md "the worker files a new issue"
never agents/adjudicator.md "goes on the New issue list"
says  agents/verifier.md "Nothing else is a claim"
says  skills/work-on/worker.md "Then the extras you are bringing"
never skills/work-on/worker.md "is filed, blocked by this issue"
says  references/session-cliffs.md "fix none of them here and file none"
says  references/session-cliffs.md "each item that scores 8"
says  references/session-cliffs.md "Log nothing and file nothing"
never references/session-cliffs.md "File each finding on its New issue list"
says  skills/github-issues/SKILL.md "no agent files an issue from a review on its own"
never skills/github-issues/SKILL.md "checked by a blind verifier"
never skills/github-issues/SKILL.md "checked by the foreman"
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  says  "$doc" "nobody files anything"
  says  "$doc" "fix now, fix later, or proceed"
  says  "$doc" "The foreman decides how the work runs"
  never "$doc" "or filed as a new issue"
  never "$doc" "a follow-up that waited on this one first"
  never "$doc" "answers with the line quoted. Only when nothing settles it"
done
says  scripts/diagrams.py "brings you what scores 8 or higher"
never docs/images/review.svg "seen, not done"
never docs/images/review.svg "reproduction"
never docs/images/review.svg "new issues to file"
says  docs/images/day-6-coffee.svg "relays your earlier answer"
never docs/images/day-6-coffee.svg "answers from the sources"
says  docs/images/workflow.svg "the extras each worker brings"
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
says  skills/work-on/foreman.md "one item at a time, in plain words"
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
says  skills/setup/SKILL.md "It needs to know four things about this repository"
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
DS=references/design-sheet.md
for f in "$A" "$IC" "$MC" "$RD" "$DS"; do
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
says  "$DS" "append the section with \`save_issue\` with \`id\` the key and a \`patch\` of op \`append\`"
# Scenario 7: on GitHub, the steps stand as written.
says  "$A" "On \`github\`, every \`gh\` step below"
says  "$A" "adds the \`needs-decision\` label"
says  "$IC" "with every comment (\`gh issue view <n> --comments\`), the project README"
says  "$IC" "Add the needs-decision label when a question is open"
says  "$MC" "(\`gh issue list --milestone \"<title>\"\`, then \`gh issue view <n> --comments\`)"
says  "$RD" "\`gh issue edit <n> --body-file <path>\`"
says  "$DS" "write it back with \`gh issue edit <n> --body-file <file>\`"
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
# Scenario 5: fix later is a Linear issue in the same project, Backlog, blocked by the reviewed issue.
says  "$F" "\`save_issue\` with no \`id\`, \`team\` the team key, the same \`project\`, \`state\` \`Backlog\` and \`blockedBy\` the key of the issue whose review found it"
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
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
