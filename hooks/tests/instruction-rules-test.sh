#!/usr/bin/env bash
# Checks that the skills state the three rules of issue #8 and no longer state
# the ones they replaced: issues sliced like scrum stories, one worker per
# sub-issue, and a review follow-up started as soon as its blocker merges.
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
never skills/github-issues/SKILL.md "more than about five scenarios"

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
never skills/work-on/worker.md "git/refs/heads"
says  skills/work-on/foreman.md "that worker is free"
says  skills/work-on/foreman.md "stop that session as after a merge"
says  skills/work-on/foreman.md "set the merged issue and each parent to Done"
says  skills/work-on/foreman.md "A worker that split its issue sends the sub-issue numbers"
says  skills/work-on/foreman.md "Close now any parent whose sub-issues are all closed"
says  skills/work-on/foreman.md "each parent up the chain"
says  skills/work-on/foreman.md "set each to Done"
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
says  skills/work-on/foreman.md "within the user's worker limit"
says  skills/work-on/foreman.md "the question goes to the user first"
says  skills/work-on/foreman.md "ready issue as step 2 says, those first"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
