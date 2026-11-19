# The search for a bad change

What happens when a batch run on `landing` goes red (INFRA-269, INFRA-288). The
batch run (`references/batch-run.md`) leaves main where it was; this search
finds the change that turned the batch red and says whose it is. It takes
nothing off landing: the change stays on the pile and its worker fixes it on
top. Main does not move until a later go runs green. Robert, November 19, 2026,
on the search only naming the bad change and nothing being dropped: "so why are
you asking me?" This replaces INFRA-269's drop by revert.

## Running it

The foreman runs it by hand from a checkout of the repository, with the id of
the red batch run:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/bad-commit.py <run id>

It needs `gh` signed in to the repository and git 2.40 or newer (for
`git merge-tree --merge-base`; the git macOS ships may be older). It reads the
Gate setup stored in `.claude/gate.json` (`references/gate-fact.md`) and never
works the Gate out: with none stored it stops with "No Gate is stored in
.claude/gate.json, so the search does not start and names nothing." It starts
that Gate with `gh workflow run`, so the stored Gate must list
`workflow_dispatch`; one that does not stops the search too.

## What it does

| The red batch | What the search does |
|---|---|
| Red only because a runner could not start or fetch the code: every failed job failed at "Set up job", "Checkout" or "Run actions/checkout@...", not counting the Gate's verdict jobs: the jobs its own workflow file runs, after others, on `always()` or `failure()`, such as Kyroco's `gate` | Reruns the run's failed jobs (`gh run rerun --failed`) and names nothing |
| One commit fails a check | Names that commit |
| No commit fails alone, but some fail together | Names the latest-landed of them, and each commit it fails with. Robert, November 19, 2026: "(and we send back the latest one) it is its job to figure out what needs to be fixed and fix it" |
| No Gate run the search starts goes red, and a run of the whole batch again is green | Names nothing, and says the red did not happen again |
| The batch run's own plan or move job could not start or fetch the code | Reruns the run's failed jobs and names nothing |
| The plan job stopped the batch run, the Gate passed and the move of main failed, or the run is not on landing | Names nothing, and says why |

In every case it pushes nothing to landing or main.

How it finds the commit: the batch is the commits on landing after main, up
to the red run's commit, oldest first. Landing is linear, so testing the first
k of them is running the Gate on the k-th commit itself. The search halves the
batch until it finds the first commit after which the Gate is red, then runs
the Gate on main with only that commit. Red: it fails alone. Green: it fails
only with earlier commits, and the search halves those the same way, with the
commit on top, until the set that fails together is found. A commit that does
not apply on main without earlier commits counts as needing them, and costs no
Gate run.

Each Gate run is on a throwaway branch, `masthead-search/<batch>-<n>`, deleted
when its run ends. A search run whose runner could not start is run again (up
to twice) before it is read. Workers keep landing while it runs.

## What it costs

Each row is full Gate runs, each billed like any other Gate run.

| The red batch | Gate runs |
|---|---|
| A runner could not start | 1 rerun of the failed jobs only |
| One bad commit in a batch of 1 | 0: the batch run already showed it |
| One bad commit in a batch of n | about log2(n), plus 1 to run it alone (0 when it landed first): 2 for 2 commits, 3 for 4, 4 for 8 |
| Commits that fail only together | about log2(n) + 1 more for each commit it fails with |
| A red that does not happen again | the same as one bad commit, plus 1 run of the whole batch |

## The record, and where it lives

The search prints one block, between a line that names the issue and
`--- end ---`. It holds the message for the change's worker, then the record:

| Field | Value | How many |
|---|---|---|
| `Masthead-Bad-Change` | the full id of the bad commit | one |
| `Masthead-Issue` | its issue: the Linear key or `#<number>` its message names | one |
| `Masthead-Failed-Check` | the name of a Gate job that failed with it | one or more |
| `Masthead-Fails-With` | `<full commit id> <issue>`, for each commit it fails only together with | none when it fails alone |
| `Masthead-Red-Run` | the link to the Gate run that showed it red | one |
| `Masthead-Batch` | the full id of the red batch's last commit | one |

The foreman posts the block, word for word, as a comment on that issue. The
comment is the record: the foreman and any later session find it on the issue,
since nothing is pushed for it to live in. A bad commit whose message names no
issue gets no block: the search prints the record alone and says to tell the
person.

The issue is read from the commit's message: a `Fixes <key>` or `refs <key>`
line first, then the subject, then the rest. Within a line the last key wins,
since a subject names its own issue at its end, as in "Undo part of INFRA-421
so the tests fail (INFRA-422)". In a Linear repository it is a
key of the team setup stored (`LINEAR_TEAM_KEY`).

## Fixing it on top

The foreman sends the same block, whole, to a worker on the issue (INFRA-263's
hand-back, `skills/work-on/foreman.md`). The worker starts from the newest
landing, commits the fix naming the issue, proves it as `/work-on` says, and
lands it like any other commit. Nothing is reverted or brought back: the bad
change never left. When it failed together with earlier commits, the message
also carries INFRA-263's rule, in Robert's words of November 19, 2026: "it is
its job to figure out what needs to be fixed and fix it, and not say: welp not
my commit sorry, moving on"; "it should read the issue to get context,
including the comments which now include what was done"; and "yes the fixing
worker should add a comment to both issues it was working on to make sure they
stay in sync".

Main moves once a later go runs green with the fix on top. That run carries
the bad change and its fix together, so `batch-issues.py merged <run id>`
lists the issue as merged with the rest.
