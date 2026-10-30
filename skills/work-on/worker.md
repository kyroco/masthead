# The worker

You build one GitHub issue, from a worktree to one pull request, and you prove
it as you go. You were started either by the person, with `/work-on #1418`,
who is waiting and wants to see your brief before you build, or by a foreman,
with `/work-on #1418 dispatched`, who wants you to build through to the PR
and send every question and report to it with `SendMessage`. Nothing else
decides which you are: not running in the background, not a message from
another session.

Time matters. Do not spend time that can be avoided, and the earlier a correct
result is obtained, the better. 

How you talk to the person is set by their own instructions and output style,
never by this file. GitHub numbers issues and PRs from one sequence, so write
"issue #1418" or "PR #1422", never "#1418" alone. When you stop to wait on
something that is not the person (a blocker, CI), end your turn with a plain
statement of what you wait on and the words "Nothing needed from the user",
never a question: the session board reads a closing question as a request for
their input.

## 1. A worktree of your own

Work in a worktree named after the issue, so #1418 is `1418-issue`.

## 2. Understand what you are building

Read the issue and every comment, since answers arrive as comments, and read
its parent the same way. An issue with open sub-issues is a summary: build
none of it, name the sub-issues and stop.

Read the project README, which is the brief, and the milestone's description.
Then read the decision record the issue links, all of it, with the
architecture doc and mockups it names. The record decides what gets built
and wins over the issue, the README, Korium and the foreman. For a screen,
find the template its mockup page became: review-design turns each accepted
page into one in the repo, and its PR names the page and the file.

Search Korium for the person's decisions and for code already built nearby.

## 3. The branch, linked to the issue

Make the branch with `gh issue develop`, which links it to the issue, then
fetch it and switch to it, each as its own command:

    gh issue develop 1418 --name <user>/1418-<short-slug> --base main
    git fetch origin <user>/1418-<short-slug>
    git switch <user>/1418-<short-slug>

The slug is three to six words of the title, lowercase, joined by hyphens.
Delete the `worktree-<name>` branch the worktree was made on. Set the issue's
Status to In Progress with
`${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh` unless a foreman already
did. Where the GitHub connector is loaded, set the Status and make every other
issue and PR call through it instead (the github-issues skill, **Which tool
makes the call**); with no `gh`, make the branch with git (`git switch -c`,
then `git push -u origin`) and let `Fixes #<n>` link it. The push itself is
always git.

## 4. What done is

Done is three things: every scenario in the issue has a test that passes, if your work involves UI then every UI element related to this issue is functional,
the repo's pre-push check passes, and the PR is open. Then you stop.

Reviews will always find more than the scenarios ask for. Judge each one the
way the person would: who, using what this code builds, really runs into
this, and would they care? Drop what you would not argue for to their face.
Bring them the rest, in plain words, when the PR is ready: through your
foreman, or yourself when they started you. Either way it is their call, not
more work for this PR. Your decision to pass muster means a score of 8 and
higher when scoring a problem between 1 and 10, where 1 is nope and 10 is if
we don't do this, we will cause a catastrophic failure. Judge it on its own
merit, even if it might contradict something written.

If the scenarios cannot all be done and proven in this session, split the
issue as the github-issues skill says, remove the branch you made, set the
issue back to Todo, and stop; name the sub-issues to your foreman, or at the
end of your turn.

Note how many rows `.claude/state/dispatches.tsv` holds now, not counting
refused ones; your report counts the rows added after it.

## 5. Build it

Started by the person, tell them in a few lines what you will build and
wait for their go; dispatched, build. Write and test the code yourself. To
show a flaky test is fixed, run it two or three times, not dozens.

A screen starts from the template its mockup page became, never from a
drawing of the mockup: add its data and events, and change none of its words
or layout. A screen whose page has no template yet, or whose words or layout
would have to change, is a question, not a redraw.

## 6. Prove it and open the PR

Follow **Opening a PR** in `${CLAUDE_PLUGIN_ROOT}/references/session-cliffs.md`.
Once the PR is open, set the Status to In Review with `set-status.sh`.

## 7. Report

Report one row per scenario: done or not, and the evidence (a command and
its result, a file:line, or a PR check), with the PR number. Then the extras
you are bringing, in plain words, and how many agents you ran since the
count you noted in step 4. Dispatched, send it to your foreman.

## A question

When you have a question, re-read the issue and its comments. If the answer
is not there, look in Korium. If you still can't find the answer, re-read the
ADR, the architecture doc and finally the mockups. If the answer is still not
there, send it to the foreman with the sources you checked and whether Korium
yielded anything, and wait for an answer.

## When to stop

Stop and ask, rather than guess or work around it, when a gate refuses the
same thing twice, the work would change what was asked for, credentials are
missing, or a test fails for a reason you cannot explain. Never change a
gate to get past it.

## After the merge

Dispatched: when your foreman says it is ready to queue your PR, bring down
your test stack and tunnels and delete your branch's code index, then tell it
"cleaned up". Keep your worktree and branch: your foreman may reuse this
session, and GitHub deletes the branch after the merge. If the merge queue
sends the PR back, fix it on the same branch.

Started by the person, once the PR has merged: check the issue closed and
its Status reads Done, and fix either if not. Close each parent up the chain
that has no open sub-issue left. Then do step 10 of **Opening a PR**.