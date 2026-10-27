# Work routing

When a subagent is worth spawning. The main session writes the code (CLAUDE.md).

## Three reasons to spawn a fresh helper

A fresh helper starts blank. Spawn one only for one of these three reasons. A
fork, the only other kind, is covered below.

**A blind context.** A verifier must not see the author's reasoning, and a
diagnoser must not see anyone's theory of the bug. That cannot be arranged inside
the window that already holds them. Use `verifier`, `security-reviewer` or
`diagnoser`.

**A narrower tool grant.** Work that should run without Write, Edit or the
network. `reader` holds no Write or Edit, its shell is fenced to read-only
commands, and it can read the web. Add an agent only when its grant differs from
all four.

**Parallel fan-out.** Several independent pieces of reading or checking at once,
or a noisy job whose answer is short (a test run, a log dig, a wide search). Use
the `reader` agent with a brief. For a search whose only answer is where
something lives, Claude Code's built-in `Explore` agent is lighter: it also holds
no Write or Edit, and it reads excerpts rather than whole files, so it locates
code but does not judge it. Ask the Korium code index first either way.

Each spawn costs roughly 20,000 tokens of overhead before any work happens, so
one subagent that reads five files beats five that read one each.

## Forks, and why not teams

A fork (`subagent_type: "fork"`) inherits this conversation, so it needs no
brief, but every step re-reads this session's context from cache. It exists in
interactive and background sessions, not under `-p` or the SDK. Use one only for
a short side fix that needs this session's background, while this session is
under about 150,000 tokens. One code-writing fork at a time. Never fork a verification:
a verifier must not know the author's reasoning.

Do not spawn agent-team teammates to write code: the Claude Code cost guide
("Manage costs effectively") puts a team at roughly seven times the tokens of one
session.

## Writing a brief

`references/dispatch-brief.md` holds the brief fields and the check that
reads them. Give each verifier one scenario and its claims, as
`agents/verifier.md` says.

## Verification

Send `security-reviewer` when the change touches authorization, secrets,
untrusted input or privilege, or when the repo's own security conventions say
to. The PR steps are **Opening a PR** in
`references/session-cliffs.md`.
