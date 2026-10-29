---
name: analyze-issues
description: Check a milestone, a project or a list of issues before any of them is built, verify each issue against its sources (its four parts Why, Scenarios, Out of scope and Questions, the user's lines, each scenario's source line, its shape, no how, and the size rule), fix only the part that fails, split the ones that are too big, and bring the user the questions nothing else answers. /analyze-issues milestone 4, /analyze-issues <project>, or /analyze-issues #3074 #3075. The foreman runs it as its first step; the user runs it alone any time after planning. Run it from the repo the issues live in.
disable-model-invocation: true
---

# Analyze issues before they are built

Agents go wrong when the issue could be better and when it is too big, not
because they are bad at the work. This skill fixes
the issue before a worker sees it. It changes no code.

An issue's shape, and the size rule, are in the `github-issues` skill. Read
that section first; this skill applies it.

The session that runs this skill starts the agents and stays out of the way.
It writes no issue itself and holds no edit: each agent edits its issue
on GitHub directly, and GitHub keeps every earlier body in the issue's edit
history. An issue that passes every check is untouched: no edit and no comment,
so a second run on the same issues is cheap and changes nothing.

## 1. Resolve the work

Find the open issues of the milestone, project or numbers given. An issue
with a parent is checked with its parent, as one. No exact match: list the
close ones and ask. Then `agent_search` Korium for the project, its
subsystem and earlier runs of this skill on it, with `limit` 5, and use what
comes back.

## 2. Verify each issue, in parallel

One `general-purpose` agent per issue, with `model: "haiku"`, all sent in one
message so they run at once. Each gets the brief in `issue-check.md` beside
this file, with the issue number filled in. It reads the issue with every
comment, the project README, and the ADR sections and mockups the issue
names, then checks a fixed list: the four parts are present in order; every
line the user wrote is still quoted under its scenario; each scenario cites a
source line that exists, which it opens and quotes; each scenario is
Given/When/Then and a test can show it; nothing says how; and it fits one
worker session by the Size rule, with the reason.

An issue that passes every check is untouched: no edit and no comment.
Otherwise, on GitHub, it:

- edits only the part that fails, keeping every other line as it was: any
  folded history block, the Screens paragraph, every tool-maintained block
  (between `:start` and `:end` comments), and every line the user wrote,
  quoted under the scenario it rules on;
- splits the issue when the Size rule says so: each sub-issue with its own
  four parts, the sub-issue link, and blocked-by where one waits on another,
  leaving the parent as the summary;
- puts every question the sources leave open in the Questions part, each
  with its "looked in:" part naming the decision-record section, README rule
  and Korium query it searched, and adds the `needs-decision` label.

A check in front of the edit (`issue-edit-gate.py`) reads one form, the
body in a file inside the checkout sent with `gh issue edit <n> --body-file <path>`,
and refuses a body that drops a line quoted as the user's, or a question
without its "looked in:" part.

It returns only a verdict per check with its evidence, what it edited, the
sub-issue numbers and the open questions word for word.

## 3. Check the milestone as one

Once every per-issue agent is back, one `general-purpose` agent on Opus
(`model: "opus"`, with the `Model-choice:` line the dispatch check wants),
given the brief in `milestone-check.md`. It reads the whole ADR, the
architecture doc, the project README, every issue as it now stands with its
comments, and, for each issue edited today, its body before the edit from
GitHub's edit history.

It fixes on GitHub, itself, a copying mistake (a line of the user's dropped, a
kept part changed, a placeholder such as "the scenarios as in section 2"
where the text belongs) and a blocked-by link that is missing or wrong. Each
fix rests on a line it quotes from the ADR, the architecture doc, the
mockups or the old body; nothing it assumes is a reason to change an issue.

It reports, and changes nothing for, what would change what gets built:

- two issues that build the same thing;
- an issue that contradicts the ADR, with the ADR line;
- a gap: an ADR decision for this stage that no issue builds;
- size: an issue or sub-issue that does not fit one worker session by the Size rule,
  named with the reason.

## 4. Questions

Every open question is already on its issue, with the `needs-decision`
label: the per-issue agent looked in the sources before it asked. Put them
to the user one at a time, in build order, each as one paragraph: what is
blocked, your one recommendation with its reason, and the question. Hand
each answer's write to one `general-purpose` agent with `model: "haiku"`,
sending the issue number, the `[NEEDS CLARIFICATION]` line it answers word
for word, your recommendation when the user's words refer to it, and the
user's words verbatim. It reads the issue and, in this order: captures in
Korium the question, the recommendation marked as the session's when it
was sent, and the user's own words unchanged, and when that fails reports
it and carries on; then, stopping at the first of these that fails, posts
the same three as a comment, takes only that line out of the body (the new
body written to a file inside the checkout and sent with
`gh issue edit <n> --body-file <path>`, the one form the edit check reads), and
removes the label when no such line is left; and returns one short line
saying what it did. Wait for that line before the next write: one write at
a time. When it says a step failed, tell the user which issue and step;
when that step was the comment, body edit or label, the label stays and
the issue waits. Never read a
whole issue body yourself to make the write. An issue with the label is
not dispatched.

## 5. Report, and capture

One table, one row per issue: ready, split into which numbers, or waiting on
which question. Then what the check in step 3 fixed and what it reported.
Capture the run in Korium with `agent_capture` and give its id.

## What this skill never does

It writes no code, no plan and no design. How a scenario is built is the
worker's to decide when it builds; the design itself is reviewed before the
issues are written (`/review-design`). It
never adds a scenario the sources do not support: a gap is a question, not a
guess.
