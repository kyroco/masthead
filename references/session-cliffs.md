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
and check removals as well as presence; a green run on a dirty or mutated tree
proves nothing about the intended tree. More ways a run lies about itself:

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

To undo a mutation, restore your exact edit with an Edit call, or copy the file
to the scratchpad first and restore from the copy. Commit before mutating, so
HEAD is where your work is.

**Opening a PR.** Every change reaches main through one reviewed PR, in this
order. The steps live here and nowhere else; a repo supplies only its own facts
(its pre-push check, its changelog format) in its
`CLAUDE.md` and `docs/conventions/`.

1. Build on a branch and commit. Keep two lists: what you claim works, and what
   you did not prove. Every verifier gets both.
2. Send the first verification of the finished diff in one message, so they
   run blind and at the same time: one `verifier` per scenario, given the
   scenario, the decision-record lines it rests on, the diff and both lists;
   every sentence a customer reads that the diff adds or edits text a customer
   reads in (screen text, a refusal sentence, the site's docs, the changelog)
   is a claim of the scenario it belongs to. Add the `security-reviewer` when
   the change touches authorization, secrets, untrusted input or privilege,
   or the repo's security conventions call for it, with those conventions as
   its claims. Brief each as `references/dispatch-brief.md` says. You do not
   read, merge or drop their results. `/code-review` is not used.
3. Send the `adjudicator` the commit range, the reviewed files (the files the
   change touched before its first verification, the same list on every
   round) and the path of every findings file the round wrote, and nothing
   else: not your claims, not your did-not-prove list, not your view of any
   finding. It runs each reproduction a verifier showed where it can,
   confirms the claim is false, and places it: fix in this PR, or new issue.
   That placement is final. What it throws out is gone: it is not logged or
   filed. File each finding on its New issue list as its own issue, as the
   repo's tracker skill says, in the same milestone and blocked by this one,
   and link it in the PR body; fix none of them here, and never ask for one
   to be fixed here. Its For the foreman section (a security finding it
   could not settle) goes to the foreman unedited (to the user when there is
   none), who decides; the PR waits for that answer.
4. Fix each finding on the adjudicator's fix list in this PR, test first,
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
   findings files as in step 3. At most two re-verify rounds per change;
   the brief check counts them in the dispatch log and refuses a third. If
   the second round still leaves anything on the fix list, stop and report
   it to the foreman, or to the user when there is none. That is
   fix-break-fix churn, and it needs a person.
6. Log nothing. There is no Nit log: a finding is either on the fix list and
   fixed, or thrown out.
7. Add the changelog entry when the repo keeps one, or its label for internal
   work.
8. Commit, then run the repo's pre-push check on that last commit: the script
   its `.claude/settings.json` env names as `PROJECT_PUSH_CHECK`, or its own
   test command when it names none, in one command with nothing sourced. Read
   the output, not the exit code. When it cannot reach its test stack, do what
   it prints, and stop and report only when that fails too. `hard-gate.sh`
   refuses the push and the PR until the check's receipt matches the commit.
9. Push and open one PR to main. Its body gives the unproven list, the
   agent-run count (the rows added to `<state>/dispatches.tsv` for this
   issue), and `Fixes #<issue>`. Never
   commit or push to main: main changes only by merging the reviewed PR once
   its checks are green.
10. Once it merges, clean up what your own work created, from the main
    checkout: bring down the test stack and any tunnels as the repo's
    procedures say, delete the branch's code index
    (`korium-cli delete <branch>`), `git worktree remove` the worktree (never
    forced; report what blocks it), and delete the branch locally and on the
    remote.

**Updating main.** Never commit or push directly to main. Build on a branch,
open a PR, and let main change only by merging the reviewed PR once its checks
are green.
