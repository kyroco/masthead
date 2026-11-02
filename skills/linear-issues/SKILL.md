---
name: linear-issues
description: How work is tracked in Linear - how projects, issues and statuses are laid out, what an issue must say, and which Linear call makes each action. Read before filing, reading or working an issue in a repository whose issues live in Linear.
---

# Linear issues

A repository keeps its issues in one tracker, GitHub or Linear, never both.
First ask which: `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/project_fact.py --tracker`
prints `github` or `linear`. On `github`, this skill does not apply: read the
`github-issues` skill instead, and never file or look for this repository's
work in Linear.

On `linear`, every issue, project and status lives in Linear, on the team whose
key `/masthead:setup` wrote as `LINEAR_TEAM_KEY` (the letters before the number
in an issue like `KOR-12`). Pull requests, CI, the merge queue and the
decision records stay on GitHub; only issues and projects live in Linear.

## Structure

**A Linear project is the container for a body of work.** Issues are added to
it. There are no epics; a project is the epic.

**The project description is the whole brief.** Someone picking the work up
cold reads the project description and knows why the work exists, what its
shape is, and what the rules are. An issue carries one step, not the context
for the step. A session that reads only an issue builds the wrong thing. Keep
the project's summary to one or two sentences; the description holds the rest.

**Milestones only where a project has real stages**, such as build, test,
deploy, or parts of a large body of work that ship one after another. A
project with no stages has no milestones.

**Order lives in the issues, through blocked-by links.** When steps have to
happen in sequence, link each issue to the one it waits on, and say in the
issue what the blocking condition actually is. A wait on another issue is a
blocked-by link, never a status. Do not rely on the list order in the UI. A
parent issue with sub-issues is how one issue is split.

**Statuses.** Issue statuses are set once on the parent team and every
sub-team inherits them: Backlog, Todo, In Progress, Needs Human, In Review,
Done, Canceled, Duplicate. Needs Human means the issue waits on a person: a
question or a decision. Project statuses: Backlog, Planned, Design Review, In
Progress, Completed, Canceled. Design Review is when `/review-design` and
`/analyze-issues` run, just before a project starts; a reviewed project left
waiting goes back to Planned. The Linear connector cannot add a status or
change a team's settings; a person does that in Linear.

## House style

Everything written into the tracker is read by a person later, usually cold.

- Say what to DO. A title is a thing to be done, not a topic.
- Never invent state to fill a gap. A dash beats a zero.
- Give the file and line when you know it. `dispatch.ex:84` saves a search.

## What an issue holds

An issue says what is true when the work is done, never how the code gets
there. Four parts, in this order, under these headings, the same as on GitHub:

- **Why:** one or two sentences: what a person cannot do today, or what goes
  wrong, with the file and line when known.
- **Scenarios:** at least one, each a thing a test can show, written
  "Given <starting state>, When <what happens>, Then <what is true>", and
  each naming what it rests on: a decision record, a rule in the project
  description, or the user's words quoted. Nothing about modules, calls or
  where a check runs: that is the worker's to decide when it builds.
- **Out of scope:** what this issue leaves to another, by key when it exists.
- **Questions:** what the decision records, the project description and
  memory do not settle, each as `[NEEDS CLARIFICATION: the question; looked in: <decision-record section>, <project description rule>, Korium "<query>"]`,
  naming where the answer was looked for first. Never guess an answer into a
  scenario.

**An issue with an open question has the status Needs Human**, not a label,
and is not dispatched. When the question is answered, put the answer on the
issue as a comment in the person's words and move it back to Todo.

Done is the same for every issue and is not restated in one: every scenario
has a passing test, and the repository's pre-push check passes on the PR's
head.

**Size.** One issue is one PR, built and proved by one worker in one fresh
session, sliced and merged as the `github-issues` skill's Size rule says.

## Which Linear call makes each action

Every call goes through the Linear connector (its tools show as
`mcp__<server>__get_issue` and the like). An issue is named by its key, such
as `KOR-12`. Commits and pushes still go through git, and pull requests and
the merge queue through GitHub, as the `github-issues` skill says.

| Action | GitHub form | Linear call |
|---|---|---|
| Read an issue with its comments | `gh issue view <n> --comments` | `get_issue` with `id` the key, then `list_comments` with `issueId` the key. Answers arrive as comments, so read every one |
| Search | `gh issue list --search "<words>" --state all` | `list_issues` with `query` the words and `team` the team key; add `includeArchived` true to see old work too |
| Create | `gh issue create` | `save_issue` with no `id`, plus `team`, `title`, `description`, `project`, and `state` `Backlog` |
| Edit the body | `gh issue edit <n> --body-file <path>` | `get_issue` first, then `save_issue` with `id` and `patch`, which changes only the text it names. `description` replaces the whole body, so use it only when rewriting all of it, and keep every quoted line of the person's word for word |
| Set the status | `set-status.sh <n> "<Status>"` | `save_issue` with `id` and `state` the status name, such as `In Progress` |
| Add a blocked-by link | `gh api .../dependencies/blocked_by` | `save_issue` with `id` the waiting issue and `blockedBy` the keys it waits on. It only adds; `removeBlockedBy` takes one away |
| Add a sub-issue | `gh api .../sub_issues` | `save_issue` with `id` the child and `parentId` the parent's key |
| Comment | `gh issue comment <n>` | `save_comment` with `issueId` the key and `body` |
| List what an issue blocks | `gh api .../dependencies/blocking` | `get_issue` with `includeRelations` true; the answer's `relations.blocks` lists them, and `relations.blockedBy` what it waits on |
| Add a label | `gh issue edit <n> --add-label <label>` | `save_issue` with `id` and `addLabels`. `labels` replaces the whole set, so never pass it to add one |
| Read the project brief | the project README | `get_project` with `query` the project name, and `includeMilestones` true |
| Create a project | `gh project create` | `save_project` with `name`, `addTeams` the team, `summary`, `description` the brief, and `state` `Backlog` |
| Create a milestone | `gh api .../milestones` | `save_milestone` with the project, only where the project has real stages |

## Filing

- Check first that it is not already filed: `list_issues` with `query`.
- Create it with `save_issue` in its project, with status Backlog. Leave
  priority empty unless there is a reason.
- Labels: `Bug`, `Feature` or `Improvement` for the kind of work, plus any
  topic label the team already has, with `addLabels`.
- A blocked-by link for a real sequence dependency, never for "this would be
  tidier after that". A follow-up filed from a PR's review is blocked by the
  issue whose review found it, and only the user files one, by answering "fix
  later" to its line; no agent files an issue from a review on its own.
- An open question: status Needs Human, as **What an issue holds** says.

## Working an issue

- **One command.** `/work-on <key>`, such as `/work-on KOR-12`, from a
  session in the repository the issue belongs to.
- **The branch** is the one Linear names: `get_issue` returns it as
  `gitBranchName`. Make it with git (`git switch -c <name>`, then
  `git push -u origin <name>`); Linear links a branch and PR that carry the
  key.
- **One checkout per issue**, deleted when the pull request merges, and **one
  issue per session**.
- **Status.** `/work-on` sets In Progress, and sets In Review once the PR is
  open: Linear does not move it there on its own. `Fixes <key>` in the PR body
  moves the issue to Done when the PR merges. When it did not, set Done
  yourself and say so.
- **`refs <key>`** when a change touches an issue without finishing it.
- **"Close it" means Done** when the issue's work shipped. Canceled is only
  for work that will not be done, and only when the user says so in those
  words.
