---
name: work-on
description: Work on GitHub or Linear issues, one session per issue. /work-on #1418, or a Linear key such as /work-on KOR-12, makes this session the worker for that one issue in this repo, from worktree to one PR. /work-on foreman makes this session the foreman and then asks what to run (a project, milestone or issue numbers); /work-on <project or milestone> does the same with the work already named. The foreman proposes a plan, the user decides how many workers run at once, and each issue runs in a fresh session of its own (a desktop session in the Claude desktop app, a background session in the terminal) through to merge. Run it from the repo the issue lives in.
disable-model-invocation: true
---

# Work on an issue

One session works on one issue, on GitHub or in Linear. Starting hundreds of short sessions is
fine; one session carrying several issues drifts.

## What you typed decides the role

Read the text typed after `/work-on`:

- **`#1418`**: you are the **worker** for that issue, started by the user,
  who is waiting. Read `${CLAUDE_PLUGIN_ROOT}/skills/work-on/worker.md` and follow it.
- **`#1418 dispatched`**: you are a worker a foreman started. The word
  `dispatched` means you write no sheet and build through to the PR without
  waiting for a go; a question the issue, its ADR, the architecture doc, the
  mockups and Korium do not answer goes to your foreman. Read `worker.md`.
- **A Linear key** such as `KOR-12` (the team's key, which may hold
  letters and digits, such as `K8S-12`, then a hyphen and a number), in a repo whose issues live in Linear: the same as `#1418`, so you
  are the worker for that issue, and `KOR-12 dispatched` makes a dispatched
  worker, the same as `#1418 dispatched`. A key is never read as a project or
  milestone name. Read `worker.md`, and its **On Linear** section.
- **`foreman`** on its own: you are the **foreman**, with no work yet. Say so
  in one line and ask what to run: a project, a milestone, issue numbers, or a
  mix, in words or GitHub links, now or later in this session. Read
  `${CLAUDE_PLUGIN_ROOT}/skills/work-on/foreman.md`.
- **A project or milestone**, in words or as a link, quoted or not, or
  `foreman` followed by a project, milestone or issue numbers: the foreman,
  with that work named. Read `foreman.md`.

With nothing typed, ask for an issue or a project; do not guess and do not
offer a list. A typo is not a missing argument: do what was meant. The word
`foreman` anywhere, or several issues, means foreman.

## Which tracker

Before reading any issue, run `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/project_fact.py --tracker`.
On `linear`, this repo's issues live in Linear only: follow the `linear-issues`
skill for every issue, project and status call below, and never look in GitHub
issues. Where no `linear-issues` skill is installed, say Masthead cannot work
Linear issues yet, and stop. On `github`, everything below holds as written.

## Which repo

Work in the repo the session was started in; this skill never moves a session
to another repo, and every `gh` command and GitHub connector call runs
against this one. Where the connector is loaded, issue, pull request, comment
and Status calls go through it and `gh` is the fallback; git keeps the
commits and pushes, and the merge queue stays on `gh` (the github-issues
skill, **Which tool makes the call**). The repo's own
facts come first: where its `CLAUDE.md` or `docs/conventions/` sets a test
command, a pre-push check, its changelog or a worktree
standard, those bind. The PR steps themselves are **Opening a PR** in
`${CLAUDE_PLUGIN_ROOT}/references/session-cliffs.md`. When a step names a
file this repo does not have, do what the step is for with what the repo has,
and list in the PR body each check the repo lacks. The `verifier` and
`security-reviewer` agents live in `${CLAUDE_PLUGIN_ROOT}/agents` and review every repo;
`/code-review` is not part of the flow.

## Korium, at every step

Search Korium before each step and before each change, not only at the start:
`agent_search` for what the step is about, and `code_locate` (with the `repo`
value from `CLAUDE.md`) for code you are about to read or change. For what is
adopted, use `stance: "position"` with a `limit` of 10, so a ruling that ranks
low is still read. Every other `agent_search` takes a `limit` of 5: each hit comes
back whole, and at the default of 10 one search has filled 40,000 characters.
Use what comes back, and put this rule in every subagent brief except the verifier's
and the adjudicator's, which hold no memory search and judge from the code,
the claims and the findings alone. Error -32029 is the
limit of 60 searches a minute, not an outage: wait the `retry_after_ms` it
gives and search again.

## What enforces this

`gate-edit` refuses the first edit until a Korium search has run, and
`hard-gate.sh` refuses `git push` and `gh pr create` until the repo's local
test receipt matches the commit. Nothing else in this skill or its files is
checked by a hook, including the ADR review; it rests on the text.

