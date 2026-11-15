# Bring existing code in line with the architecture doc

Step 10 of `/masthead:setup` sends you here. The pull request reviewer looks
only at the lines a change touches, so drift already in the code is never
seen by it. This review looks at the code as it stands, once, and files what
it finds only where the person says yes.

The script is `${CLAUDE_PLUGIN_ROOT}/skills/setup/architecture-sweep.py`,
called "the script" below, and the ledger is
`<state>/architecture-review.json`, where `<state>` is the repository's
`PROJECT_STATE_DIR` fact (`.claude/state` when it states none). The ledger
records which parts of the code were reviewed, so a review too big for one
session stops cleanly and the next `/masthead:setup` goes on from there.

You change no code and write no file but the ledger, and the review helpers
change nothing either. Ask one question at a time and wait for the answer.

## 1. Ask what they want

When `findings --ledger <L>` prints a file, a review was left unjudged: an
earlier session reviewed batches and ended before its judge. Say so, and go
to step 5 with what it prints before asking anything else.

Ask only when the repository has code: the script's `parts` exits 3 when it
holds none (it counts everything tracked but docs, media, archives, binaries,
licences and lock files), and then say you found no code to review, so there
is nothing to bring in line. When `left --ledger <L>` lists parts, a review
is part done: name how many parts are left and ask "Shall I go on with the
review we started?" On yes, run `resume --ledger <L>` and go to step 4. On
no, ask the question below; the review they choose replaces the part-done
one.

Otherwise ask: "Would you like me to check the code you already have against
the architecture doc? I can do a targeted review of the parts you name, or a
full sweep of the whole codebase, or neither. Either way you see what I find
before anything is filed."

- **Neither**: say "No review, nothing filed," and end setup.
- **Targeted**: step 2.
- **Sweep**: step 3.

## 2. A targeted review

Run `parts` and show its lines as a table: each part, its files and its lines
of code (a `<folder>/*` row is that folder's own files, without its
subfolders). Ask "Which parts should I review? Name folders or files." Then
run `plan --ledger <L> <each folder or file they named>`. Only the code under
what they named is reviewed. When it prints `no code under:`, say which name
holds no code and ask again. Go to step 4.

## 3. A full sweep

Run `plan --ledger <L>` with no part named: every code file in the
repository is reviewed.

In either step, when `plan` exits 4, a review is part done and the person
chose a new one over it: run `plan` with `--fresh` and the same parts, which
replaces it. When it prints that the other batches wait for the
next run, tell the person how many sessions the sweep will take, and that
running `/masthead:setup` again goes on where it stopped. Go to step 4.

## 4. Send the reviewers

The reviewers are the `architecture-reviewer`, the same agent and the same
seven lenses and two scores every pull request gets: there is no second set.
Each batch goes to three reviewers, one per lens family, sent in one message:

| Family | Lenses |
| -- | -- |
| boundaries | Direction, One way in and out |
| calls-seams | Call shape, Seams |
| builds-upkeep | What each build carries, Leftovers, Tests and checks |

Three reviewers a batch, not one per lens and model: the November 14 trial
sent fourteen and spent most of its room merging what they all found.

Loop:

1. Run `next --ledger <L>`. It prints the next batch as JSON, with `list`,
   the file that names the batch's exact files; the reviewers read that
   list, never a pattern. Exit 5 means every batch is reviewed and exit 6
   means this session has reviewed its share: either way, go to step 5.
2. Send the batch's three reviewers, each with the brief in
   `${CLAUDE_PLUGIN_ROOT}/references/dispatch-brief.md`, **A review of
   existing code**.
3. When all three are back, run
   `done --ledger <L> <batch id> <the three findings files>`.

Where Korium's code index is on, run `korium-cli index` in the checkout
before the first batch, as for any review.

## 5. Send the judge

Send one `adjudicator` for the run, with the judging brief in the same
section of `dispatch-brief.md`: every findings file that
`findings --ledger <L>` prints (each batch reviewed and not yet judged, from
this run or one that ended before its judge), and what `left` prints. When
its verdict is back, run `judged --ledger <L>`, so no batch is judged twice.
When `findings` prints nothing, there is nothing to judge: say so and end. It reads the code at each finding,
gives each one both scores (customer, 1 to 10, and drift, yes or no against
the doc's seven rules), keeps or drops it, and groups the kept ones by cause.
It keeps what is drift, broken today or breaks a build the doc names, and
drops design cost with no drift. Its verdict is the only thing you show.

## 6. Show one row per cause

Show the judge's kept causes as one table, one row per cause, before anything
is filed:

| Cause | Where | Drift | Customer | Breaks | Findings |
| -- | -- | -- | -- | -- | -- |

"Cause" is one plain sentence, "Where" a `file:line` or two, "Drift" yes with
the rule's lens or no, "Customer" the score and who feels it, "Breaks" the
doc line, principle or build it breaks, "Findings" how many it holds. Then
the dropped findings in a short second table, one line each with the judge's
reason, so the person can bring one back. When the run stopped early, say
which parts were not reviewed (`left`), and that `/masthead:setup` goes on
from there.

Ask: "Which of these causes should I file as issues? Name them, say all, or
say none."

## 7. File each cause they approve

On none: say "Nothing filed," and end. You file only what the person names,
and never a cause they did not.

Otherwise run `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/project_fact.py --tracker`
and follow its skill (`linear-issues` on linear, `github-issues` on github)
for every call. Ask once which project, or milestone on GitHub, the issues go
in. Search for each cause before filing it, and file nothing already filed.

Each approved cause is one issue, never one per finding, in the issue shape
those skills give:

- **Title**: what to do, such as "Reach billing data only through
  Billing.Accounts".
- **Why**: the cause in one or two sentences, with its `file:line`s.
- **Scenarios**: one for each build the doc names (the script's
  `builds <doc>` lists them), each "Given <that build>, When <...>, Then
  <...>". When `builds` prints nothing, ask the person which builds the
  project ships, once for the whole filing, and give one scenario for each;
  a project that ships one build gets one scenario for it. When one line
  names more than one build, as one sentence can ("the open build ships the
  core alone; the hosted build adds billing"), split it into a scenario for
  each. Each rests on the doc line the cause breaks, quoted word for word
  from `rules <doc>`, or the principle it breaks, by number.
- **Out of scope**: the other causes, by key once filed.
- **Questions**: what the doc and the code do not settle, as those skills
  say, or "None."

Label it Bug when the judge found it broken today, else Improvement, and give
it the status Backlog. When every approved cause is filed, list each one with
its key or number.
