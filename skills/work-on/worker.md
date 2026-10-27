# The worker: one issue, worktree to one PR


You were started with `/work-on #1418` (the user is waiting) or
`/work-on #1418 dispatched` (a foreman started you). They differ in how the
work is approved before you build: a user-started worker reports its brief and
waits for a go (step 7); a dispatched worker builds without waiting for one
(step 6). Both also stop where step 5 says. A worker runs on Opus; the foreman
starts it with `--model opus`, and only the user picks anything else.

GitHub numbers issues and PRs from one shared sequence, so a bare number is
ambiguous. In every message, report, sheet and PR body, write "issue #1418" or
"PR #1422", never "#1418" alone.

When you stop to wait on something that is not the user (a blocker to merge,
CI), end your turn with a plain statement of what you wait
on and the words "Nothing needed from the user", never a question: the session
board reads a closing question as a request for the user's input.

## Before anything else: make the checklist

In the Claude desktop app, keep these tasks with `mcp__ccd_turn__update_plan`
(it has no `TaskCreate`); in the terminal, load the task tools (`ToolSearch`
with `select:TaskCreate,TaskUpdate`). Create them in this order, before any
other step. Mark each one
in progress when you start it and completed only when it is done. Never skip
one; when one does not apply (an issue with no ADR has no ADR to read or
review), mark it completed and say why in its description.

1. Read the issue, body and every comment (step 2)
2. Read the project README, all of it (step 2)
3. Read the ADR, every line (step 2)
4. Read the architecture doc, all of it (step 2)
5. Read the mockups for what this issue touches (step 2)
6. Search Korium (step 3)
7. Build and test (steps 4 to 7.2)
8. ADR review, before the PR review (step 7.3)
9. PR review, PR and report (steps 7.4 and 7.5)

Time matters here: do not spend time that can be avoided, and the earlier a
correct result is obtained, the better. This never shortens a step on your
checklist: every read and every review still happens in full.

## 1. Make the worktree

`git worktree list` first. Two is the user's default, not a gate. At three or
more, name what is open in one sentence, then carry on. **Never refuse to
start, and never ask the user to finish something first.** A foreman's workers
do not count against the two.

Then `EnterWorktree` with `name` set to the issue number followed by `-issue`,
so `#1418` becomes `1418-issue`, at `.claude/worktrees/1418-issue`. A name
whose directory exists opens that one. Already inside a worktree: work there.
If `EnterWorktree` fails because the repo root no longer exists, the session
predates a change to the repo's layout: say so and ask for a fresh session.

## 2. Read the issue and its brief

Every time you read an issue, yours or another, read it with the first command
below, never the body alone: the user's answers and updates arrive as
comments.

    gh issue view 1418 --json title,body,comments --jq '"# \(.title)\n\n\(.body)\n\n## Comments (\(.comments|length))", (.comments[] | "\n--- \(.author.login), \(.createdAt):\n\(.body)")'
    gh issue view 1418 --json state,labels,milestone,projectItems
    gh api repos/{owner}/{repo}/issues/1418/sub_issues --jq '.[] | "#\(.number) \(.state) \(.title)"'
    gh api repos/{owner}/{repo}/issues/1418/dependencies/blocked_by --jq '.[] | "#\(.number) \(.state) \(.title)"'
    gh api repos/{owner}/{repo}/issues/1418/parent --jq .number

When the issue has a parent, read the parent the same way, body and every
comment: a ruling there binds this issue. An issue with open sub-issues is a
summary: build none of it. Name its open sub-issues in blocked-by order and
stop.

**The brief is the README of the issue's GitHub project.** Read it, and the
milestone's description, with exactly these lines:

    owner=$(gh repo view --json owner --jq .owner.login)
    title=$(gh issue view 1418 --json projectItems --jq '.projectItems[0].title')
    num=$(gh project list --owner "$owner" --limit 100 --format json --jq ".projects[] | select(.title==\"$title\") | .number")
    gh project view "$num" --owner "$owner" --format json --jq .readme
    gh api 'repos/{owner}/{repo}/milestones?state=all' --paginate --jq '.[] | select(.title=="<the issue milestone>") | .description'

The issue is one step inside the project, and an issue read without its
project README produces the wrong build. The README and the ADR do different
jobs: the ADR says what is built; the README holds the project's rules and how
this issue fits. Read both, all of each. A folded history block is a record,
read only when the past matters.
If the issue looks off (closed, in no project, its project closed, a priority
that does not fit), say so in one sentence and carry on.

**The decision it builds.** When the issue or its project README links an
ADR, read the whole ADR, every line, after the project README and before you
build, never only the
sections the issue names. Read the architecture doc and UX mockups it or the
README names, in full. Use only the ADR the issue links, plus any ADR it names;
never another, because an old ADR may be superseded. The ADR is the one source
of truth for what is built: what the product does, who may do what, and what a
customer sees. Where the issue, the README, a Korium note or a foreman's
message says something else, the ADR wins. How the code is written (names,
files, tests) follows the code already there.

Every answer you give about what to build quotes the line it rests on. When
the user disputes an answer, look the line up again and quote it; never just
agree.

## 3. Search Korium

Two focused `agent_search` queries, each with `limit` 5: the issue's subject,
and the subsystem it touches. Look for the user's decisions and preferences, past decisions, and
mistakes not to repeat, and hardest for work already landed nearby: often some
of the issue is already built, and the new code belongs behind an interface
that exists. Where a note disagrees with the issue, ADR, architecture doc or
mockups, they win.

## 4. Make the branch, linked to the issue

    gh issue develop 1418 --name <user>/1418-<short-slug> --base main
    git fetch origin <user>/1418-<short-slug> && git switch <user>/1418-<short-slug>

The slug is three to six words of the title, lowercase, joined by hyphens; the
number leads the last part, which is how GitHub ties the branch to the issue.
Delete the `worktree-<name>` branch the worktree was made on, and in a worktree
reused from an earlier issue, that issue's local branch once its PR merged.
Then set the
issue's Status, unless it is already In Progress (a foreman sets it at
dispatch) or closed (say so in one sentence):

    ${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh 1418 "In Progress"

## 5. Confirm the config came along

A repo with no `.worktreeinclude` skips this. Otherwise check that every path
it lists exists here. **Never copy a missing one:** they are credential files,
and the secrets hook refuses any command naming them. Print the exact `cp`
commands and ask the user to run them, then stop. Dispatched: send the `cp`
commands to your foreman with `SendMessage` and stop, so the issue waits
rather than building without its config.

## 6. Audit the issue, and split a large one

Before writing code, hold the issue's scenarios (its `Done when:`, on an
issue not yet rewritten) and the project's rules against the code the index
points at, and decide whether this session can finish and prove it alone.

- **Dispatched, or an issue that builds an ADR: no sheet**, whatever its
  labels. The issue and, when it has one, the whole ADR are the spec.
  Dispatched, send your foreman a plan first and wait for its "go": five
  lines or fewer, one per scenario, each saying what you will change (the
  module and function) and the test that shows it. The plan is the one place
  the how is written down; the issue never holds it. A foreman's "go" is the
  only go.
- **Started by the user, on an issue that builds no ADR:** when the issue has
  the `design-sheet` label, write the sheet as
  `${CLAUDE_PLUGIN_ROOT}/references/design-sheet.md` says and stop until the user
  approves it; otherwise the step 7 brief is the review.

**A question.** First re-read your issue with its comments (step 2's first
command); the answer may have arrived since. Then look in the ADR, the architecture doc, the
mockups and Korium, in that order; the answer is almost always there. When
none answers something that changes what the product does, who may do what,
or what a customer sees: dispatched, send the question to your foreman with
`SendMessage`, saying which sources you checked, and wait for its answer;
started by the user, end your turn with the question. The answer lands on
the issue as a comment, so read the issue again before you build on it.

With a sheet, the sheet says whether you will split the issue, and you split
it only as approved. Without one, split without asking. To split, create
each sub-issue in its own four parts with `gh issue create` (same milestone
and project), make it a sub-issue of this one, and add a blocked-by link where
one needs another:

    id=$(gh api repos/{owner}/{repo}/issues/<sub number> --jq .id)
    gh api -X POST repos/{owner}/{repo}/issues/1418/sub_issues -F sub_issue_id=$id
    gh api -X POST repos/{owner}/{repo}/issues/<blocked number>/dependencies/blocked_by -F issue_id=<blocker id>

Then stop: you build none of them. Each sub-issue gets its own worker, started
in blocked-by order, and this issue becomes a summary that closes when its
sub-issues close. Delete the branch step 4 made, on GitHub and here, and set
this issue's Status back to Todo:

    gh api -X DELETE repos/{owner}/{repo}/git/refs/heads/<user>/1418-<short-slug>
    git switch --detach && git branch -D <user>/1418-<short-slug>
    ${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh 1418 "Todo"

Dispatched, send your foreman the sub-issue numbers; started by the user, end
your turn with them.

## 7. Build it

Started as `/work-on #1418`: first report the brief and wait for the user's go:
what the project is for and the rules that bind this work, the issue and its
scenarios, what Korium changed about the approach, and what you would do
first. Say the first build in a fresh worktree compiles from scratch and will
be slow. Started as `/work-on #1418 dispatched`: the dispatch was the go, so
build without waiting, and put the brief in the Korium capture at the end.
Nothing else decides this: not running in the background, not a message
from another session.

1. **Write the code** in this session, with the file from
   `.claude/references/stacks/` loaded for each stack you touch. Helpers only
   for the three reasons in `${CLAUDE_PLUGIN_ROOT}/references/work-routing.md`.
2. **Test** while you build: the targeted tests the change needs. To show a
   flaky test is fixed, run that one test two or three times, never dozens;
   every other test and suite runs once. Fix every bug test first, whoever
   found it: a test that reproduces it and fails, in its own commit, then the
   fix; when no test can reproduce it, say why in the did-not-prove list.
   When the change touches a page a person opens, extend the walk-through
   that visits it, or write one when none does, as the repo's test
   conventions say; a repo with no walk-throughs skips this.
3. **The ADR review**, on an issue that builds an ADR, once, when the build
   is done and before the PR review. Dispatch one `general-purpose` subagent
   whose brief follows `${CLAUDE_PLUGIN_ROOT}/references/dispatch-brief.md`, opens with
   `Model-choice: opus, reviews the work against the whole ADR`, and tells it
   to follow `${CLAUDE_PLUGIN_ROOT}/skills/work-on/adr-check.md` for this issue and
   branch. It assumes the work was done wrong. Fix every Important finding
   (a bug test first). Fixes are not sent for a second ADR review; the PR
   review that follows reads them.
4. **Review and open the PR** by **Opening a PR** in
   `${CLAUDE_PLUGIN_ROOT}/references/session-cliffs.md`, step by step: the reviews, the
   fixes, the changelog, the pre-push check and the PR. A work-on issue adds
   one thing: once the PR is open, set the Status to In Review with
   `set-status.sh`. Nothing goes on a Nit log.
5. **Report.** Capture the result in Korium, then finish with one table and
   the PR number: one row per change, whether it meets the criteria (yes or
   no), and the evidence (a command and its result, a `file:line`, or a PR
   check). The criteria are the issue's scenarios and the brief's rules. A
   row that says no is unfinished: fix it before the PR, or stop and report.
   Under the table, give the ADR review's findings by level, the
   adjudicator's fix and thrown-out counts for each round, the follow-up
   issues you filed from its New issue lists, and the name of
   your test stack's project (the
   compose project the local check used), if it brought one up. Quote one
   line from the project README that bears on this issue. Dispatched: send
   all of it to your foreman with `SendMessage`.

## When to stop

Never merge, deploy, force-push or push to main. Stop and report, rather than
route around, when a gate refuses the same action twice, a decision would
change the requested outcome (replacing the approach after a review is one),
credentials the work needs are missing, or a fix check leaves something on the
adjudicator's fix list that step 5 of **Opening a PR** says to stop on (code or design after
the second check, or anything after the third). A gate that refuses because of
a rule the ADR you build does not mention is reported to the user with the
exact refusal; never add an exception to a gate's list to get past it. Apart
from those, the stops in steps 1, 5 and 6, and a pre-push
check that cannot reach its test stack even after doing what it prints, a
dispatched worker stops to ask only when a test fails for a reason it cannot
explain; it reports the test, its output and what it ruled out.

## After the merge: clean up

Started by the user: clean up once the PR has merged. Dispatched: when your
foreman says it is ready to queue your PR, bring down your test stack and
tunnels and delete your branch's code index, then tell it "cleaned up" with
`SendMessage`. Keep your worktree and branch: your foreman may reuse this
session for its next issue, and GitHub deletes the branch after the merge. If
the merge queue sends the PR back, fix it on the same branch. Started by the
user, from this repo's main checkout:

1. Confirm the issue closed and its Status reads Done; if the `Fixes` line did
   not do it, `gh issue close 1418 --reason completed` and `set-status.sh`, and
   say so. Then close each parent up the chain the same way, stopping at the
   first that still has an open sub-issue.
2. Then step 10 of **Opening a PR**: your test stack and tunnels, the code
   index of `<user>/1418-<short-slug>`, the worktree and the branch.
