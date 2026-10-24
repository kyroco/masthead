# Dispatch brief

Seven hooks read every `Agent` call. `hooks/agent-brief-gates.sh`, in
the plugin's hooks folder, runs six and joins their refusals into one message. One
of those six, `dispatch-record-gate.sh`, only records and never refuses.
`hooks/skill-review-gate.py` runs on its own.

## The shape

```
Model-choice: opus, this decides supervision behaviour and no diff can check it
Korium: nothing on the extractor pool refusal path; the only hits were about
queue admission, which is a different subsystem.

Fix review findings 1, 2 and 3 in the connection pool.

Finding 2 needs a genuinely dead process rather than a stub returning an error
tuple, because a stub does not take the supervisor with it.

Run the korium agent_search tool before you start, capture decisions and
reversals with agent_capture as they happen, and capture one handoff before you
return.
```

The `Model-choice:` first line is required when the dispatch would run on Opus;
see `model-choice-gate.sh` below.

## A reviewer's brief

A brief to `reviewer` or `security-reviewer` passes every check the first time
when it carries these, in this order (four of one session's reviewer briefs were refused for
missing one):

```
read_only: true
This is a review; you change no code.

Angle: <angle>. Review <the diff command, with the head commit>. Level every
finding Important or Nit. Write your findings to
<state>/review/findings-reviewer-<angle>-<name>.json
(security-reviewer: <state>/review/findings-security-reviewer-<name>.json),
where <state> is the repo's PROJECT_STATE_DIR fact from the env block of its
.claude/settings.json (.claude/state when it states none).
Write the real path in the brief, never the placeholder.

What it does: <two or three plain sentences>.

Code outside the diff this depends on: <modules, files and functions it calls
into or is called by>, or "self-contained".

How it is proven, and its limit: <the tests, what they drive for real, and what
is out of reach>.

What the author claims works: <list>.
What the author did not prove: <list>.

Use code_locate with repo "<repo value>" and branch "<branch>" before
reading code. Capture your review with agent_capture and return its
thought_id with your findings.
```

A reviewer's brief names no Korium memory search: reviewers hold only
`code_locate` and `agent_capture`, so no author's note reaches them.

The name in the file stops a later round overwriting an earlier one.

## The adjudicator's brief

It gets the round and nothing of yours: no claims, no did-not-prove list, no
summary of the change, no opinion of any finding.

```
read_only: true
This is a judging job; you change no code.

Judge the findings of this review round. The change is <base>..<head>.
The first review's range is <base>..<first-review head>.
The reviewed files are:
<git diff --name-only <base>..<first-review head>, one per line>
The findings files are:
<one path per line, every file the round wrote, Nits included>
```

The reviewed files are the first review's on every round, fix checks
included, so a fix that reached a new file cannot widen what counts as this
PR.

No `Korium:` line and no Korium ids, the reviewers' included: the adjudicator
judges from the code and the findings alone and holds no memory search.
`gate-agent` exempts it, as it does the reviewers.

**Index before you dispatch.** A reviewer has a read-only shell and cannot
re-index, so a stale index sends it to `rg`. Run `korium-cli index` in the
checkout after the last commit and before the dispatch, and give the branch in
the brief. Nothing checks this.

## What each check wants

**`dispatch-record-gate.sh` is a record, not a check.** It appends each dispatch
to the repo's `.claude/state/dispatches.tsv`, with the model from the call's `model` field
or the agent file's `model:` line. An optional first non-empty line,
`Model-choice: <tier>, <why>`, is recorded as the reason.

**`model-choice-gate.sh`. Haiku is the default for helper work.** A dispatch
that would run on Opus is refused unless its first non-empty line is
`Model-choice: opus, <why>`. It runs on Opus when the call sets `model: "opus"`,
or sets no model and the agent has no file naming one (general-purpose, Plan),
so it inherits this session's. Set `model: "haiku"` (or sonnet) on the call and
no line is needed. Opus is for work that decides something no later step
checks: writing code, judging a design. Not covered: agents whose file names a
model (reviewer, security-reviewer and diagnoser name opus; reader names haiku,
so a reader that must judge takes `model: "opus"` and the line), forks,
Explore, claude-code-guide, statusline-setup and plugin agents.

**`gate-agent`. Pass on what we already know.** If this session's `agent_search`
returned results, the brief needs a line starting `Korium:` with at least 40
characters of what we know, or saying Korium had nothing on this. If this session
has not searched, the brief names Korium and tells the agent to search, capture
as it goes, and capture once before returning. `reviewer` and
`security-reviewer` are exempt unless the brief orders a source change: do not
hand a blind reviewer the session's findings.

**`gate-fix-evidence`. A brief that asks for a fix says how the fix is proven.**
Name the real failure the test must cause: terminate the process, cause a genuine
SQL error, revoke the grant, stop the container. A stub returning an error tuple
is not the failure.

Do not ask for a break-it-and-restore run. A brief to `reviewer`,
`security-reviewer`, `diagnoser` or `reader` is skipped unless its first
instruction orders a change. Any other brief that changes no code declares it on
a line of its own in the first twelve non-blank lines: `read_only: true`,
`docs only`, or `no code change`. Declare it because it is true.

**`gate-wave-brief` checks briefs to `reviewer` and `security-reviewer` only.**
The brief carries what the author claims and could not prove, and the code
outside the diff the change leans on, or says plainly the change is
self-contained.

**`gate-brief-inference`: every brief except a reviewer's.** If it says
something cannot be done, mark whose judgement that is and invite the agent to
disprove it.

**`skill-review-gate.py`** refuses a dispatch of an agent whose
`.claude/agents` file changed and that this session has not read. Read it first.
It does not see the plugin's own agents.

These checks test that words are present, not true; a passing brief is not a
reviewed one.
