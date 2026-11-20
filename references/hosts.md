# Hosts

Masthead's foreman and workers run in a host: the terminal, the Claude
desktop app, or a Claude Code Project, where the foreman and each worker is a
thread. Most of `/work-on` is the same in all three. The steps below are not:
`skills/work-on/SKILL.md`, `foreman.md` and `worker.md` name each one and
point here, and never name a host's tool or command themselves. Each step has
one version per host. A new host adds its own version to each step.

## Which host you are in

Look in this order, counting a tool whether it is loaded or only listed as
deferred:

- **Project:** the `mcp__hearthbot__` tools exist. With
  `mcp__hearthbot__message_coordinator` among them you are a thread; without
  it you are the coordinator, the session of the project chat.
- **Desktop app:** the `mcp__ccd_session__start_session` tool exists.
- **Terminal:** neither does.

## Start the foreman

- **Desktop app and terminal:** the session `/work-on` was typed in is the
  foreman.
- **Project:** a foreman is a thread, never the coordinator: the coordinator's
  context is swapped out to stay small, and a long run would block the
  project chat. The coordinator starts one thread for the run, titled for the
  milestone or the issues, with this prompt: "Read
  ${CLAUDE_PLUGIN_ROOT}/skills/work-on/SKILL.md and follow it as if
  `/work-on <what the person asked for>` had been typed. You are the foreman
  thread of this run." Add the person's own messages about the run, attached
  as theirs. Then the coordinator does nothing more of the run: it starts the
  worker threads the foreman asks for (**Start a worker**) and passes on what
  the person says about the run. A thread that reads this step is already
  the foreman.

## Show the crew

A project's status page lists who works on what: each foreman and the
workers it started. Each one adds itself, once, when it starts.

- **Desktop app and terminal:** nothing here; no page is read or written.
- **Project:** the status page is the Artifact titled "Project status" that
  `Artifact` with `action` "list" shows. With none, or more than one, write
  nothing and run as before. The page reads one document per thread in its
  database collection `crew`, written with `ArtifactData`. A thread's
  session id is the `id` that `get_session` returns when called with no
  `session_id`; it is also the document's id, so a thread is listed once
  however often it reaches this step: `get` that document first, and when it
  exists, leave it. A new one is written with `set`, its `order` one more
  than the highest `order` a `list` of `crew` shows.
  - The foreman, once it knows what it runs: `role` "foreman", `session`
    its session id, `label` the milestone it runs, or the issue keys or
    numbers it was given when there is no milestone, and `milestone` the
    milestone when there is one.
  - A worker, only when its prompt names a status page (**Start a worker**):
    on that page, `role` "worker", `session` its session id, `parent` the
    foreman's session its prompt names, `issue` its key or number, and
    `label` its thread's title.

  A write that fails stops nothing: say so in one line in the next report,
  and go on.

## Warm up the build

- **Desktop app and terminal:** as `foreman.md` says.
- **Project:** skip it. Each thread runs on its own machine, which cannot
  read the foreman's disk, so each worker builds cold and its prompt names
  no warm build.

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
- **Project:** a thread cannot start a thread. Ask the coordinator with
  `message_coordinator`, one message per worker, for a new thread titled
  with the issue's key or number and its title, with this prompt: "Read ${CLAUDE_PLUGIN_ROOT}/skills/work-on/SKILL.md and follow it
  as if `/work-on #<n> dispatched` had been typed. Your foreman is the thread
  <this thread's title> (<this thread's id>): send every question and report
  to it with message_thread." Attach the person's messages about the run, so
  their instructions reach the worker in their own words. When **Show the
  crew** found a status page, add "Status page: <its link>. Your foreman's
  session is <this session's id>." to the prompt. A thread's effort is the
  project's and it changes only on the person's word, so the issue's
  effort is not set.

## Give a free worker its next issue

A worker is free once its PR merged, its landing was accepted in the batch
way, or it split its issue.

- **Desktop app:** from any turn: `clear_session`, set its effort, send the
  prompt of **Start a worker** with `SendMessage`; a cleared session
  remembers nothing, so the prompt always names its foreman.
- **Terminal:** stop the worker's session (its id and worktree come from
  `claude agents --json`, not from memory) and start the next issue in a new
  one, as **Start a worker** says.
- **Project:** a thread is never given a second issue. Start the next issue
  in a new thread, as **Start a worker** says. The free thread stays open
  until its issue reaches main (**A worker's issue reached main**), or until
  **End a worker**.

## Reach the foreman

A dispatched worker sends every question and report to its foreman.

- **Desktop app:** with `SendMessage`, to the session its prompt names as its
  foreman.
- **Terminal:** with `SendMessage`, to the session whose first message told
  you it is your foreman; the start prompt names none (**Start a worker**).
- **Project:** with `message_thread`, to the foreman thread its prompt names.
  Your thread's own replies reach the coordinator and the person, not the
  foreman.

## Hear from a worker, and wait on a run

- **Desktop app:** rely on the notes the app sends when a worker ends a
  turn, and on `Monitor`, not a shell loop, for a queued PR or a CI run, or
  in the batch way a batch Gate run.
- **Terminal:** rely on `notify_when_idle` notices, and on `Monitor`, not a
  shell loop, for a queued PR or a CI run, or in the batch way a batch Gate
  run.
- **Project:** a worker's message arrives in the foreman thread as a turn of
  its own, and its wake names the worker's thread; note each worker's thread
  id from it. A turn that holds a shell loop or a sleep holds the thread, so
  for a queued PR, a CI run or a batch Gate run, schedule a message to this
  thread with `send_later` and end the turn; when it arrives, read the run as
  `foreman.md` says, with no person prompting it, and schedule the next check
  further out while the run is still going.

## Hand a change back

A red batch's search named a change, and its block goes to a worker on that
issue.

- **Desktop app and terminal:** its own worker when that session is still
  alive, otherwise a new one started as **Start a worker** says, with the
  block added to its prompt.
- **Project:** that issue's own worker thread, with `message_thread`; a
  message reopens a resolved thread. Its id is the one its report came from,
  or `list_threads` finds it by the issue in its title. No new worker starts for the issue while that
  thread exists; only when none does, start one as **Start a worker** says,
  with the block added to its prompt.

## Ask the person

- **Desktop app and terminal:** the foreman asks in its own session, and a
  worker started by the person asks in its own.
- **Project:** the foreman thread asks in its own thread with
  `post_message`, and a worker started by the person asks in its own. A
  dispatched worker thread never asks the person: its question goes to its
  foreman (**Reach the foreman**).

## A permission prompt

Tell the person which session and what it asks; never perform the blocked
action yourself.

- **Desktop app:** a link to the worker's session, `[its title](#<its id>)`.
- **Terminal:** `claude attach <id>`.
- **Project:** a link to the worker's thread, `[its title](#<its thread id>)`.

## End a worker

At the end of the run, every worker still running ends.

- **Desktop app:** archive it, which also removes its worktree.
- **Terminal:** stop its session (its id comes from `claude agents --json`).
- **Project:** tell each worker thread still open that the run is over for
  it, with `message_thread`; it resolves its own thread with
  `set_thread_resolved`, since a thread can resolve only its own. Then
  resolve the foreman thread, last.

## A worker's issue reached main

Its PR merged, or in the batch way a green batch moved main past its commits.

- **Desktop app and terminal:** nothing here; the session was already given
  its next issue, or ends at the end of the run (**End a worker**).
- **Project:** tell that issue's worker thread with `message_thread`; it
  resolves its own thread with `set_thread_resolved`. In the batch way never
  sooner, not at its landing: until main moves past its commits, a red batch
  may still hand its change back to it.
