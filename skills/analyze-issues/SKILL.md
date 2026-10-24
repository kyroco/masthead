---
name: analyze-issues
description: Check a milestone, a project or a list of issues before any of them is built, rewrite each issue into its four parts (Why, Scenarios, Out of scope, Questions), split the ones that are too big, and bring the user the questions nothing else answers. /analyze-issues milestone 4, /analyze-issues <project>, or /analyze-issues #3074 #3075. The foreman runs it as its first step; the user runs it alone any time after planning. Run it from the repo the issues live in.
disable-model-invocation: true
---
<!-- [web-access: this agent read web-search, github.com, code.claude.com, platform.claude.com, www.anthropic.com during this task. Not a claim about where this content came from.] -->

# Analyze issues before they are built

Agents go wrong when the issue could be better and when it is too big, not
because they are bad at the work. This skill fixes
the issue before a worker sees it. It changes no code.

An issue's shape, and the size rule, are in the `github-issues` skill. Read
that section first; this skill applies it.

## 1. Resolve the work

Find the open issues of the milestone, project or numbers given. An issue
with a parent is checked with its parent, as one. No exact match: list the
close ones and ask. Then `agent_search` Korium for the project, its
subsystem and earlier runs of this skill on it, and use what comes back.

## 2. Check each issue, in parallel

One `reader` agent per issue (Haiku, its own model, at high effort), all
sent in one message so they run at once. Each gets the brief in
`issue-check.md` beside this file, with the issue number filled in. It reads
the issue with every comment, the project README, and the ADR sections and
mockups the issue names, and reports:

- which of the four parts are present, and the lines that say how instead
  of what;
- the scenarios it reads out of the issue as it stands, and how many;
- the modules it expects the work to touch, from the code index;
- a split, when the size rule says so: each sub-issue's four parts and the
  order between them;
- the questions the sources leave open, each as
  `[NEEDS CLARIFICATION: ...]`;
- the rewritten body, in the four parts, with every line it kept from the
  old body and nothing it invented.

## 3. Check the milestone as one

One `reader` agent on Opus (`model: "opus"`, with the `Model-choice:` line
the dispatch check wants), given the brief in `milestone-check.md`: it reads
the whole ADR, the architecture doc, the project README and every issue, with
the per-issue reports, and names only these:

- two issues that build the same thing;
- an issue that contradicts the ADR, with the ADR line;
- a gap: an ADR decision for this stage that no issue builds;
- an order problem: a blocked-by link that is missing or wrong.

## 4. Apply the rewrites

Show the user the first issue's rewrite, old body and new side by side, and
wait for their go; that go covers the rest of the run. Then, for each issue,
in this session: edit the body to the rewrite
(`gh issue edit <n> --body-file`), keeping any folded history block, the Screens paragraph and every tool-maintained
block (between `:start` and `:end` comments) exactly as they were. Where the check split it, create the sub-issues as
the `github-issues` skill says (same milestone and project, the sub-issue
link, blocked-by where one needs another), each with its own four parts, and
leave the parent as the summary. Record each rewrite in one issue comment:
"Rewritten by /analyze-issues on <date>; the old body is in the edit
history."

Never drop a line the user wrote; quote it under the scenario it rules on.

## 5. Questions

For every `[NEEDS CLARIFICATION]`, look in the sources in order: the issue's
comments, the project README, the ADR, the architecture doc, the mockups,
Korium. What a source settles, answer on the issue as a comment quoting the
line, and take the question out. What nothing settles stays in the issue and
gets the `needs-decision` label.

Then put the open questions to the user one at a time, in build order, each
as one paragraph: what is blocked, your one recommendation with its reason,
and the question. Write each answer on the issue as a comment in the user's
own words, capture it in Korium, take the question out of the body and
remove the label. An issue with the label is not dispatched.

## 6. Report, and capture

One table, one row per issue: ready, split into which numbers, or waiting on
which question. Then the milestone findings. Capture the run in Korium with
`agent_capture` and give its id.

## What this skill never does

It writes no code, no plan and no design. How a scenario is built is the
worker's plan, checked by the foreman. It never adds a scenario the sources
do not support: a gap is a question, not a guess.
