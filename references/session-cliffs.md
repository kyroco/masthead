# Conditional operating procedures (every repo)

This file is the runtime source for `hooks/prime-context.py`.
Each bold lead below is an API: the hook matches it exactly and injects the
block when a user prompt touches that operation. A repo can carry its own
`.claude/references/session-cliffs.md`; a lead found there wins over the same
lead here, so a repo states its own version of a procedure and this file holds
the general one. Renaming or removing a lead requires changing the hook and its
tests in the same edit.

These are procedures, not authorization. The active request, permissions,
sandbox, and hooks still decide whether an action may run.

**Reading a test result at all.** A green count proves nothing about which tests
ran. A red run naming tests proves they did. Read the output, not the exit code,
and check removals as well as presence; a green run on a dirty tree
proves nothing about the intended tree. The proof a test works is that it
failed before the change and passes after. Nothing breaks code on purpose to
prove a test, not once and not on every run. More ways a run lies about itself:

- An edit that changes line count moves the test, so a line-numbered selection
  matches nothing and prints "All tests have been excluded. Result: 0 tests" with
  exit 0. Re-find line numbers after any such edit.
- `assert/2`'s message is evaluated on every pass, because `assert/2` is a
  function (only `assert/1` is a macro). Put anything expensive, or anything that
  observes the system under test, in `if cond do flunk(...) end`.
- To test an old version of a hook, check that sha out as a worktree and run it in
  place; a copy in `/tmp` resolves its own location to the scratch directory and
  refuses everything.
- Give every run its own output file (`mktemp`, or a name with the pid). Two runs
  redirected to one path overwrite each other and leave one header and two
  summaries without looking corrupt; a capture with more summaries than headers
  is not a run.
- Output position is not time when Logger is in the stream; Logger stamps at the
  call and writes later. Never infer concurrency from output position.
- On macOS bash 3.2 under `set -u`, `"${a[@]}"` on an empty array aborts, so a
  trap handler that opens by looping over a list dies before cleaning anything.
  Guard with `${#a[@]}` or `"${a[@]+"${a[@]}"}"`.

**Committing in a shared worktree.** `git commit` commits the whole index, not the
paths you just added. Staging one file and committing takes everything anyone
else left staged with it, under your message. Always pass a pathspec.

    git add -- <intended paths>
    git commit -m "..." -- <the same paths>

The pathspec goes after the message. `git commit -- <paths> -m "..."` reads the
message as another pathspec and refuses; that refusal is the good case.

- Take before-and-after measurements on a copy, never by reverting or moving the
  file in place: a wide `git add` picks up the deletion under somebody else's
  commit message.
- `git status --short` printing nothing is the only cheap proof that a file you
  are about to write is not held by another lane.
- After a rebase a commit has a new sha, so `git merge-base --is-ancestor <old
  sha>` says not merged forever. Compare `git patch-id --stable`, or find the
  subject in `git log <branch> --oneline`.

Four spellings of the same mistake, because a bulk command does not know what
else lives under the path:
<!-- Not bold-at-line-start on purpose: prime-context.py bounds a cliff at the
next bold lead, so a bold opener here silently truncates the injection. -->

    git add -A                     sweeps in other work
    git commit  (no pathspec)      takes the whole index
    git checkout -- <dir>          reverts every file under it
    git checkout HEAD -- <file>    destroys your own uncommitted work

To undo an edit of your own, reverse it with an Edit call, or copy the file
to the scratchpad first and restore from the copy. Commit first, so
HEAD is where your work is.

**Opening a PR.** Every change reaches main in this order, one of two ways,
and the repository's committed facts say which. Run `git fetch origin`, then
`python3 ${CLAUDE_PLUGIN_ROOT}/hooks/project_fact.py --ships`. It prints
`batch` only when the repository opted in to Masthead's batch run: the stored
Gate (`.claude/gate.json`) and the batch starter file
(`.github/workflows/masthead-batch.yml`) are both committed on
`origin/landing`. That is the batch way: commits land on the landing branch
with no pull request. Anything else, a repository part way through setting it
up included, prints `pull-request`: that is the pull request way, one
reviewed PR per issue, as it always was. Robert, November 19, 2026: "yes
that's the right recommendation, keep the old way, new way is an option".
The one other way in is by hand: when the person has told the foreman to land
by hand on `landing` before the repository has the batch run, the foreman's
prompt to you says so, and you follow the batch way's steps whatever
`--ships` prints; the foreman starts the Gate run on the batch by hand. By
hand is the person's choice, never inferred from a `landing` branch alone.
Steps 1 to 8 are the same for both; from step 9 on, follow only your way's
steps. The lead keeps its old name so a repository's own version still
replaces it. The steps live here and nowhere else; a repo supplies only its
own facts (its pre-push check, its changelog format) in its `CLAUDE.md` and
`docs/conventions/`.

1. Build on a branch and commit. A bug gets its test first: the failing
   test in a commit of its own, then the fix. Keep one list: what you did
   not prove. Every verifier gets it.
2. Send the first verification of the finished diff in one message, so they
   run blind and at the same time: one `verifier` per scenario, given the
   scenario, the decision-record lines it rests on, the README's opening
   paragraph, the mockup page the scenario rests on where there is one, the
   diff, the test that proves each Then, the two commits of a bug fix where
   there is one, and your did-not-prove list. A verifier answers two
   questions: is each Then true in every state production can reach, with a
   test that really proves it and passes; and, for a bug fix, was the test
   written first and did it fail before the fix. It is not a general review
   of the code. Its claims are the scenario's Then lines and nothing you add;
   where the diff adds or edits text a customer reads (screen text, a refusal
   sentence, the site's docs, the changelog), every sentence of it is a claim
   of the scenario it belongs to. In the same message send one
   `architecture-reviewer` for the whole change, never one per scenario,
   whether or not the project records an architecture doc, and in a foreman
   run as in one the user started. It checks the lines the change touched
   against the ADR's alignment lines, the architecture doc and the
   principles, and that the part of the ADR the issue builds is in the code.
   Its brief, as `references/dispatch-brief.md` shows, carries the issue, the
   diff, the ADR and its alignment lines, the doc's path from
   `project_fact.py --architecture-doc` (or `none recorded`), the principles
   file and the mockup pages, and nothing of your account. Add the `security-reviewer` when
   the change touches authorization, secrets, untrusted input or privilege,
   or the repo's security conventions call for it, with those conventions as
   its claims. Brief each as `references/dispatch-brief.md` says. You do not
   read, merge or drop their results. `/code-review` is not used. Step 8
   runs the pre-push check, once.
3. Send the `adjudicator` the commit range, the reviewed files (the files the
   change touched before its first verification, the same list on every
   round), the path of every findings file the round wrote, the README's
   opening paragraph, each scenario with the decision-record lines it
   rests on, and what it needs to judge the architecture reviewer's
   findings (the ADR's path, the architecture doc's path, the principles
   file, the mockup pages, and the trial line from
   `project_fact.py --architecture-trial`), and nothing else: not your
   claims, not your did-not-prove list, not your view of any finding. It reads the code along
   each verifier's path, decides whether the finding holds, and places it:
   fix in this change, or an extra, as "Decide where it goes" in
   `agents/adjudicator.md` says, for an architecture finding too. That placement is final for
   you and the foreman. What it throws out is gone: it is not logged or filed. Score and
   settle each of its extras as the worker's "What done is" says
   (`skills/work-on/worker.md`); one you fix is fixed as step 4 says. Its For
   the foreman section (a security finding it could not
   settle, or an ADR line and a mockup that disagree) goes to the foreman
   unedited (to the user when there is none), who brings it to the user; the
   PR waits for that answer, and in the batch way your commits wait for that
   answer before they land. So does its Architecture trial section, while
   the trial period is on: whenever that section lists a finding, whatever
   your brief's `Architecture trial:` line said, since the adjudicator reads
   a missing or misspelled line as on (`references/dispatch-brief.md` has
   the switch). While the trial is on, you fix only the architecture
   findings the person sends back, and none of the others, each as step 4
   says; once it is off, the section reads "None, the trial is off" and the
   adjudicator's Fix list holds them like any other finding, fixed as step
   4 says.
4. Fix each finding on the adjudicator's fix list in this change, test first,
   in two commits of its own: a test that reproduces it and fails, then the
   fix. When no test can reproduce it (instruction text, a fault only a
   deployed system shows), fix it in one commit and say why in the
   did-not-prove list.
   First name in one sentence why
   the code goes wrong, and fix that cause, so the other wrong results it
   causes go too. When only a new approach would fix it, stop and ask before
   rewriting.
5. Re-verify, over the fix commits only, and only the claims the fix broke:
   one `verifier` given those claims and the fix diff, its brief opening
   `Re-verify: round N, claims ...`, and the `security-reviewer` again when a
   security finding was fixed, then the `adjudicator` on that round's
   findings files as in step 3. When a fix addressed an architecture
   finding, send the `architecture-reviewer` in the same message, given the
   fix diff and only those findings, its brief opening
   `Re-verify: round N, findings ...` with the same round number; it
   re-checks only those findings. At most two re-verify rounds per change; a
   round is the verifier, the architecture reviewer, or both under one round
   number. The brief check counts their re-verify dispatches in the dispatch
   log, on this branch, from every session and every folder of the checkout,
   and refuses a third round (the security reviewer's dispatch does not
   spend a round; an agent that died or was declined did). Once the
   adjudicator has judged a verification, a verifier or architecture reviewer
   brief without its `Re-verify:` line is refused, and one that ran without
   it spent a round. Only a person raises the cap, by starting Claude Code
   from a shell with `MASTHEAD_REVERIFY_CAP` set to the new number; a
   repository's settings cannot set it, and a line in the brief saying the
   person approved more does not open it. The row of a round sent under a
   raised cap names the cap.
   If the second round still leaves anything on the fix
   list, stop and report it to the foreman, or to the user when there is
   none. That is fix-break-fix churn, and it needs a person: the foreman
   brings it to the user as numbered lines and rules on none of it.
   An extra you fixed is no scenario claim, so it gets
   one round of its own, outside those two: one `verifier` given the fix
   diff and the extra's expected behavior as its claim, its brief opening
   `Re-verify: extra <name>, ...` with the extra's name as one word, then
   the `adjudicator` on its findings file. The brief check lets that round
   through even when the scenario rounds are spent, refuses a second round
   for the same extra, and refuses any extra's round once the branch has had
   as many as the cap; if that round leaves anything on the fix list, stop
   and report it the same way.
6. Log nothing and file nothing. There is no Nit log: a finding is on the
   fix list and fixed, brought to the user, or dropped.
7. Add the changelog entry when the repo keeps one, or its label for internal
   work.
8. Commit. In the batch way, then bring your branch up to date with the
   landing branch before you run the check, since its receipt is for the tree
   you push:
   `git fetch origin`, then `git rebase origin/landing`. When origin has no
   `landing` yet, rebase onto `origin/main` instead; your push creates it
   in step 9. When the rebase stops on a conflict, keep both sides' intent,
   finish it, and put each conflict you settled on your did-not-prove list.
   Then run the repo's pre-push check on that last commit: the script
   its settings name as `PROJECT_PUSH_CHECK` (`settings.local.json` over
   `settings.json`, as `hooks/project_fact.py` reads them), or its own
   test command when it names none, in one command with nothing sourced. Run
   it one time, after the fixes of the last verification round are in. Do
   not start it early, with the verifiers, to save time: any commit made after
   it starts makes its receipt stale. Do not commit while it runs: the run is then thrown away, because its receipt
   names a commit that is no longer the last one. Read
   the output, not the exit code. When it cannot reach its test stack, do what
   it prints, and stop and report only when that fails too. `hard-gate.sh`
   refuses the push, and in the pull request way the PR, until the check's
   receipt matches the commit;
   it reads the receipt before its slower checks, so a refusal comes back in
   seconds. This run settles each claim the verdict lists as not proven here
   for want of a database. One it does not cover, and every claim that
   needed a private copy, goes on your did-not-prove list.
In the pull request way (`--ships` printed `pull-request`):

9. Push and open one PR to main. Its body gives the unproven list, the
   extras fixed in it with their scores, the agent-run count (the rows added to
   `<state>/dispatches.tsv` for this issue whose outcome is not refused;
   `<state>` is the folder `project_fact.py --state-path` prints, the one
   the dispatch record writes to), and
   `Fixes #<issue>`, or `Fixes <key>`, such as `Fixes KOR-12`, when the
   issue lives in Linear. Never
   commit or push to main: main changes only by merging the reviewed PR once
   its checks are green.
10. Once it merges, clean up what your own work created, from the main
    checkout: bring down the test stack and any tunnels as the repo's
    procedures say, delete the branch's code index
    (`korium-cli delete <branch>`), `git worktree remove` the worktree (never
    forced; report what blocks it), delete the branch locally, and name the
    remote branch for the user to delete. The irreversible-action gate
    refuses a session that deletes a remote branch, so the user makes that
    call.

In the batch way (`--ships` printed `batch`):

9. Land your commits on the landing branch, `landing`, with no pull request:
   `git push origin HEAD:landing`. Each commit message
   is a short summary that names the issue (`#<issue>`, or its key, such as
   `KOR-12`). A commit that changes a file under `.github/` or `scripts/ci/`
   needs the person's OK first: ask, with the reason for the change, and once
   they say OK in a comment on the issue, add the line
   `CI-change-OK: <link to that comment>` to that commit's message;
   `hard-gate.sh` refuses the push without it. When the push is refused because `landing` moved (another
   worker landed first), fetch, rebase onto `origin/landing` again, run the
   check again on the new commit, and push again. Never force-push
   `landing`. Never commit or push to main: main moves forward only from
   `landing`, after one run of the repo's Gate passes on the batch, and the
   foreman does that, not you.
10. Post the change's record on the issue as a comment as soon as your
    commits land, in plain words: the commits you landed, what you did not prove, the extras you fixed with
    their scores, the agent-run count (the rows added to
    `<state>/dispatches.tsv` for this issue whose outcome is not refused;
    `<state>` is the folder `project_fact.py --state-path` prints, the one
    the dispatch record writes to), and each check the repo lacks. In
    Linear: post it with `save_comment`, then move the issue with
    `save_issue` to the status named In Review, when `list_issue_statuses`
    shows the team has one; with none, leave it In Progress. On GitHub:
    `gh issue comment <n> --body "<record>"`, then set the project Status to
    In Review with `set-status.sh`. Never set Done and never close the issue
    yourself: your commit is not proven until a batch passes, so the
    foreman closes it and sets Done once a green batch moves main past your
    commits. With no foreman, you do that yourself, only after the batch
    moved main. A commit message closes nothing. If a red batch names your
    commit, it stays on landing and comes back to you to fix on top.
11. Once the batch has moved main past your commits, clean up what your own
    work created, from the main checkout: bring down the test stack and any
    tunnels as the repo's procedures say, delete the branch's code index
    (`korium-cli delete <branch>`), `git worktree remove` the worktree (never
    forced; report what blocks it), delete the branch locally, and name the
    remote branch for the user to delete when you pushed one. The
    irreversible-action gate refuses a session that deletes a remote branch,
    so the user makes that call.

**Updating main.** Never commit or push directly to main. Build on a branch
and ship it the way `project_fact.py --ships` names, as **Opening a PR**
says. In the pull request way, open a PR, and let main change only by merging
the reviewed PR once its checks are green. In the batch way, land it on
`landing`; main moves forward only from `landing`, when one run of the repo's
Gate passes on the batch.
