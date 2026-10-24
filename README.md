# Masthead

Masthead is a plugin for [Claude Code](https://code.claude.com). It takes the
rules a team writes down for its AI and turns the ones that matter into
checks that run before the action, so they hold whether the session is five
minutes old or five hours old.

We built it because we had the rules written down and they still broke. We'd
put "search memory before you change anything" in the file Claude reads at
the start of every session, took out the small script that was enforcing it,
and within two days shipped a whole piece of work with nothing saved. Nobody
noticed until later. A rule in prose is a suggestion. A rule in front of the
action is a rule.

![A rule in prose fades over a session; a check holds](docs/images/gates.svg)

## Install

In a terminal:

```
claude plugin marketplace add kyroco/masthead
claude plugin install masthead@masthead
```

Then open Claude Code in a repository and run:

```
/masthead:setup
```

Setup asks three questions and writes nothing until you say yes.

1. Just you, or the team? That decides whether the settings are committed
   with the code or stay on your machine.
2. Tests before a push? It finds your test command and asks whether a push
   should wait for it.
3. A memory across sessions? Connect Korium now, later, or not at all.
   Everything else works without it.

Run `/masthead:setup` again whenever you want to change an answer. The
install options are under `/plugin configure masthead@masthead`:

| Option | Default | What it does |
|---|---|---|
| Connect Korium memory | off | Each session looks up what earlier sessions learned before its first change, and saves what it learned at the end. Needs a [Korium](https://kyroco.ai) account; there's a free plan. |
| Keep AI attribution out of commits | on | Refuses a commit message or pull request body with an AI co-author line, a session link or a generated-with footer. |
| Ask for a reason before a helper runs on the biggest model | off | Helpers run on the small model unless the brief says why the big one is needed. |

To remove it: `claude plugin uninstall masthead@masthead`. The settings file
setup wrote (`.claude/settings.json` or `.claude/settings.local.json`) and the
push check script (`.claude/push-check.sh`) are yours to delete.

## Every check, what it refuses, and where it falls short

Each check is a short script under `hooks/`, run by Claude Code at a fixed
moment: before a tool call, after one, or when a session or helper stops. It
reads what is about to happen and either lets it through or refuses it with a
reason Claude can act on. `hooks/hooks.json` wires them. `bash
hooks/run-tests.sh` runs every check's tests, and CI runs them on Linux and
macOS.

The off switches are environment variables read from the check's own
environment, so a session can't switch a check off for itself. Set one in your
shell before starting Claude Code if you ever need to.

### Always on

| Check | Runs | Refuses | Where it falls short |
|---|---|---|---|
| `block-secret-reads.py` | before a Read, Grep or shell command | reading a credential file: `.env`, keys, tokens, password files, cloud and SSH credentials, even through the masked reader | matches file names and command text, so a secret in an oddly named file isn't recognized |
| `block-secret-fetches.py` | before a shell command | pulling a secret out of a vault or secret store on the command line | matches command text |
| `scan-tool-output-for-secrets.py` | after a shell command | nothing; warns when the output looks like a credential | a backstop after the fact |
| `irreversible-action-gate.sh` | before a shell command | force pushes, history rewrites, deleting unmerged branches, destructive data and infrastructure commands, pushing without the push check | emits a refusal, not a question |
| `untrusted-domain-deny.py` | before a web fetch or search | requests to paste sites and other hosts code shouldn't reach | the host list is in the script |
| `web-to-memory-gate.py` | after a web fetch; before a write | copying text fetched from the web into files every session loads, or into memory, without a marker saying the web was read | files inside a git repository are left alone, since a pull request shows them |
| `agent-brief-gates.sh` | before a helper is sent | a brief to a reviewer that leaves out the author's claims or the code outside the diff the change depends on; a brief asking for a fix without saying how it's proved; a brief that passes a conclusion off as a rule | checks the shape of the brief, not whether it's true |
| `dispatch-record-gate.sh` | before a helper is sent | nothing; records which model each helper ran on, in the repository's state folder | |
| `review-write-fence.py` | before a file write | a reviewer writing anything but its own findings file, or a scratch copy under the review folder | a shell write isn't seen |
| `bash-scope-reviewer.sh` | before a shell command | a reviewer reaching the network | scoped by the agent's type |
| `bash-scope-diagnoser.sh` | before a shell command | the diagnoser or reader doing anything but running tests, reading git history and inspecting files | scoped by the agent's type |
| `verdict-gate.sh` | when a session or helper stops | a diagnosis case file whose verdict names no file and line, or has fewer than two numbered observations | |
| `scope-gate.py` | before and after a write | while a scope file exists in the checkout, writes outside its allowed paths; puts back a protected file a command changed | a background command's later writes aren't seen |
| `skill-review-gate.py` | before a skill or helper runs | invoking a changed project skill or agent nobody in the session has read | project files only |
| `prime-context.py` | at session start and on each prompt | nothing; injects the procedure that fits the prompt (before a commit, before a push, before reading a test result) | |

### On when the repository states the fact setup writes

| Check | Runs | Refuses | Needs |
|---|---|---|---|
| `hard-gate.sh` | before `git push` or `gh pr create` | a push until the push check reports the tests passed on this exact commit; a push of any other commit | the test command from setup (`PROJECT_PUSH_CHECK`) |
| `adr-sections-gate.py`, `adr-structure-gate.sh`, `wiki-refresh.sh` | before a write; at stop; at session start | a decision record written without its sections; a finish that leaves one with an unchecked claims list; keeps the records folder fresh | a decision records folder (`ADR_DIR`) |
| `elixir-toolchain-env.sh`, `elixir-format-after-edit.sh` | at session start; after an edit | nothing; pins the Elixir toolchain and formats an edited file | an Elixir root (`PROJECT_ELIXIR_ROOT`) |

### On or off with an install option

| Check | Option | Refuses |
|---|---|---|
| `engram-protocol.sh` | Connect Korium memory | the first edit before a memory search; a finish with nothing saved; a brief that hides what memory found; a capture filed under another agent's name; a grep for a name the code index already answered |
| `capture-finding-reminder.py`, `korium-index-on-stop.sh` | Connect Korium memory | nothing; reminders and index refreshes |
| `commit-attribution-gate.py` | Keep AI attribution out of commits | a commit message or pull request body with an AI co-author line, a session link or a generated-with footer |
| `model-choice-gate.sh` | Ask for a reason before the biggest model | a helper sent to the big model with no reason on the first line of its brief |

### Off switches

| Variable | Turns off |
|---|---|
| `MASTHEAD_CODE_GATE=off` | the code index check |
| `MASTHEAD_SEARCH_GATE=off` | the search-before-edit check |
| `MASTHEAD_CAPTURE_GATE=off` | the capture-name check |
| `MASTHEAD_MODEL_GATE=off` | the model check |
| `MASTHEAD_BRIEF_GATE=off` | the brief checks |
| `MASTHEAD_DONE_GATE=off` | the push check |
| `MASTHEAD_INDEX_ON_STOP=off` | the index refresh at stop |

## What a session looks like

You type one command with an issue number. Claude reads the issue and its
project README, makes a branch and a worktree, looks up memory if it's
connected, builds on the branch, sends the change to the blind reviewers,
fixes what the judge kept, runs the push check, and opens one pull request.
It asks you only when something is yours to decide.

![One issue, one session, one pull request](docs/images/workflow.svg)

You don't see the checks while this happens. You see one only when it refuses
something, and the refusal says what to do instead.

## The review, up close

When the change is done, Claude doesn't grade its own work. It sends the
diff, and nothing else, to reviewers who each take one angle: bugs, edge
cases, contracts, reuse and cleanup, plus a security reviewer when the change
touches sign-in, secrets or input from outside. They can't edit, can't reach
the network, and never see the author's explanation. A separate judge reads
the code and the findings, throws out what it can't prove, and gives the
author a list to fix, each item with a file and a line.

![The review wave: blind reviewers, one judge, one fix list](docs/images/review.svg)

## Why it's built this way

### Rules as checks, not as sentences

The rules that matter are small programs that run just before Claude acts.
If the action breaks the rule, the program says no and Claude sees why. We
only turn a rule into a check when we're prepared to enforce it, and we leave
out the rules we aren't, rather than pretend.

### Secrets are never read

A secret that gets into the conversation is in the transcript, in the logs,
and in whatever Claude writes next, so the only place to stop it is the read
itself. Claude asks you for the value instead. There's a masked reader for
the rare case where the shape of a file matters and the values don't.

### Nothing it can't undo

Everything else Claude does can be reviewed and reverted. A force push, a
rewritten history or a dropped table can't be, so those are refused outright
and you get one sentence saying why.

### Tests pass on the commit being pushed

When you say yes at setup, a push waits until your test command has passed on
the exact commit going out. Claude runs the tests itself and the check only
reads the receipt, which names the commit. That last part matters, because
the usual way a green run ends up attached to the wrong code is pushing a
different commit than the one that was tested.

### The reviewers are blind, and the judge decides

A reviewer who reads the author's explanation ends up reviewing the
explanation. A reviewer who can edit stops reviewing and starts fixing. A
reviewer who can reach the network can be talked to. We took all three away.
The judge is there because reviewers disagree, and the author shouldn't be
the one deciding which findings count.

### One issue per session

A session that carries several pieces of work drifts, and the second piece
gets a tired reviewer. Many short sessions cost little, so Masthead gives
each issue a fresh one, and a foreman mode runs several of them side by side.

### Helpers get the whole story

A helper starts with only its brief, and whatever is left out it never
learns. So a brief has to say what the author claims works, what isn't
proved, and how a fix will be proved, and a brief that passes the author's
conclusion off as a rule is sent back.

### Memory is optional

Korium is a product from Kyroco, the company behind Masthead. It has a free
plan, but it's an account and a sign-in, and that's your call. With it on,
Claude stops re-deriving what you settled last week. Without it, every other
check works the same.

### Your repository states its facts

A small settings file tells Masthead your test command, where your decision
records live if you keep any, and where it may keep its own working files. A
repository that states nothing still gets every always-on check, and the ones
that need a fact wait until it's there. Facts belong to the repository, so a
teammate who clones it gets the same checks without configuring anything.
Setup writes the file for you after you confirm it.

## What Masthead never does

- Send anything anywhere. There's no telemetry. The only network use is the
  Korium memory, and only if you connect it.
- Change your code on its own. The checks refuse actions; they don't take
  them.
- Read a secret file, not even to check it.
- Touch your git history. No co-author trailers, no footers.

## For the curious

The skills under `skills/` are the written procedures Claude follows:
`work-on` for the issue-to-pull-request flow, `setup` for the three
questions, `analyze-issues` to tighten issues before they're built,
`github-issues` for how the tracker is used, and the two Korium skills for
memory and code search. `agents/` holds the five reviewers and the judge.
`references/` holds the procedures the checks inject.

Masthead is made by [Kyroco](https://kyroco.ai). It's the setup we run on our
own repositories every day. Apache 2.0.
