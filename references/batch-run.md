# The batch run

How a repository's commits on `landing` reach main (INFRA-270). Workers land
verified commits on `landing` with no pull request. One run of the
repository's own Gate tests everything landed since the last run, together,
and main moves to that batch's last commit only when the run is green.
Robert, November 18, 2026, agreeing to "One Gate run tests each batch. Green
moves main forward.": "I agree with 1 and 2".

## The parts

| Part | Where it lives | What it does |
|---|---|---|
| The starter file | the repository's `.github/workflows/`, written by setup (INFRA-272) from `skills/setup/batch-starter.yml` | Starts on each push to `landing`, keeps one batch running at a time, and runs the three jobs below |
| `plan` | `kyroco/masthead/.github/workflows/batch-plan.yml` | Reads `.claude/gate.json` at the batch's commit and stops when no Gate is stored or the starter runs another one |
| `gate` | the repository's own Gate, the workflow `.claude/gate.json` names | Tests the batch's last commit, started with `workflow_call` |
| `move` | `kyroco/masthead/.github/workflows/batch-move.yml` | When the Gate passed, moves main forward to exactly that commit, as the batch App |

GitHub runs only workflow files that live in the repository, so the
repository holds the small starter file and Masthead holds the rest. The
starter calls Masthead's two workflows at `@main`.

## One run per batch

The starter's `concurrency` group lets one batch run at a time. A push while
a batch runs waits; a newer push replaces the one waiting (GitHub's
concurrency rule, `cancel-in-progress: false`). So when a run ends, the one
that starts next tests the newest commit on `landing`, which carries every
commit landed while the last run was going.

## Green, red, and no Gate

- Green: `move` checks the commit is still on `landing` and main is behind it,
  then pushes it to main with a plain push, never forced. Main ends on the
  batch's last commit, the one the Gate tested.
- Red, cancelled or skipped: `move` does not run, and if it is ever made to
  run it refuses anything but a Gate that passed. Main stays where it was.
  Finding the commit that turned the batch red is INFRA-262.
- No Gate stored: `plan` stops with "No Gate is stored in .claude/gate.json,
  so the batch run does not start and main does not move." The Gate and the
  move never start. Robert, November 19, 2026: "yes that's the right
  recommendation, keep the old way, new way is an option".

The batch run never works the Gate out. It reads the stored answer
(`references/gate-fact.md`) and checks the starter runs that one; a stored
Gate that cannot be started with `workflow_call` stops the run too, since the
starter runs the Gate as a job of its own.

## Green is decided inside the run

A `workflow_dispatch` run's check does not count toward a ruleset's required
status check, so no required check says a batch is green. The `move` job runs
only after the `gate` job passed in the same run, and that is the decision.

## What the repository needs

Setup's part (INFRA-272): the starter file as `python3 skills/setup/gate.py
starter` prints it, the lock on main whose only bypass is the batch App, and
the App's id and key as the secrets `BATCH_APP_ID` and `BATCH_APP_PRIVATE_KEY`.
`gate.py starter` fills in the stored Gate and grants the starter's Gate job
the strongest token permission each of the Gate's jobs asks for: a called
workflow may ask for no more than its caller job grants, or GitHub refuses
the whole run before any job starts.

`plan` reads the starter's own `uses: ./...` lines, the workflow GitHub runs
as the Gate, and stops unless they name the stored Gate and nothing else.
