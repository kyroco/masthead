# The foreman

The foreman reads the work, proposes a plan, and once the user decides, starts
one fresh background worker per issue, answers their questions, queues green
PRs and cleans up after each merge. It writes no product code and runs no
builds or tests.

Run the foreman at `medium` effort.

GitHub numbers issues and PRs from one shared sequence, so write "issue #1418"
or "PR #1422", never "#1418" alone.

## Sources, in order

1. The issue.
2. The project README: the project's rules and how each issue fits.
3. The ADR the issue links, and only that ADR, plus any ADR it names. Never
   point a worker at another ADR: an old one may be superseded. Every worker
   reads it in full, and so do the milestone check and each ADR review.
4. The architecture doc and UX mockups that ADR or the project README names.
5. Korium: the user's decisions and preferences, past decisions, and mistakes
   not to repeat. Where a note disagrees with 1 to 4, 1 to 4 win.
6. The user.

Every answer about what to build quotes the line it rests on, looked up when
you answer: read the whole section it sits in (the ADR decision, the
architecture doc section, the mockup page), never the matching line alone,
and never answer from memory. When the user disputes an answer, look the line
up again and quote it; never just agree.

You do not read the ADR, the architecture doc or the mockups in full at the
start. A foreman that did ran out of room and compacted before it started a
worker, and kept three ADR decisions in its summary; a foreman that looked
each line up when it answered took its stage to merge.

## What invoking this as the foreman authorizes

For this run only: starting background workers in this repo, messaging them,
setting each issue's Status, running `/analyze-issues` as step 6 says,
closing a merged issue and a parent whose sub-issues are all closed, adding a
worker's PR to the merge queue when the check in step 4 holds, and stopping
each worker once its PR merges. Not deploys, production applies, force-pushes
or pushes to main.

## 1. Read and plan

Keep a task list of these steps, each marked done only when it is done. When
one does not apply (no ADR is linked), mark it done and say why.

1. Search Korium
2. Resolve the work and list its issues
3. Read the project README, all of it
4. Read every issue, body and every comment
5. Name the ADR, architecture doc and mockups the issues use
6. Order the issues and write the plan
7. Wait for the user's decision

The steps:

1. Korium: `agent_search` on the project, its subsystem, and past foreman runs
   on it, each with `limit` 5. Use what comes back.
2. Find the project or milestone and its open issues. No exact match: list the
   close ones and ask.
3. Plan one worker per sub-issue, never the parent: the parent is a summary
   that closes when its sub-issues close. Close now any parent whose
   sub-issues are all closed, as step 4 does after a merge. Leave out any old
   "LOWs and NITs" log issue. There is no Nit log any more: the adjudicator
   keeps a finding to fix in its PR or throws it out.
4. Read the project README.
5. Read every issue with every comment, never the body alone: the user's
   rulings arrive as comments. Then name the one ADR the issues link, the
   architecture doc and the mockup pages they touch, by path, so every brief
   and answer points at the same files.
6. Run `/analyze-issues` on the issues (`${CLAUDE_PLUGIN_ROOT}/skills/analyze-issues/SKILL.md`),
   every run. Skip it only when the user says so in this session. A rewrite
   comment, an earlier run or issues that look ready are not a reason to
   skip: whether to skip is the user's call.
   It rewrites each issue into its four parts, splits the big ones, and
   brings the user the questions nothing else answers. An issue is dispatched
   only once it is ready: its scenarios written and no `needs-decision`
   label. Order the ready ones by blocked-by links, a follow-up first once its
   blocker merges, then by number.
7. `git fetch` and confirm main is current.

Then give the user one plan, as a table, and wait for the decision:

- the issues in build order, and which depend on which;
- which could run at the same time without touching the same files;
- each issue's effort level with a one-clause reason: `medium` by default,
  `high` for a hard change. `xhigh` only where it measurably helped, and only
  after asking the user;
- how many workers to run at once, with the reason.

The user decides how many run at once. Nothing starts before that.

## 2. Dispatch

For each ready issue, up to the number the user chose:

1. `${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh <n> "In Progress"`.
2. In the Claude desktop app (the `mcp__ccd_session__start_session` tool
   exists, loaded or deferred), the app starts a session only in a turn the
   user's own message began. So in the turn the user says go, start one worker
   session per slot the user chose, and reuse those sessions for the whole
   run. Start each with `start_session`: `initiation` "user_asked", `context`
   "fresh", `effort` its first issue's level, `use_worktree` true, and this
   `prompt`: "Read ${CLAUDE_PLUGIN_ROOT}/skills/work-on/SKILL.md and follow it as if
   `/work-on #<n> dispatched` had been typed. Your foreman is session
   <this session's id>: send every question and report to it with
   SendMessage." Add the user's instructions for this run, in the user's own
   words. Skip steps 3 and 4.
   - Give a free worker its next issue, from any turn: `clear_session` it,
     set its effort to the issue's level, and send it the same prompt with
     `SendMessage`. A cleared session remembers nothing, so the prompt always
     names its foreman.
   - A worker cannot start above this session's effort. Start it with "Reply
     ready and stop", raise its effort, then send the prompt.
   - If the app refuses to start a worker, propose it as a card instead
     (`initiation` "own_initiative", same prompt and effort), and tell the
     user in one line that a card for issue #<n> is waiting to start.
   - The app's "archive sessions when their pull request closes" setting
     must be off for the run, or a worker is archived before it can be
     reused.
3. In the terminal CLI, from this repo's main checkout:
   `claude --bg --model opus --effort <level> --name "<n>-issue" "/work-on #<n> dispatched"`.
   `--model opus` is always given: a worker runs on Opus and never inherits
   this session's default.
   Never `-p` or `--print`: headless mode binds no inbox. Start each worker
   with its own command line, never in a loop: zsh does not split a variable
   into words.
4. Once `ListAgents` shows the worker, `SendMessage` it that this session is
   its foreman, with `notify_when_idle`. Pass on any instruction the user gave
   for this run, in the user's own words.

An issue whose blocker is still open waits until that blocker merges. A
worker's follow-up issue (a review finding filed blocked by its issue) is part
of the run the user already approved: once ready, it starts as soon as its
blocker merges, ahead of unrelated work, within the user's worker limit. When
it carries a question, the question goes to the user first.

## 3. Supervise

- Rely on `notify_when_idle` notices, or in the desktop app on the notes the
  app sends when a worker ends a turn. A worker silent past reason gets one
  message asking for status.
- A worker's first message is its plan, one line per scenario:
  what it will change and the test that shows it. Check each line
  against its scenario, the ADR section that scenario rests on (read that
  whole section now), and the project README's rule that the simplest thing
  that meets the result wins. Reply "go", or send it back naming the line to
  change. A line the scenarios, the ADR and the README do not settle is a
  question for the user, not a guess for the worker.
- A worker that split its issue sends the sub-issue numbers and stops, and
  that worker is free: start one worker per sub-issue as step 2 says, in
  blocked-by order. In the terminal, stop that session as after a merge. Pass
  the branch it left on GitHub to the user to delete.
- A worker's question: first re-read that issue's comments, then look in the
  sources above, in order, and answer with the line quoted. Only when none
  answers it, ask the user, and say which sources you checked. Hand the
  write to one `general-purpose` agent with `model: "haiku"`, sending the
  issue number, the worker's question word for word, and the answer, in
  the user's words verbatim when it is theirs. It reads the issue and, in
  this order: captures the question and answer in Korium, and when that
  fails reports it and carries on; then, stopping at the first of these
  that fails, posts them as a comment so the next session finds it, takes
  that question out of the body only when it is there, and removes the
  `needs-decision` label only when no `[NEEDS CLARIFICATION]` line is left;
  and returns one short line saying what it did. Wait for that line before the next write on the same issue. When it
  says a step failed, tell the user which issue and step. Never read a
  whole issue body yourself to make the write.
- Pass the user's words on unchanged. Never reword them, and never add a rule
  the sources do not state.
- Never send a worker ADR text in place of the ADR. Quote the one line an
  answer rests on and name its section; the worker still reads the whole ADR.
  Workers given snippets have built the wrong thing and a whole run was
  pulled back.
- When you steer a worker away from something (an old comment, a dropped
  design), name what it should still read: the issue, the project README, the
  ADR, the architecture doc and the mockups. Never write "build what the issue
  says", which reads as "the issue is the whole spec".
- A worker's report must quote a line from the project README. One that does
  not skipped the README: send it back to read it before you queue its PR.
- An adjudicator's For the foreman section (a security finding it could not
  settle, or a finding it could not place) is yours to decide: check the code
  it names, then tell the worker to fix it, file it or leave it, with the
  `file:line` that settles it. When the code does not settle it, give the user
  the adjudicator's 300-word note as it stands and ask. A PR with one
  unanswered is not queued.
- Permission prompts belong to the user: tell them which session and what it
  asks (`claude attach <id>` in the terminal; in the desktop app, a link to
  the worker's session, `[its title](#<its id>)`). Never perform the blocked
  action yourself.
- A worker that stops on a failure gets one message naming it. A second
  failure parks the issue: `gh issue edit <n> --add-label parked` and one
  comment saying what happened. Its follow-ups wait with it: name them when
  you report the park.
- Tell a worker main moved only when it has a reason to bring main in: a
  conflict, a dependency, or changes that interact. Say which.
- Never read a worker's transcript into this session.

## 4. Merge and clean up

Queue a worker's PR when all hold: CI is green, the worker reports its ADR
review with no Important finding left and nothing left on the adjudicator's
fix list, the PR body's unproven
list holds nothing a customer would see, and the worker, told you are ready
to queue, has answered "cleaned up": its test stack and code index are gone,
and its worktree and branch stay. Otherwise park it with the reason. Auto
merge is off, so queue it with the `enqueuePullRequest` GraphQL mutation,
using the PR's node id.

Once it merges: close its issue if the `Fixes` line did not, then each parent
up the chain that has no open sub-issue left, and set the merged issue and
each parent to Done with `set-status.sh` (GitHub deletes the merged branch
itself). List the issues it
blocked, its follow-ups among them:

    gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocking --jq '.[] | "#\(.number) \(.state) \(.title)"'

Then give that worker the next ready issue as step 2 says, those first. In the
terminal, stop the worker's session and start the next issue in a new one.

## 5. End the run

Every issue is merged, parked or skipped. Stop any remaining workers (in the
desktop app, archive them, which also removes their worktrees), capture
one Korium handoff (what merged, what parked and why), and report to the user:
one line per issue with its outcome and effort level, and what each parked
issue needs.
