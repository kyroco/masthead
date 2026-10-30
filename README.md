# Masthead

Masthead is a plugin for [Claude Code](https://code.claude.com). You give it
a list of things to build, as GitHub issues, and it builds them: each one in
its own session, checked, reviewed by people who weren't in the room, tested
on the exact commit that ships, and merged. You decide the things only you
can decide.

## Why we built it

We'd had the rules written down for a long time. "Search memory before you
change anything" sat in the file Claude reads at the start of every session.
Then we took out the small script that was enforcing it, and within two days
a whole piece of work shipped with nothing saved. Nobody noticed until later.
A rule in prose is a suggestion. A rule in front of the action is a rule.
That's the idea under all of it: write the spec into the issue before the
session starts, let the session run on its own, and put the rules that
matter where they can't be forgotten.

![A rule in prose fades over a session; a check holds](docs/images/gates.svg)

Here's what a day with it looks like.

## A day with Masthead

It's Monday. You have a milestone with nine issues in it, the kind of list
that used to mean a week of watching over someone's shoulder. You open
Claude Code in the repository and type one thing:

```
/work-on milestone 4
```

![You type one command; the milestone has nine issues](docs/images/day-1-start.svg)

A foreman wakes up. It doesn't build anything yet. It reads. What earlier sessions
wrote down in memory first. Then the project's README, because that's the
brief: why this work exists, what shape it has, what rules it follows. Then
every issue, with every comment, because your rulings tend to arrive as
comments. It notes which decision record, architecture notes and
mockups the issues point at, but it doesn't read those end to end yet. Every
builder reads them in full, and when a builder asks a question, the foreman
reads the section the answer sits in and quotes it. A foreman that reads
everything up front runs out of room before the first builder starts.

![The foreman reads the brief and every issue first](docs/images/day-2-read.svg)

Then it sends a small agent to every issue, all nine at once. Each one reads
its issue and checks it against its sources, on a fixed list. Are the four
parts there, in order? Is every line you wrote still quoted under the
scenario it rules on? Does each scenario cite a source line that exists, one
the agent opens and quotes: a decision that was made, a rule in the README,
something you actually said? Can a test show it, "Given this, When that,
Then this is true"? Does it say what has to be true when it's done, or does
it tell the builder how to do its job? Does it fit one worker session? An
issue that passes is left alone: no edit, no comment. One that fails gets
only the failing part fixed, on GitHub, and a check in front of the edit
refuses a body that drops a line quoted as yours (three or more words in
quotes, with your name on the line or on a heading above it), or that adds a
question for you without saying where it looked first. Each agent hands the foreman only its
verdicts and the open questions. When all nine are done, one more agent, on
a stronger model, reads every issue against the decision record, the
architecture notes, the mockups and the old body. It puts back anything an
edit dropped and fixes the order, each fix resting on a line it can quote.
It tells you, without changing anything, when two issues build the same
thing, one contradicts the decision record, a decision has nobody building
it, or an issue is still too big for one session.

![Nine agents, one per issue, and one check of them all](docs/images/day-3-check.svg)

The big ones get split into sub-issues by the agent that checked them. Every
open question gets looked up in the sources first, in order: the issue's own
comments, the README, the decision record, the architecture doc, the
mockups, the memory. Whatever a source settles is written into the issue
with the line quoted, so nobody has to ask twice. Whatever nothing settles
comes to you, one question at a time, with a recommendation. You answer in a
sentence. It goes on the issue in your words. An issue with a question still
open stays out of the run until you've answered it.

Now the foreman tells you, in one sentence, what it is about to do, and asks
how many workers. You pick a number. Say three. It names the three issues
that fill those slots, each with what the customer gets, and brings you the
questions those issues still carry, one at a time, in plain words. You answer;
each answer goes onto the issue in your words. Then it tells you how far the
queue of issues with no open question runs behind them, and takes the next
questions whenever you want, so the run never waits on one. The order, the
effort each worker runs at and what can run side by side are its calls, and
it does not hand you a table to judge them by.

![The foreman's plan; you pick how many run at once](docs/images/day-4-plan.svg)

Three fresh sessions start, each with its own copy of the repository and a
branch tied to its issue. Each worker reads its issue, the README and the
decision record cover to cover, looks up what earlier sessions learned, and
builds. It writes no plan and waits for no go: the design was reviewed
before the issues were written, and the verifier checks each scenario once
the code exists. A worker is done when every scenario has a test that
passes, the screens the issue touches work, the push check passes and the
pull request is open. Then it stops.

![Three workers, each with its own session and its own copy of the repository](docs/images/day-5-workers.svg)

Then they build. A bug is fixed test first: a failing test in its own
commit, then the fix. Anything a worker notices that the issue didn't ask
for is an extra. It scores each one from 1 to 10, where 10 means leaving it
would cause a catastrophic failure, and brings you only what scores 8 or
higher. The rest is dropped, not filed.

When a worker thinks it's done, it doesn't grade its own work. For each
scenario it sends one verifier the scenario, the decision lines it rests on,
the README's opening paragraph on who uses the product, the mockup page the
scenario rests on, the diff, and two lists: what it
claims works and what it could not prove. Nothing else: not its notes, not
an earlier review. The verifier assumes the code is wrong and tries to prove
it, with every way a change goes wrong as its methods: a write that fails
halfway, an input nobody handled, a promise to a caller the code breaks, a
shared module written again, a sentence a customer reads that is false in
some state. It tries only states production can reach, starting from a real
entry point such as a route, a job or a webhook. For every claim it returns
either "true in every state", with the run that shows it, or each state
where it is false, with the run; never partly. A security reviewer joins
when the change touches sign-in, secrets or input from outside, with the
repository's security rules as its claims. None of them can edit anything.
None of them can reach the network. Then a judge, given the same product
context and nothing from the worker, reads the code along each verifier's
path without running the tests a third time, and places each finding that
holds: fixed in this pull request when a scenario's Then is false, something
that worked before broke, or words a person reads are now wrong; otherwise
an extra, which the worker scores like its own. That placement is final for
the worker and the foreman; nobody files anything. The worker fixes the
list, test first again, and only the claims the fix broke go back to a
verifier, at most twice. The tests run on the final commit and leave a
receipt that names it, and nothing can be pushed until the receipt matches.
Then one pull request goes up, with `Fixes #41`, the list of what wasn't
proved, the number of agent dispatches it took, and the issue moves to In
Review.

Meanwhile you're having coffee. A worker's question lands at the foreman,
which re-reads the issue's comments and Korium for an answer you already
gave and relays it with the line quoted. Anything you have not answered
reaches you one question at a time, in customer words, and your answer goes
back verbatim and onto the issue so the next session finds it. The foreman
decides how the work runs; what the product does, says or charges, and who
may do what, are yours. A worker that stops on a failure gets one
message; a second failure parks the issue with a comment saying what
happened, and the run goes on without it.

![You have coffee; questions reach you only when nothing settles them](docs/images/day-6-coffee.svg)

When a pull request is ready, the extras its worker brought come to you one
item at a time, and you answer each one: fix now, fix later, or proceed. Fix
later is the only way an issue gets filed. When its checks pass, its review
is clean, every line is answered and the worker has cleaned up after itself,
the foreman queues it to be merged. It closes the issue, and any big issue
whose pieces are now all done, then starts the next issue, a fix-later issue
that waited on this one first, in that worker in the desktop app or in a
fresh session in the terminal. By the end of the day every issue is merged,
parked or skipped, and you get one line per issue saying which, with how
many merged and how many were filed.

![A run: issues checked, a foreman plan, workers in parallel, merges](docs/images/workflow.svg)

The whole time, a set of small checks runs underneath. Nobody, not a worker,
not a verifier, not Claude in a hurry, reads a secret, force-pushes, pushes
untested code, or sends a verifier a brief with no claims to check. You
don't see those checks unless one says no, and when it does, it says why and
what to do instead.

![The verification: blind verifiers, one judge, one fix list](docs/images/review.svg)

### One issue on its own

`/work-on #123` does the same for a single issue with you as the foreman.
The worker tells you in a few lines what it will build and waits for your
go.

## Install

Open Claude Code in a repository and run these two inside the session,
not in a terminal, because only the in-session install asks you the four
install options (a terminal install takes the defaults silently):

```
/plugin marketplace add kyroco/masthead
/plugin install masthead@masthead
```

It asks whether to connect Korium memory (off unless you say so), whether to
keep a code index in Korium (off), whether to keep AI attribution out of commits (on), and whether a helper needs a reason
before running on the biggest model (off). Then run `/masthead:setup`. It
asks three questions about the repository, or two when a memory is already
connected, and one or two more when it finds a folder of decision records or
no ignore line for its working files, and writes nothing until you say yes: just you or the team
(whether the settings are committed with the code), tests before a push
(it finds your test command), and whether to connect a memory now, later or
not at all. Run it again whenever you want to change an answer.

To change an install option later, run `/plugin configure masthead@masthead`:

| Option | Default | What it does |
|---|---|---|
| Connect Korium memory | off | Each session looks up what earlier sessions learned before its first change, and saves what it learned at the end. Needs a [Korium](https://kyroco.ai) account; there's a free plan. Everything else works without it. |
| Keep a code index in Korium | off | Only with Korium memory on and korium-cli installed. The names and structure of the code in each repository you open, and the names you search for, go to your Korium account, so Claude can ask the index before it greps. Leave it off for a repository you may not send to Korium. |
| Keep AI attribution out of commits | on | Refuses a commit message or pull request body with an AI co-author line, a session link or a generated-with footer. |
| Ask for a reason before a helper runs on the biggest model | off | A helper sent to the big model, by the call or by inheriting this session's, runs there only when the brief says why; a call that names no model for a helper whose own file names one is not asked. |

To remove it: `claude plugin uninstall masthead@masthead`. The settings file
setup wrote and the push check script (`.claude/push-check.sh`) are yours to
delete.

## What an issue has to say

An issue says what is true when the work is done, never how to get there,
in four parts: **Why** (what a person can't do today, with the file and line
when known), **Scenarios** (at least one line of "Given, When, Then", each
naming the decision, README rule or your own words it rests on), **Out of
scope** (what this issue leaves to another), and **Questions** (what the
sources don't settle, each marked `[NEEDS CLARIFICATION]`). One issue is one
pull request, built and proved by one worker in one session. The
`analyze-issues` skill checks each issue against this shape and its sources,
fixes only the part that fails, and splits the ones that are too big, so you
don't have to write them this way yourself.

## Every check, what it refuses, and where it falls short

Each check is a short script under `hooks/`, run by Claude Code at a fixed
moment: before a tool call, after one, or when a session or helper stops. It
reads what is about to happen and either lets it through or refuses it with a
reason Claude can act on.

### Always on

| Check | Runs | Refuses | Where it falls short |
|---|---|---|---|
| `block-secret-reads.py` | before a Read, Grep or shell command | reading a credential file: `.env`, keys, tokens, password files, cloud and SSH credentials, even through the masked reader | matches file names and command text, so a secret in an oddly named file isn't recognized |
| `block-secret-fetches.py` | before a shell command | pulling a secret out of a vault or secret store on the command line | matches command text |
| `scan-tool-output-for-secrets.py` | after a shell command | nothing; warns when the output looks like a credential | a backstop after the fact |
| `issue-edit-gate.py` | before a shell command or a GitHub connector issue edit | an issue edit whose new body drops a line quoted as yours (three or more words in quotes, with your name on the line or on a heading above it), or adds a `[NEEDS CLARIFICATION]` question with no `looked in:` part naming the decision record, the README rule and the Korium query searched | on the shell it reads the body from `--body-file <path>` only, a real file (not a link) inside the git checkout, with the edit alone in its own command, and refuses with that form to use `--body`, standard input, a heredoc, a here-string, a session folder that is no checkout, and anything around the edit (a wrapper such as `sudo` or `env`, `$(...)`, a shell keyword, a `cd`, another command); a connector edit with no `gh` is checked against the issue as the session last read it, and refused when it has not read it; knows you by the first name in git config, or "the user" when it is the one speaking; a document quote on the same line as your words is kept too; a question already on the issue is left alone; it guards against a line dropped by accident, like the other checks, and does not resist a session set on getting past it |
| `connector-commit-gate.py` | before a GitHub connector call | `push_files`, `create_or_update_file` and `delete_file`, which write a commit on GitHub that never passes the push gate's test check; work goes up with `git push` | another server's tool with the same name is refused too |
| `irreversible-action-gate.sh` | before a shell command | force pushes, hard resets, `git clean`, deleting a remote branch, skipping the checks with `--no-verify`, and destructive data and infrastructure commands | emits a refusal, not a question |
| `untrusted-domain-deny.py` | before a web fetch or search | requests to paste sites and other hosts code shouldn't reach | the host list is in the script |
| `web-to-memory-gate.py` | after a web fetch; before a write | copying text fetched from the web into files every session loads, or into memory, without a marker saying the web was read | files inside a git repository are left alone, since a pull request shows them |
| `agent-brief-gates.sh` | before a helper is sent | a brief to a verifier or security reviewer that leaves out the claims it must check; a third re-verify round | checks the shape of the brief, not whether it's true |
| `dispatch-record-gate.sh` | before a helper is sent | nothing; records which model each helper ran on, and whether it was a re-verify round | |
| `review-write-fence.py` | before a file write | a verifier writing anything but its own findings file, or a scratch copy under the review folder | a shell write isn't seen |
| `bash-scope-reviewer.sh` | before a shell command | a verifier reaching the network | scoped by the agent's type |
| `bash-scope-diagnoser.sh` | before a shell command | the diagnoser or reader doing anything but running tests, reading git history and inspecting files | scoped by the agent's type |
| `verdict-gate.sh` | when a session or helper stops | a diagnosis case file whose verdict names no file and line, or has fewer than two numbered observations | |
| `scope-gate.py` | before and after a write | while a scope file exists in the checkout, writes outside its allowed paths; puts back a protected file a command changed | a background command's later writes aren't seen |
| `skill-review-gate.py` | before a skill or helper runs | invoking a changed project skill or agent nobody in the session has read | project files only |
| `prime-context.py` | at session start and on each prompt | nothing; injects the procedure that fits the prompt (before a commit, before a push, before reading a test result) | |

### Fully on once the repository states the fact setup writes

| Check | Runs | Refuses | Needs |
|---|---|---|---|
| `hard-gate.sh` | before `git push`, `gh pr create` or a GitHub connector's `create_pull_request` | a push that carries something shaped like a secret, or fails a changed stack's format, compile, lint or type check; with the test command, a push until the push check reports the tests passed on this exact commit, and a push of any other commit | nothing for the secret scan and the stack checks; the test command from setup (`PROJECT_PUSH_CHECK`) for the test receipt |
| `adr-sections-gate.py`, `adr-structure-gate.sh`, `wiki-refresh.sh` | before a write; at stop; at session start | a decision record written without its sections; a finish that leaves one with an unchecked claims list; keeps the records folder fresh | a decision records folder: `ADR_DIR`, or `docs/adr` when none is named, for the two gates; the refresh only with `ADR_DIR` set to an absolute path |
| `elixir-toolchain-env.sh`, `elixir-format-after-edit.sh` | at session start; after an edit | nothing; pins the Elixir toolchain and formats an edited file | an Elixir root (`PROJECT_ELIXIR_ROOT`) |

Where these three fall short, together: the fact names a file, and the copy
that runs is the one in the checkout you are in. A branch can change the push
check script or the toolchain file, the same way CI runs a pull request's own
tests. The record of which commit passed is a file in the checkout too. So the
push check is a guard against forgetting, not against intent; a pull request
review is the guard against intent.

### On or off with an install option

| Check | Option | Refuses |
|---|---|---|
| `engram-protocol.sh` | Connect Korium memory | the first edit before a memory search; a finish with nothing saved; a capture filed under another agent's name; a decision saved with no `decided_by` field, or with no word on what it replaces (it checks the field is there, not who it names) |
| `capture-finding-reminder.py` | Connect Korium memory | nothing; reminders only |
| `korium-index-on-stop.sh` and the code index gates in `engram-protocol.sh` | Keep a code index in Korium | a grep for a name the code index holds until the index is asked (and every grep while korium-cli is signed out or Korium does not answer), a search that repeats a name it just answered, and, once, a whole-file read of a file it just placed; the index refresh at the end of a session refuses nothing |
| `commit-attribution-gate.py` | Keep AI attribution out of commits | a commit message or pull request body with an AI co-author line, a session link or a generated-with footer |
| `model-choice-gate.sh` | Ask for a reason before the biggest model | a helper sent to the big model, by the call or by inheriting this session's, with no reason on the first line of its brief; a call that names no model for a helper whose own file names one is not asked |

The off switches are environment variables read from the check's own
environment, so a session can't switch a check off for itself:
`MASTHEAD_CODE_GATE`, `MASTHEAD_SEARCH_GATE`, `MASTHEAD_CAPTURE_GATE`,
`MASTHEAD_MODEL_GATE`, `MASTHEAD_BRIEF_GATE`, `MASTHEAD_DONE_GATE` and
`MASTHEAD_INDEX_ON_STOP`, each set to `off`. A switch that a repository's
own committed settings file sets is ignored, so a clone can't turn a check off
for the sessions that open it.

## What Masthead never does

- Send anything anywhere. There's no telemetry. The only network use is the
  Korium memory, and only if you connect it; the code index is a second
  switch, off unless you turn it on.
- Change your code on its own. The checks refuse actions; they don't take
  them.
- Read a secret file, not even to check it.
- Touch your git history. No co-author trailers, no footers.

## For the curious

The skills under `skills/` are the written procedures Claude follows:
`work-on` (the foreman and the worker), `review-design` (the design checked
against the code and the mockups before issues are written, and, when you say
yes, the mockups turned into screens), `analyze-issues`
(the checks on each issue before a build), `github-issues` (how the tracker is used), `setup`, and the two
Korium skills. `agents/` holds the verifier, the security reviewer, the
judge (the `adjudicator` agent), the diagnoser and the reader. `references/` holds the pull request steps and the brief
format. `bash hooks/run-tests.sh` runs every check's tests, and CI runs them
on Linux and macOS.

Masthead is made by [Kyroco](https://kyroco.ai). It's the setup we run on our
own repositories every day. Apache 2.0.
