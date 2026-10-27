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

says  skills/work-on/worker.md "Then stop: you build none of them"
says  skills/work-on/worker.md "each sub-issue in its own four parts"
says  skills/work-on/worker.md "set this issue's Status back to Todo"
says  skills/work-on/worker.md "When the issue has a parent, read the parent the same way"
says  skills/work-on/worker.md "An issue with open sub-issues is a summary"
says  skills/work-on/worker.md "each parent up the chain"
says  skills/work-on/worker.md "issues/1418/parent"
says  skills/work-on/worker.md "Name its open sub-issues in blocked-by order and stop"
says  skills/work-on/worker.md "korium-cli delete <user>/1418-<short-slug>"
says  skills/work-on/worker.md "name the branch left on GitHub"
says  skills/work-on/worker.md "git switch --detach"
says  skills/work-on/worker.md "git branch -D <user>/1418-<short-slug>"
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
says  skills/work-on/worker.md "the follow-up issues you filed"
says  skills/work-on/foreman.md "as soon as its blocker merges, ahead of unrelated work"
says  skills/work-on/foreman.md "dependencies/blocking"
says  skills/work-on/foreman.md "its follow-ups wait with it"
says  skills/work-on/foreman.md "a follow-up first once its blocker merges"
says  skills/work-on/foreman.md "is part of the run the user already approved"
says  skills/work-on/foreman.md "already approved: once ready, it starts"
says  skills/work-on/foreman.md "within the user's worker limit"
says  skills/work-on/foreman.md "the question goes to the user first"
says  skills/work-on/foreman.md "ready issue as step 2 says, those first"

# 4. No scenario count. The check is exact on purpose, not a prose scanner: it
# holds the lines where the rule now lives, and refuses the three phrases this
# issue removed wherever a person or agent reads them. It reads each file
# whole (grep -o, never -q), since a pipe that stops early on a match can turn
# a hit into a pass on a page as large as docs/explainer.html.
says  skills/github-issues/SKILL.md "Scenarios:** at least one, each a thing a test can show"
says  skills/github-issues/SKILL.md "How much one issue holds is the Size rule's call, never a count of scenarios"
says  skills/work-on/worker.md "write your plan: one line per scenario"
says  skills/work-on/foreman.md "A worker's first message is its plan, one line per scenario"
says  README.md "writes a plan, one line per scenario"
says  README.md "Scenarios** (at least one line of"
says  docs/explainer.template.html "<b>Scenarios</b> (at least one line of"
says  docs/explainer.html "<b>Scenarios</b> (at least one line of"
says  docs/explainer.template.html "writes a plan, one line per scenario"
says  docs/explainer.html "writes a plan, one line per scenario"
says  docs/explainer.html "its plan, one line per scenario"
says  docs/images/day-5-workers.svg "its plan, one line per scenario"
says  scripts/diagrams.py "its plan, one line per scenario"
says  .claude-plugin/plugin.json '"version": "0.1.5"'

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
says  agents/verifier.md "- **words** every sentence a customer reads that the change adds or edits"
says  agents/verifier.md "list every state that shows it"
says  agents/verifier.md "report each state where it is false"
never agents/verifier.md "plain English against"
never agents/verifier.md "customer-text convention"
never agents/verifier.md "every sentence a customer reads about that behavior"
says  agents/verifier.md "what the change promises its callers, and where the code breaks it"
says  agents/verifier.md "find any other copy of that rule"
says  references/session-cliffs.md "adds or edits text a customer reads"
for doc in README.md docs/explainer.template.html docs/explainer.html scripts/diagrams.py docs/images/workflow.svg references/session-cliffs.md agents/verifier.md agents/adjudicator.md skills/work-on/worker.md skills/work-on/foreman.md; do
  never "$doc" "English p""ass"
done
says  references/session-cliffs.md "Add the changelog entry when the repo keeps one"
never references/session-cliffs.md "which is not plain English"
says  README.md "a sentence a customer reads that is false in some state"
says  docs/explainer.template.html "a sentence a customer reads that is false in some state"
never agents/verifier.md "plain English"
says  scripts/diagrams.py "7. push check"

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
says  agents/verifier.md "You are given one scenario, the decision-record lines it rests on, the code, and the author's claim and unproven lists"
says  agents/verifier.md "true in every state"
says  agents/verifier.md "each state where the claim is false"
says  agents/verifier.md "## Attack methods"
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
# Scenario 2: the plan is verified before any code.
says  skills/work-on/worker.md "Send the plan to one \`verifier\`"
says  skills/work-on/worker.md "only the plan, the issue and the decision-record sections the issue names"
says  skills/work-on/worker.md "A second fail: stop and ask"
never skills/work-on/worker.md "wait for its \"go\""
says  skills/work-on/foreman.md "with its verifier's pass"
says  skills/work-on/foreman.md "You do not check the plan"
never skills/work-on/foreman.md "Reply \"go\""
never skills/work-on/foreman.md "Check each line against its scenario"
says  agents/verifier.md "## Verifying a plan"
says  agents/verifier.md "does it over build, does it cut corners"
says  agents/verifier.md "undoes a decision recorded in the issue or the decision record"
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
says  agents/adjudicator.md "run the reproduction the verifier showed"
says  agents/adjudicator.md "That placement is final"
never agents/adjudicator.md "or that is not plain English"
never agents/adjudicator.md "each finding you could not place"
says  skills/work-on/worker.md "never fixed in this PR"
says  skills/work-on/foreman.md "never fixed in this PR"
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
says  skills/work-on/worker.md "not yet checked"
# Scenario 8: the report counts agent runs, and a refused dispatch is not a run.
says  skills/work-on/worker.md "the agent-run count"
says  skills/work-on/worker.md "dispatches.tsv"
says  skills/work-on/worker.md "\$6 != \"refused\""
says  references/session-cliffs.md "not refused"
says  references/dispatch-brief.md "not refused"
says  skills/work-on/foreman.md "agent-run count"
# Review round 1 of issue #20: the docs say what the hooks do.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "a brief that hides what memory found"
done
says  docs/explainer.template.html "isn't real, isn't confirmed, or isn't worth a change"
says  docs/explainer.html "isn't real, isn't confirmed, or isn't worth a change"
for doc in scripts/diagrams.py docs/images/review.svg docs/explainer.html; do
  never "$doc" "could not be confirmed by running it"
  says  "$doc" "not real, not confirmed, or not worth"
done
says  references/session-cliffs.md "the security reviewer's dispatch does not spend a round"
says  skills/work-on/worker.md "A dead or declined verifier still spends its round"
# Fix check 1 of issue #20: the count is of agents sent, and a declined one is in it.
for doc in README.md docs/explainer.template.html docs/explainer.html; do
  never "$doc" "the count of agent runs it took"
  says  "$doc" "the count of agents it sent"
done
says  skills/work-on/worker.md "declined at a permission prompt"
says  references/dispatch-brief.md "declined at a permission prompt"
says  references/gate-catalog.md "A dead or declined verifier still spends its round"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
