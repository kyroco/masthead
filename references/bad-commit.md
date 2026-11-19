# The search for a bad commit

What happens when a batch run on `landing` goes red (INFRA-269). The batch run
(`references/batch-run.md`) leaves main where it was; this search finds the
commit that turned the batch red, takes its change off landing, and records
whose it is, so the rest of the batch can reach main. Robert, November 18,
2026, agreeing to "Red is bisected, the bad commit is dropped and goes back to
its worker": "I agree with 1 and 2".

## Running it

The foreman runs it by hand from a checkout of the repository, with the id of
the red batch run:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/bad-commit.py <run id>

It needs `gh` signed in to the repository and git 2.40 or newer (for
`git merge-tree --merge-base`; the git macOS ships may be older). It reads the
Gate setup stored in `.claude/gate.json` (`references/gate-fact.md`) and never
works the Gate out: with none stored it stops with "No Gate is stored in
.claude/gate.json, so the search does not start and drops nothing." It starts
that Gate with `gh workflow run`, so the stored Gate must list
`workflow_dispatch`; one that does not stops the search too.

## What it does

| The red batch | What the search does |
|---|---|
| Red only because a runner could not start or fetch the code: every failed job failed at "Set up job", "Checkout" or "Run actions/checkout@...", not counting a verdict job that ran after all the others | Reruns the run's failed jobs (`gh run rerun --failed`) and drops nothing |
| One commit fails a check | Drops that commit |
| No commit fails alone, but some fail together | Drops the latest-landed of them, and names each commit it fails with. Robert, November 19, 2026: "(and we send back the latest one) it is its job to figure out what needs to be fixed and fix it" |
| No Gate run the search starts goes red, and a run of the whole batch again is green | Drops nothing, and says the red did not happen again |
| The commit cannot be taken off cleanly, because later commits change the same lines | Drops nothing, and says to hand it back by hand |
| The plan job stopped the batch run, or the run is not on landing | Drops nothing, and says why |

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

The batch run waiting behind the red one starts as soon as the red one ends,
and it holds the bad commit too, so it usually goes red as well. That run is
the starter's, not the search's.

## How the commit is dropped

With a revert commit pushed to landing as a plain push, never a force push: a
force push would race workers landing at the same moment and could lose their
commits. When landing moved meanwhile, the revert is made again on the newest
landing. The bad change is gone from landing's code; the commit itself stays
in landing's history. That push starts the next batch run, which tests the
rest of the batch again.

## The record

The revert's message carries the record as git trailers. The foreman reads
every record on landing with:

    git log origin/landing --grep='^Masthead-Dropped:'

and one record's fields with `git interpret-trailers --parse`. The search also
prints the record when it ends. INFRA-263 hands the commit back from these
trailers, so their names do not change without it:

| Trailer | Value | How many |
|---|---|---|
| `Masthead-Dropped` | the full id of the dropped commit | one |
| `Masthead-Issue` | its issue: the Linear key or `#<number>` its message names, or `none found` | one |
| `Masthead-Failed-Check` | the name of a Gate job that failed with it | one or more |
| `Masthead-Fails-With` | `<full commit id> <issue>`, for each commit it fails only together with | none when it fails alone |
| `Masthead-Red-Run` | the link to the Gate run that showed it red | one |
| `Masthead-Batch` | the full id of the red batch's last commit | one |
| `Masthead-Bring-Back` | `revert-this-commit-and-fix-in-one-push` | one |

The issue is read from the commit's message: a `Fixes <key>` or `refs <key>`
line first, then the subject, then the rest. In a Linear repository it is a
key of the team setup stored (`LINEAR_TEAM_KEY`).

## Bringing it back

The returned worker reverts the revert, which puts its change back as it was,
commits the fix on top, and pushes both to landing in one push. One push puts
both in the same batch, so no batch tests the change without its fix. Landing
the original commit again, cherry-picked, works as well, but reverting the
revert keeps the record and the change linked in landing's history. When the
dropped commit failed together with others, the fixing worker reads each of
their issues and comments first, and comments on each issue its fix touches.
Robert, November 19, 2026: "yes the fixing worker should add a comment to both
issues it was working on to make sure they stay in sync". Handing it back is
INFRA-263's.
