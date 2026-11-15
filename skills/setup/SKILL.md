---
name: setup
description: Set Masthead up for this repository. A few short questions, then it writes the few facts the gates read and shows what is on. Run it once per repository, right after installing the plugin, and again whenever you want to change an answer.
disable-model-invocation: true
---

# Masthead setup

You are setting Masthead up for the person in the repository this session was
started in. They may know little about Claude Code. Be brief and warm, use
plain words, ask one question at a time and wait for the answer. Never write a
file before they say yes to it. If they say "skip" to any question, skip it.

## 1. Look first, so you ask less

Quietly gather these, with commands that read and change nothing:

- Whether this session is in a worktree: `git rev-parse --git-dir` and
  `git rev-parse --git-common-dir` print different folders. Masthead reads a
  repository's settings from its main checkout only, so answers written in a
  worktree would never be read. Say so, ask the person to run `/masthead:setup` from the repository's main checkout, and stop.
- The repository: its name from `git remote -v`, and whether it has commits.
- Facts already set: read `.claude/settings.json` and
  `.claude/settings.local.json` for an `env` block with `PROJECT_PUSH_CHECK`,
  `PROJECT_STATE_DIR`, `ADR_DIR`, `ISSUE_TRACKER`, `LINEAR_TEAM_KEY` or
  `ARCHITECTURE_DOC`. If
  Masthead was set up before, say so and
  offer to change answers rather than starting over. When it was set up
  before and no `ARCHITECTURE_DOC` is recorded, offer the architecture doc on
  its own: go straight to step 8, then step 9, and ask none of the other
  questions unless the person asks to change an answer. The fact goes to the
  settings file that already holds the other answers.
  When `ARCHITECTURE_DOC` is recorded but `project_fact.py --architecture-doc`
  prints nothing, the doc has moved or gone: say which path is recorded and
  that no file is there, and offer the architecture doc on its own the same
  way.
- A test command, from the files present: `package.json` with a `test` script
  means `npm test`; `mix.exs` means `mix test`; `Cargo.toml` means
  `cargo test`; `go.mod` means `go test ./...`; `pyproject.toml`, `pytest.ini`
  or `setup.cfg` means `pytest`; a `Makefile` with a `test` target means
  `make test`. None of those means you do not know.
- A folder of architecture decision records: `docs/adr`, `docs/decisions` or
  `adr` at the top of the repository.
- The architecture doc: `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/project_fact.py --architecture-doc`
  prints the one already recorded, and
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/setup/architecture-doc.py find` lists
  the docs at the common paths (`ARCHITECTURE.md`, `docs/architecture.md`,
  `docs/architecture/README.md`, `docs/<folder>/architecture.md`).
- The project's principles: the file that numbers them P1, P2 and on, usually
  `CLAUDE.md` at the top of the repository.
- Whether Korium memory is connected: `claude mcp list` names a server called
  `korium`, or the person tells you.

## 2. Say what Masthead does

Three sentences, then the first question:

"Masthead adds a few guard rails to Claude Code in this repository: it refuses
dangerous commands and reads of secret files, it keeps the reviewers of a
change blind and separate from its author, and it can make sure tests passed
before anything is pushed. It needs to know five things about this
repository. The answers go in a small settings file, and you can change them
any time by running `/masthead:setup` again."

## 3. Question one: just you, or the team?

Ask: "Should these settings be shared with everyone who works on this
repository, or stay on your machine only?"

- Team: write to `.claude/settings.json`, which is committed with the code.
- Just me: write to `.claude/settings.local.json`, which Claude Code keeps out
  of git.

## 4. Question two: tests before a push?

If you found a test command, ask: "I found `<command>`. Should Masthead require
it to pass on the exact commit before Claude pushes or opens a pull request?
Claude runs the tests itself; you will only ever see a push refused when they
did not pass."

If you found none, ask: "What command runs this repository's tests? Say
'none' and Masthead will not check pushes."

On yes:

1. Copy `${CLAUDE_PLUGIN_ROOT}/skills/setup/push-check.sh` to
   `.claude/push-check.sh` in the repository, replacing `__STATE_DIR__` with
   `.claude/state`. Write the command, exactly as the user gave it, as the one
   line of `.claude/push-check.cmd`; the script runs that file, so quotes and
   `$( )` in the command stay as written.
2. Add `"PROJECT_PUSH_CHECK": ".claude/push-check.sh"` to the env block.

## 5. Question three: where do issues live?

Ask: "Where do this repository's issues live: GitHub or Linear? Masthead works
with one of them at a time, never both."

- GitHub: add `"ISSUE_TRACKER": "github"` to the env block. This is also what
  Masthead does when the setting is missing, so nothing changes.
- Linear: ask "What is the Linear team's key, the letters before the number in
  an issue like KOR-12?" Then add `"ISSUE_TRACKER": "linear"` and
  `"LINEAR_TEAM_KEY": "<the key>"` to the env block.

Write both to the file the first question chose. When that is the shared
file, also remove both from settings.local.json, so no older personal answer
outranks it. When it is "just me", leave the shared file alone: their own
answer wins on their machine only, and say so when the shared file names a
different tracker.

When the answer changes an earlier one, say that open issues in the old tracker
do not move by themselves, and that every Masthead skill follows the new
answer from the next session on.

## 6. Question four: a memory across sessions

If a `korium` server is already connected, say "Korium memory is connected, so
each session will search what earlier sessions learned before its first change
and save what it learned at the end," and move on.

Otherwise ask: "Masthead can give Claude a memory that lasts across sessions,
through Korium, a product from Kyroco with a free plan and no card needed. With
it on, each session searches what earlier sessions learned before its first
change, and saves what it learned before it finishes. Would you like to connect
it now, later, or not at all?"

- Now: give them the two steps and stop so they can run them:
  `claude mcp add --transport http korium https://api.kyroco.ai/mcp` (a sign-in
  opens in the browser the first time it is used), then
  `/plugin configure masthead@masthead` and switch "Connect Korium memory" on.
- Later or not at all: say nothing more about it, except that
  `/masthead:setup` brings the question back.

Everything else in Masthead works without Korium.

## 7. Architecture decision records, only if you found a folder

Ask: "I see `<folder>`. Should Masthead hold new decision records there to a
fixed shape (why it aligns with the project's principles, what counts as done,
and a checked list of factual claims)?" On yes, add `"ADR_DIR": "<folder>"` to
the env block.

## 8. The architecture doc

One doc per project, a page or two, gives the design a target shape that
decision records and pull requests are checked against. Write nothing to it,
and record nothing, before the person says yes.

**A doc is recorded.** Name it and go straight to the check below.

**A doc was found.** Name the file and ask: "I found
`<path>`. Is this the project's architecture doc?" With several, list them and
ask which, if any. On yes, add `"ARCHITECTURE_DOC": "<path>"` (relative to the
repository's top) to the env block. On no to every one, treat it as none found.

**None found.** Ask: "This repository has no architecture doc. Shall I draft
one from the code? It names the parts, the one module each body of data is
reached through and what it hands back, the rules between the core and its
extensions, and what each build ships. I will show you the draft before
writing anything." On no, skip it; running `/masthead:setup` again brings the
question back. On yes, read the code, then fill
`${CLAUDE_PLUGIN_ROOT}/skills/setup/architecture-template.md` in a scratch
file outside the repository. State only what the code shows; where it does not
say (which build ships what, which part is the core), ask the person rather
than guess. Show the whole draft and ask "Shall I write this to
`docs/architecture.md`?" (or a path they name). On yes, write it and add
`"ARCHITECTURE_DOC"` with that path to the env block.

**Either way, check it before showing it or recording it.** Run
`python3 ${CLAUDE_PLUGIN_ROOT}/skills/setup/architecture-doc.py check <doc> <principles file>`
(leave out the principles file when the project has none). For a draft you
made from the template, run it as `check --draft`, which also fails a draft
that leaves any of the template's four sections empty or holds a placeholder
anywhere. It passes only when the doc:

- states each of the seven lenses (Direction, One way in and out, Call shape,
  Seams, What each build carries, Leftovers, Tests and checks) as a rule for
  this project in plain words, such as "the core never names an extension",
  or says "Does not apply:" and why;
- cites the project's principles by number, such as P9, and copies none of
  their text, since the principles stay where they are.

Fix a draft until it passes. For a doc the person already has, show each line
the check printed in plain words, draft the missing rules and the citations,
show the exact text to add, and add it only on yes. If they say no, record
the doc anyway and say the architecture reviewer has no stated rules to hold
pull requests to until the doc has them.

## 9. Write, then show what is on

Show the exact env block and the file it goes to, and ask "Shall I write
this?" On yes, merge it into the file (keep everything already there). If
`.claude/state/` is not in `.gitignore`, ask whether to add it; Masthead keeps
its small working files there.

Finish with a table: each guard rail, on or off, and the one way to change it.
Keep it to the rails this repository has: dangerous-command and secret
refusals (always on), blind review (always on), push check (on if set), where
issues live (GitHub or Linear, with the team key), memory (on if connected),
decision records (on if a folder was named), architecture doc (its path, or
none). Then name the
four install options and their defaults, because a terminal install never
asked them: connect Korium memory (off), keep a code index in Korium (off),
keep AI attribution out of commits (on), ask for a reason before a helper runs
on the biggest model (off), all under `/plugin configure masthead@masthead`. End with: "Run `/masthead:setup`
again to change any of this."
