---
name: setup
description: Set Masthead up for this repository. Three short questions, then it writes the few facts the gates read and shows what is on. Run it once per repository, right after installing the plugin, and again whenever you want to change an answer.
disable-model-invocation: true
---

# Masthead setup

You are setting Masthead up for the person in the repository this session was
started in. They may know little about Claude Code. Be brief and warm, use
plain words, ask one question at a time and wait for the answer. Never write a
file before they say yes to it. If they say "skip" to any question, skip it.

## 1. Look first, so you ask less

Quietly gather these, with commands that read and change nothing:

- The repository: its name from `git remote -v`, and whether it has commits.
- Facts already set: read `.claude/settings.json` and
  `.claude/settings.local.json` for an `env` block with `PROJECT_PUSH_CHECK`,
  `PROJECT_STATE_DIR`, `ADR_DIR` or `PROJECT_ABILITIES`. If Masthead was set up before, say so and
  offer to change answers rather than starting over.
- A test command, from the files present: `package.json` with a `test` script
  means `npm test`; `mix.exs` means `mix test`; `Cargo.toml` means
  `cargo test`; `go.mod` means `go test ./...`; `pyproject.toml`, `pytest.ini`
  or `setup.cfg` means `pytest`; a `Makefile` with a `test` target means
  `make test`. None of those means you do not know.
- A folder of architecture decision records: `docs/adr`, `docs/decisions` or
  `adr` at the top of the repository.
- Whether Korium memory is connected: `claude mcp list` names a server called
  `korium`, or the person tells you.

## 2. Say what Masthead does

Three sentences, then the first question:

"Masthead adds a few guard rails to Claude Code in this repository: it refuses
dangerous commands and reads of secret files, it keeps the reviewers of a
change blind and separate from its author, and it can make sure tests passed
before anything is pushed. It needs to know three things about this
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

## 5. Question three: a memory across sessions

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

## 6. Architecture decision records, only if you found a folder

Ask: "I see `<folder>`. Should Masthead hold new decision records there to a
fixed shape (why it aligns with the project's principles, what counts as done,
and a checked list of factual claims)?" On yes, add `"ADR_DIR": "<folder>"` to
the env block.

## 6b. Abilities files, only if you found one

Look for abilities files whether or not you found a records folder: decision
records may live in a wiki while their abilities files sit in the repository
(YAML with `record`, `roles` and `lines`, one per decision record). If you
find any, ask: "Should a push be refused when an abilities file has a bad line
or its page was edited by hand?" On yes, add
`"PROJECT_ABILITIES": "<the file or its folder>"` to the env block.

## 7. Write, then show what is on

Show the exact env block and the file it goes to, and ask "Shall I write
this?" On yes, merge it into the file (keep everything already there). If
`.claude/state/` is not in `.gitignore`, ask whether to add it; Masthead keeps
its small working files there.

Finish with a table: each guard rail, on or off, and the one way to change it.
Keep it to the rails this repository has: dangerous-command and secret
refusals (always on), blind review (always on), push check (on if set), memory
(on if connected), decision records (on if a folder was named), abilities
check (on if a file or folder was named). Then name the
four install options and their defaults, because a terminal install never
asked them: connect Korium memory (off), keep a code index in Korium (off),
keep AI attribution out of commits (on), ask for a reason before a helper runs
on the biggest model (off), all under `/plugin configure masthead@masthead`. End with: "Run `/masthead:setup`
again to change any of this."
