# The worker

You build one GitHub issue, from a worktree to commits landed on the
`landing` branch, and you prove it as you go. No pull request is opened. You were started either by the person, with `/work-on #1418`,
who is waiting and wants to see your brief before you build, or by a foreman,
with `/work-on #1418 dispatched`, who wants you to build through to the landing
and send every question and report to it with `SendMessage`. Nothing else
decides which you are: not running in the background, not a message from
another session. In a repo whose issues live in Linear, the issue is a key
such as `KOR-12` in place of `#1418`, and **On Linear** at the end of this
file says which steps change.

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

When your foreman's prompt names a warm build ("Warm build: <tree path>"),
clone it into your worktree now, from the worktree's top folder, before any
command that fetches or builds:

    ${CLAUDE_PLUGIN_ROOT}/skills/work-on/warm-build.sh clone <tree path>

It clones the foreman's built output (for example the dependencies, `_build`
and the Rust `target` folders) with an APFS clone, which takes a few seconds
and no extra disk until a file changes, and keeps anything your worktree
already has. Your first build then compiles only your own code and what
differs from the warm tree. Exit 3 says why it cloned nothing (the tree is
not ready, belongs to another repository, or is on another disk, where a
clone would be a full copy): build cold, as you would with no warm build.
Never clone a build from the main checkout or from another worker's
worktree: only the tree your foreman names.

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

Done is five things: every scenario in the issue has a test that passes, if
your work involves UI then every UI element related to this issue is
functional, the repo's pre-push check passes, the commits are on `landing`,
and the change's record is a comment on the issue. Then you stop.

Reviews will always find more than the scenarios ask for, and so will you:
each such thing is an extra. Score each one from 1 to 10 the way the person
would: who, using what this code builds, really runs into this, and would
they care? 1 is nope, and 10 is if we don't do this, we will cause a
catastrophic failure. Judge it on its own merit, even if it might contradict
something written. An extra that scores 8 or more is fixed in this change, test
first when it is a bug, and its fix is verified in a round of its own (step
5 of **Opening a PR**). One that scores under 8 is dropped: you bring it to
no one, not your foreman and not the person, and you file nothing. An
architecture finding the adjudicator lists as an extra is scored as "Decide
where it goes" in `agents/adjudicator.md` says.

If the scenarios cannot all be done and proven in this session, split the
issue as the github-issues skill says, remove the branch you made, set the
issue back to Todo, and stop; name the sub-issues to your foreman, or at the
end of your turn.

Note how many rows the dispatch log holds now, not counting refused ones;
your report counts the rows added after it. The log is
`<state>/dispatches.tsv`, as step 10 of **Opening a PR** says.

## 5. Build it

Started by the person, tell them in a few lines what you will build and
wait for their go; dispatched, build. Write and test the code yourself. To
show a flaky test is fixed, run it two or three times, not dozens.

A screen starts from the template its mockup page became, never from a
drawing of the mockup: add its data and events, and change none of its words
or layout. A screen whose page has no template yet, or whose words or layout
would have to change, is a question, not a redraw.

## 6. Prove it, land it and close the issue

Follow **Opening a PR**, step by step, as this command prints it from your
worktree:

    python3 ${CLAUDE_PLUGIN_ROOT}/hooks/prime-context.py show "Opening a PR"

It prints the same steps the hook injects: your repository's own version when
its `.claude/references/session-cliffs.md` has that lead, otherwise the
plugin's. Its step 8 says when to run the pre-push check.
Its steps 9 and 10 land the commits on `landing` and put the change's
record on the issue as a comment, which takes the place of a pull request.
The issue closes later, when a green batch moves main.

## 7. Report

Report one row per scenario: done or not, and the evidence (a command and
its result, a file:line, or a check), with the commits you landed. Then each extra
you fixed, in plain words, with its score and its test; how many you dropped
under 8, as a count; and how many agents you ran since the count you noted in
step 4. Dispatched, send it to your foreman.

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

Dispatched: when your foreman says the batch holding your commits moved
main, bring down your test stack and tunnels and delete your branch's code
index, then tell it "cleaned up". Keep your worktree and branch: your foreman may reuse this
session. If a batch drops your commit and the foreman hands it back, fix it
on the same branch and land it again.

Started by the person, once the batch has moved main past your commits:
check the issue is closed and its Status reads Done, and fix either if not.
Close each parent up the chain that has no open sub-issue left. Then do step 11 of **Opening a PR**.

## On Linear

When `project_fact.py --tracker` prints `linear`, the issue lives in Linear
and every issue, project and status call goes through the Linear connector,
as the `linear-issues` skill says. The code, CI and the decision records
stay on GitHub. Every step above holds, with these changes,
shown for KOR-12:

- **Naming.** Write the key, "KOR-12", never a `#` number.
- **Step 1.** The worktree for KOR-12 is `KOR-12-issue`.
- **Step 2.** Read the issue with `get_issue` with `id` the key, then
  `list_comments` with `issueId` the key, and read every comment. Read its
  parent (`parentId`) the same way. The Linear project's description is the
  brief, in place of the project README: read it with `get_project`, and the
  milestone's description where the project has milestones.
- **Step 3.** The branch is the one `get_issue` returns as `gitBranchName`;
  it holds the key, so Linear links the branch to the issue. Make
  it with `git switch -c <gitBranchName>`, then
  `git push -u origin <gitBranchName>`, never `gh issue develop`. Set the
  status with `save_issue` with `id` the key and `state` `In Progress`, unless
  a foreman already did, and never `set-status.sh`, which knows only GitHub
  projects.
- **Step 4.** A split follows the `linear-issues` skill, and the issue goes
  back to `Todo` with `save_issue`.
- **Step 6.** Each commit message names `KOR-12`. A commit message moves
  nothing in Linear, so step 10 of **Opening a PR** has you post the change's
  record with `save_comment`, then set `In Review` with `save_issue` when the
  team has that status.
- **A question.** When nothing answers it, set the issue's status to
  `Needs Human` with `save_issue` before you ask, whether you ask the person
  or your foreman. When the answer comes back, put the answer on the issue as
  a comment in the words it came in, and set the status back to
  `In Progress`.
- **After the merge.** Check the issue's status reads Done once the batch
  moved main, and set it with `save_issue` if not. A parent with no open sub-issue left is set to
  Done the same way.

On a repository whose issues live on GitHub, none of this section applies.