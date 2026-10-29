# Dispatch brief

Two hooks read every `Agent` call. `hooks/agent-brief-gates.sh`, in the
plugin's hooks folder, runs the one brief check, the model option and the
dispatch record, and joins their refusals into one message.
`hooks/skill-review-gate.py` runs on its own.

## The shape

```
Model-choice: opus, this decides supervision behaviour and no diff can check it

Fix review findings 1, 2 and 3 in the connection pool.

Finding 2 needs a genuinely dead process rather than a stub returning an error
tuple, because a stub does not take the supervisor with it.

Run the korium agent_search tool before you start, capture decisions and
reversals with agent_capture as they happen, and capture one handoff before you
return.
```

The `Model-choice:` first line is required when the dispatch would run on Opus
and the model option is on; see `model-choice-gate.sh` below. Nothing checks
that a brief carries what Korium found: pass it on because the agent needs
it, never for a gate.

## A verifier's brief

A brief to `verifier` passes the check the first time when it carries these,
in this order. One verifier per scenario; it gets the scenario and nothing
of your account of the change.

```
read_only: true
This is a verification; you change no code.

Scenario: <the scenario, word for word: Given, When, Then>.
Rests on: <the decision-record lines the scenario names, quoted>.
Verify <the diff command, with the head commit>. Write your findings to
<state>/review/findings-verifier-<scenario>-<name>.json, where <state> is the
repo's PROJECT_STATE_DIR fact from the env block of its .claude/settings.json
(.claude/state when it states none). Write the real path in the brief, never
the placeholder.

Code outside the diff this depends on: <modules, files and functions it calls
into or is called by>, or "self-contained".

How it is proven, and its limit: <the tests, what they drive for real, and what
is out of reach>.

Claims:
- <each Then line of the scenario>
- <each thing the author claims works>
- <each sentence a customer reads that the diff adds or edits>
Not proven: <list>.

Use code_locate with repo "<repo value>" and branch "<branch>" before
reading code. Capture your verification with agent_capture and return its
thought_id with your findings.
```

The form is exact, on purpose: the check reads a line that is exactly
`Claims:` at column zero, with no marker before it and nothing after the
colon, and the next non-blank line must be a `- ` bullet of at least four
words. Only the first `Claims:` line is read. Any other spelling (`**Claims:**`,
`1. Claims:`, `What the author claims:`, claims on the same line) is refused
with the form to use, so no variant is ever half-read.

A verifier's brief names no Korium memory search: verifiers hold only
`code_locate` and `agent_capture`, so no author's note reaches them.

The name in the file stops a later round overwriting an earlier one.

**A re-verify brief** opens with one more line, before everything else, and
carries only the claims the fix broke:

```
Re-verify: round 1, claims 2 and 3
```

That line is exact too: it begins `Re-verify: round N` at column zero, N
the number of this round, with no marker before it; any other spelling is
refused. The round number is for the log. The check does not read it: it
counts the verifier's re-verify rows already in the dispatch log for this
session on this branch and refuses a third, whatever the brief says. The
security reviewer sent in the same round does not spend one; a verifier that
died or was declined did, since its row was written before it ran.

**The security reviewer's brief** has the same shape, with the repository's
security conventions as its claims (its CLAUDE.md and `docs/conventions/`
where it has them) and the findings file
`<state>/review/findings-security-reviewer-<name>.json`.

## The adjudicator's brief

It gets the round and nothing of yours: no claims, no did-not-prove list, no
summary of the change, no opinion of any finding.

```
read_only: true
This is a judging job; you change no code.

Judge the findings of this verification round. The change is <base>..<head>.
The first verification's range is <base>..<first-verification head>.
The reviewed files are:
<git diff --name-only <base>..<first-verification head>, one per line>
The findings files are:
<one path per line, every file the round wrote>
```

The reviewed files are the first verification's on every round, re-verify
rounds included, so a fix that reached a new file cannot widen what counts as
this PR.

No `Korium:` line and no Korium ids, the verifiers' included: the adjudicator
judges from the code and the findings alone and holds no memory search.

**Index before you dispatch.** A verifier has a read-only shell and cannot
re-index, so a stale index sends it to `rg`. Run `korium-cli index` in the
checkout after the last commit and before the dispatch, and give the branch in
the brief. Nothing checks this.

## What each check wants

**`dispatch-record-gate.sh` is a record, not a check.** It appends each dispatch
to the repo's `.claude/state/dispatches.tsv`, with the model from the call's `model` field
or the agent file's `model:` line, and its outcome: `dispatched`, `refused`
when a check refused it, or `re-verify round N` for a brief whose line starts
`Re-verify:`, and the checkout's branch. An optional first non-empty line,
`Model-choice: <tier>, <why>`, is recorded as the reason. The rows for an
issue whose outcome is not refused are its agent-run count: the agents it
sent, a dispatch declined at a permission prompt among them, since the row
is written before the prompt.

**`model-choice-gate.sh`. Haiku is the default for helper work.** An install
option, off by default. When on, a dispatch
that would run on Opus is refused unless its first non-empty line is
`Model-choice: opus, <why>`. It runs on Opus when the call sets `model: "opus"`,
or sets no model and the agent has no file naming one (general-purpose, Plan),
so it inherits this session's. Set `model: "haiku"` (or sonnet) on the call and
no line is needed. Opus is for work that decides something no later step
checks: writing code, judging a design. Not covered when the call names no
model: agents whose file names a model (verifier, security-reviewer and
diagnoser name opus; the adjudicator and reader name haiku, so a reader that
must judge takes `model: "opus"` and the line), forks, Explore,
claude-code-guide, statusline-setup and plugin agents. A model named on the
call is checked whatever the agent.

**`gate-verify-brief` checks briefs to `verifier` and `security-reviewer`
only.** The brief carries a claims list in the one exact form above: a line
that is exactly `Claims:` at column zero, then a `- ` bullet of at least four
words; a variant is refused with the form. And a verifier's brief with a line
that begins `Re-verify: round N` is refused when the dispatch log already
holds two of the verifier's re-verify rows for this session on this branch;
a re-verify line in any other spelling is refused outright.
`MASTHEAD_BRIEF_GATE=off` in the operator's environment turns it off.

**`skill-review-gate.py`** refuses a dispatch of an agent whose
`.claude/agents` file changed and that this session has not read. Read it first.
It does not see the plugin's own agents.

These checks test that words are present, not true; a passing brief is not a
verified one.
