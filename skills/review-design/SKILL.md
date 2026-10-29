---
name: review-design
description: Review a decision record, its architecture doc and its mockups against each other, the code and Korium before any issue is written from them. It assumes the design is wrong, finds every state the artifacts are silent on and every place they disagree, asks the user one question at a time, and edits the artifacts, mockups included, until they all say the same thing. /review-design ADR-0170. Then it finds the issues that quote the lines it changed and fixes only those. Run it from the repo that holds the code and the mockups.
disable-model-invocation: true
---

# Review the design before issues are written

Issues are copied from the decision record and the mockups. A hole in those
is a hole in every issue, and a worker finds it halfway through a build. This
skill finds it first. It writes no code, no issue and no plan.

## What you read

All of it, not a search over it: the decision record, every line; the
architecture doc; every mockup page the record or the doc names, and the
mockup's model where there is one; the rubric or test support file the repo
keeps for the record; the code each decision touches, found with
`code_locate` first; and Korium, `agent_search` with `limit` 5, for the
record's subject, for each decision, and for the user's earlier answers.
Read the older records a decision changes, too.

## What you are looking for

Assume the design is wrong and prove it right, one decision at a time. For
each decision, look for:

- a state it is silent on: the empty case, the person who is missing or has
  left, a retry, two people at once, and what already exists in the code;
- two artifacts that disagree: the record says one thing, the mockup shows
  another, the doc a third, the code a fourth;
- a thing one artifact has and the others do not: a refusal on a mockup with
  no decision behind it, a decision with no screen, a setting in the code no
  decision names, a rule in the rubric the record no longer says;
- an older record it changes without saying so.

A finding names the two lines that disagree, or the state and the decision
that is silent on it. "Could be clearer" and "I would have done it another
way" are not findings.

## Questions

Settle each finding from the sources first: the user's words in the record
and its comments, Korium, the mockup's model. What nothing settles goes to
the user, one at a time, in the order a builder would meet it: what the
customer sees today, your one recommendation and why, and the question.
Wait for the answer. Write it down in the user's words. Then the next one.
Never write a decision the user did not make.

## Making the artifacts agree

After each answer, and for each finding a source settled, change every
artifact that should say it so they all say the same thing: the decision
record, with a dated line in the user's words under the decision it changes;
the architecture doc; the mockup page and its model; the rubric or test
support file. The mockups change too. Save and push each the way its home
asks: the wiki by a push, the repo by a PR.

## Report, and capture

One table: each decision, what disagreed or was missing, what the user
answered, what changed where. Capture the run in Korium with `agent_capture`
and give its id.

## Then the issues

Issues written before the review quote lines you changed. Find those and fix
only them, and leave every other issue alone. Start from your own report:
every decision, criterion and mockup line the review changed. Read the body
of each open issue the record's milestones hold. An issue is stale when one
of its scenarios rests on a line you changed, or quotes words that no longer
match it. Nothing else makes it stale: not wording you would prefer, not a
scenario you would have written differently.

Bring the user the stale issues as a table: the issue, the scenario line, and
the changed line it rests on. Change nothing until they say go. Then fix them
one at a time: rewrite only the stale scenario so it says what the artifact
now says, in the shape it had, keep every line the user wrote, write the new
body to a file inside the checkout and send it with
`gh issue edit <n> --body-file <path>`. A scenario that cannot be fixed
without a decision the user has not made is one question to them, and you
wait. When they are all done, say which issues changed and which you left
alone.

## What this skill never does

It writes no code, no issue and no plan, and never a scenario the sources do
not support. It runs before the issues are written and at no other time.
