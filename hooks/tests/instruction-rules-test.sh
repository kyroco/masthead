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
says  skills/work-on/worker.md "a plan first and wait for its \"go\": one line per scenario"
says  skills/work-on/foreman.md "A worker's first message is its plan, one line per scenario"
says  README.md "sends the foreman a plan, one line per scenario"
says  README.md "Scenarios** (at least one line of"
says  docs/explainer.template.html "<b>Scenarios</b> (at least one line of"
says  docs/explainer.html "<b>Scenarios</b> (at least one line of"
says  docs/explainer.template.html "sends the foreman a plan, one line per scenario"
says  docs/explainer.html "sends the foreman a plan, one line per scenario"
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

# 6. Issue #18: the words angle, contract without customer text, no extra reading pass.
says  agents/reviewer.md "- **words** every sentence a customer reads that the change adds or edits"
says  agents/reviewer.md "list every state that shows it"
says  agents/reviewer.md "report each state where it is false"
never agents/reviewer.md "plain English against"
never agents/reviewer.md "customer-text convention"
never agents/reviewer.md "every sentence a customer reads about that behavior"
says  agents/reviewer.md "what the change promises its callers, and where the code breaks it"
says  agents/reviewer.md "find any other copy of that rule"
says  references/session-cliffs.md "a \`words\` reviewer"
says  references/session-cliffs.md "adds or edits text a customer reads"
for doc in README.md docs/explainer.template.html docs/explainer.html scripts/diagrams.py docs/images/workflow.svg references/session-cliffs.md agents/reviewer.md agents/adjudicator.md skills/work-on/worker.md skills/work-on/foreman.md; do
  never "$doc" "English p""ass"
done
says  references/session-cliffs.md "Add the changelog entry when the repo keeps one"
never references/session-cliffs.md "which is not plain English"
says  README.md "the words a customer reads (when the change adds or edits any)"
says  docs/explainer.template.html "the words a customer reads (when the change adds or edits any)"
never agents/reviewer.md "plain English"
says  scripts/diagrams.py "7. push check"

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
never README.md "skill rewrites issues into this shape"
never docs/explainer.template.html "skill rewrites issues into this shape"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
