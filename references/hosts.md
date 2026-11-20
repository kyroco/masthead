# Hosts

Masthead's foreman and workers run in a host: the terminal or the Claude
desktop app. Most of `/work-on` is the same in both. The steps below are not:
`skills/work-on/SKILL.md`, `foreman.md` and `worker.md` name each one and
point here, and never name a host's tool or command themselves. Each step has
one version per host. A new host adds its own version to each step.

## Which host you are in

- **Desktop app:** the `mcp__ccd_session__start_session` tool exists.
- **Terminal:** it does not.

## Start a worker

The foreman starts one worker per issue. On Linear, the prompt names the key
(`/work-on KOR-12 dispatched`) where it says `#<n>`.

- **Desktop app:** the app starts a session only in a turn the person's own
  message began, so start one session per slot in the turn they say go and
  reuse them for the whole run. `start_session` with `initiation`
  "user_asked", `context` "fresh", `effort` the issue's level, `use_worktree`
  true, and this prompt: "Read ${CLAUDE_PLUGIN_ROOT}/skills/work-on/SKILL.md
  and follow it as if `/work-on #<n> dispatched` had been typed. Your foreman
  is session <this session's id>: send every question and report to it with
  SendMessage." Add the person's instructions for this run in their own
  words. A worker cannot start above this session's effort: start it with
  "Reply ready and stop", raise its effort, then send the prompt. If the app
  refuses to start one, propose it as a card (`initiation` "own_initiative")
  and tell the person a card for issue #<n> is waiting. The app's "archive
  sessions when their pull request closes" setting must be off for the run.
- **Terminal:** from this repo's main checkout, one command line per worker,
  never a loop:
  `claude --bg --model opus --effort <level> --name "<n>-issue" "/work-on #<n> dispatched"`.
  On Linear the session takes `--name "KOR-12-issue"`. A worker runs on Opus
  and never inherits this session's model. Never `-p` or `--print`: headless
  mode has no inbox. Once `ListAgents` shows it, `SendMessage` it that this
  session is its foreman, with `notify_when_idle`, and pass on the person's
  instructions for the run in their words.

## Give a free worker its next issue

A worker is free once its PR merged, its landing was accepted in the batch
way, or it split its issue.

- **Desktop app:** from any turn: `clear_session`, set its effort, send the
  prompt of **Start a worker** with `SendMessage`; a cleared session
  remembers nothing, so the prompt always names its foreman.
- **Terminal:** stop the worker's session (its id and worktree come from
  `claude agents --json`, not from memory) and start the next issue in a new
  one, as **Start a worker** says.

## Reach the foreman

A dispatched worker sends every question and report to its foreman.

- **Desktop app:** with `SendMessage`, to the session its prompt names as its
  foreman.
- **Terminal:** with `SendMessage`, to the session whose first message told
  you it is your foreman; the start prompt names none (**Start a worker**).

## Hear from a worker, and wait on a run

- **Desktop app:** rely on the notes the app sends when a worker ends a
  turn, and on `Monitor`, not a shell loop, for a queued PR or a CI run, or
  in the batch way a batch Gate run.
- **Terminal:** rely on `notify_when_idle` notices, and on `Monitor`, not a
  shell loop, for a queued PR or a CI run, or in the batch way a batch Gate
  run.

## Ask the person

- **Desktop app and terminal:** the foreman asks in its own session, and a
  worker started by the person asks in its own.

## A permission prompt

Tell the person which session and what it asks; never perform the blocked
action yourself.

- **Desktop app:** a link to the worker's session, `[its title](#<its id>)`.
- **Terminal:** `claude attach <id>`.

## End a worker

At the end of the run, every worker still running ends.

- **Desktop app:** archive it, which also removes its worktree.
- **Terminal:** stop its session (its id comes from `claude agents --json`).
