# The batch run

How a repository's commits on `landing` reach main (INFRA-270). In a
repository that opted in, workers land verified commits on `landing` with no
pull request. A repository opted in when `project_fact.py --ships` prints
`batch`: its stored Gate and this starter file are both committed on
`origin/landing` (INFRA-276). Every other repository ships the pull request
way and has no batch run. Commits pile up on `landing`, and a push starts
nothing. When the person says go, one run of the repository's own Gate tests
the whole pile, together, and main moves to the pile's last commit only when
the run is green.
Robert, November 18, 2026, agreeing to "One Gate run tests each batch. Green
moves main forward.": "I agree with 1 and 2".

## The parts

| Part | Where it lives | What it does |
|---|---|---|
| The go | `skills/work-on/batch-go.py`, run by the foreman when the person says go | Checks the pile on `landing` belongs to the issues the go names, then starts the starter file on `landing`, once |
| The starter file | the repository's `.github/workflows/`, written by setup (INFRA-272) from `skills/setup/batch-starter.yml` | Starts only on a go (`workflow_dispatch`), never on a push, keeps one batch running at a time, and runs the three jobs below |
| `plan` | `kyroco/masthead/.github/workflows/batch-plan.yml` | Stops a run no go started, or whose `landing` moved after the go; reads `.claude/gate.json` at the batch's commit and stops when no Gate is stored or the starter runs another one |
| `gate` | the repository's own Gate, the workflow `.claude/gate.json` names | Tests the batch's last commit, started with `workflow_call` |
| `move` | `kyroco/masthead/.github/workflows/batch-move.yml` | When the Gate passed, moves main forward to exactly that commit, as the batch App |

GitHub runs only workflow files that live in the repository, so the
repository holds the small starter file and Masthead holds the rest. The
starter calls Masthead's two workflows at `@main`.

## The go

Robert, November 19, 2026: "Isn't the whole point of this change is to keep
throwing things on the landing until I say: go to main?" A batch is a
milestone ("batch means milestone"), or, where there is no milestone, the
issues the person names ("and when no milestone exists, then it is a set of
issues I say: go on to make a push"), and the run starts when the person says
so ("I can say go when I want."). The starter has no push and no schedule
trigger, so the pile costs no GitHub minutes until the go.

When the person says go, the foreman reads the milestone's issues from the
tracker, or takes the ones the person named, and runs, from a checkout:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-go.py --milestone "<name>" <issue> ...
    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-go.py <issue> ...

It reads main and `landing` from GitHub and finds each commit's issue in its
message, as `bad-commit.py` does: a `Fixes` or `refs` line first, then the
subject, and the last key on that line. Every commit on `landing` past main
must belong to a named issue, since the run tests `landing`'s last commit and
a green run moves main to all of it. A commit of any other issue, or of none,
stops the go: it names each such commit with its issue, and nothing starts.
Otherwise it starts the starter on `landing` with three inputs: `pile` (what
the go was for), `issues` (the named issues found on the pile) and `sha`
(`landing`'s last commit). `--check` checks and starts nothing.

The run's event is `workflow_dispatch`, its ref `refs/heads/landing`, and its
`github.sha` the last commit of `landing` when the go reached GitHub. `plan`
stops the run when its event is anything but `workflow_dispatch` (an older
starter, written before INFRA-285, still starts on every push: setup writes
it again), and when that commit is not the `sha` the go checked: `landing`
moved in between, and the person says go again so the new commits are
checked too.

## One run per batch

The starter's `concurrency` group lets one batch run at a time. A go while a
batch runs waits; a newer go replaces the one waiting (GitHub's concurrency
rule, `cancel-in-progress: false`).

## Green, red, and no Gate

- Green: `move` checks the commit is still on `landing` and main is behind it,
  then pushes it to main with a plain push, never forced. Main ends on the
  batch's last commit, the one the Gate tested.
- Red, cancelled or skipped: `move` does not run, and if it is ever made to
  run it refuses anything but a Gate that passed. Main stays where it was.
  The foreman then runs the search for the change that turned the batch red,
  which names it and says whose it is, and takes nothing off landing; its
  worker fixes it on top (`references/bad-commit.md`).
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

Setup's part (INFRA-272), each after the person's yes, through
`skills/setup/batch.py`: the starter file as `python3 skills/setup/gate.py
starter` prints it, written to `.github/workflows/masthead-batch.yml`; the
`landing` branch, made from main through GitHub's API when missing; an
environment named `masthead-batch` that only `landing` may use, holding the
App's id and key as the secrets `BATCH_APP_ID` and `BATCH_APP_PRIVATE_KEY`,
which a person stores; and, last, the lock on main, a ruleset refusing every
update, force push and delete of main whose only bypass is the batch App.
`batch.py lock` refuses until the landing branch on GitHub holds the starter
file setup writes and the environment holds both secrets, since a main locked
before the batch run can move it would never move again. `batch.py check`
answers `"offer"` false, and setup asks nothing, when the batch run is already
in place, the stored Gate cannot be started with `workflow_call`, or the
repository is on a personal account, which the App steps do not cover.
`batch.py check` says which parts are in place, changes nothing, and names any
other rule on main that would refuse the App. The README's "Set up the batch
run's GitHub App" holds the click-by-click App steps; `batch.py steps` prints
them for setup.

The key stays out of every workflow but the move. GitHub hands an
environment's secrets only to a job that names the environment, and only
`move` in `batch-move.yml` names `masthead-batch`. The Gate, called with
`secrets: inherit`, gets the repository's and organization's secrets, never the
environment's, and a workflow on any other branch that names the environment
is refused by its branch rule. A key stored anywhere else would undo this, so
`batch.py check` fails while the key is also a repository secret or an
organization secret the repository can read.

`gate.py starter` fills in the stored Gate and grants the starter's Gate job
the strongest token permission each of the Gate's jobs asks for: a called
workflow may ask for no more than its caller job grants, or GitHub refuses
the whole run before any job starts.

`plan` reads the starter's own `uses: ./...` lines, the workflow GitHub runs
as the Gate, and stops unless they name the stored Gate and nothing else.

## What the Gate sees in a batch run

The Gate runs the same code in a batch run as anywhere else, but what GitHub
tells it differs. Kyroco's first batch run (run 44591628232, November 19,
2026, 1:48 to 2:07 PM Eastern) went green only after its Gate changed in
three ways (INFRA-283). Any Gate that routes by event meets the same three.

| What the Gate reads | In a batch run | What breaks | Kyroco's fix |
|---|---|---|---|
| `github.event_name`, `github.workflow_ref` | `workflow_dispatch`, and the ref of `masthead-batch.yml@refs/heads/landing`, because the starter calls the Gate as a job | A test keyed on `workflow_dispatch` alone is true, but one on `github.workflow_ref` naming the Gate is false; a batch arm keyed on `push` is never true | Match a batch run on all three: event `workflow_dispatch`, `github.ref` `refs/heads/landing`, and `github.workflow_ref` ending in `masthead-batch.yml@refs/heads/landing` |
| `github.event.before` | Empty: a go is not a push | A diff from there sees nothing of the batch | Diff a batch run against main, as a run started by hand does |
| The check's and the run's names | Each check is `gate / <job>`, the starter's job `gate` then the Gate's own job name (Kyroco's verdict job is `gate`, so its check is `gate / gate`); the run is `Masthead batch`, not `Gate` | A script looking for the check by the job's name alone, or a `workflow_run` helper listening to "Gate", sees nothing | Match both names: `workflows: [Gate, Masthead batch]`, and both `gate` and `gate / gate` |

Kyroco's first batch run started on a push, before INFRA-285. The batch arms
of its plan-check test, part of the `if:` in its `gate.yml` (the whole test
adds two more conditions), match a batch run started by a go once the last
arm tests `workflow_dispatch`, not `push`:

```yaml
if: >-
  github.event_name == 'pull_request'
  || (github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main')
  || (github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/landing'
  && endsWith(github.workflow_ref, '/.github/workflows/masthead-batch.yml@refs/heads/landing'))
```

`python3 skills/setup/gate.py snags` points at each line that keys on one of
the three, in the stored Gate, every workflow it calls with `uses: ./...`,
and every `workflow_run` helper that names it, and says what a batch run
would miss there. A line that only declares a trigger is never pointed at, and
a line with its own fix within four lines counts as fixed: a batch arm naming
`masthead-batch.yml` beside a `github.workflow_ref` test or `github.event.before`,
a test for `== 'Masthead batch'` beside a test of the run's name, or
`gate / <job>` beside a lookup of that job's check. A test for a `push` beside
`refs/heads/landing` or `masthead-batch` is a batch arm from before INFRA-285
and is pointed at: it is never true now. A `workflows:` list that
names Masthead batch fixes the list, not a name test below it. It reads workflow files only: a script the Gate
runs (Kyroco's runner picker was one) needs the same search by hand. Setup
runs it before the starter lands, so the first batch is not where these show.
Masthead changes no repository's Gate; fixing a snag is the repository's
change to `.github/`.
