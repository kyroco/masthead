---
name: github-issues
description: How work is tracked in GitHub issues and projects - how projects, milestones and issues are laid out, what an issue must say, how one is filed and worked. Read before filing an issue, creating a milestone or project, or turning a plan into issues.
---

# GitHub issues

GitHub is the tracker. An issue lives in the repository its work belongs to,
and takes that repository's visibility: never put a secret, a customer's name
or an unfixed security weakness in an issue on a public repository. A
repository may carry its own tracker notes (its `CLAUDE.md` or a file under
`.claude/references/`); where it does, those bind.

## Structure

**A GitHub project is the container for a body of work.** Issues are added to
it. There are no epics; a project is the epic. Each project carries a Status
field (Backlog, Todo, In Progress, In Review, Done, Canceled, and Duplicate
where needed) and a Priority field (Urgent, High, Medium, Low).

**The project README is the whole brief.** Someone picking the work up cold
reads the project README and knows why the work exists, what its shape is, and
what the rules are. An issue carries one step, not the context for the step. A
session that reads only an issue builds the wrong thing.

**Milestones belong to the repository, so their name says which project they
are part of.** Every milestone is named `<project>: <number>. <name>`, for
example `Observability: 2. Connect the metrics, logs second`. Sorted by name,
a project's milestones sit together in build order. Use a hyphen, never a long
dash, in the name. A milestone's description says what it delivers and its
`Done when:`.

**Order lives in the issues, not the project.** When steps have to happen in
sequence, say so per issue with a blocked-by link, and say what the blocking
condition actually is. Do not rely on the list order in the UI. A parent issue
with sub-issues is how one issue is split; GitHub allows 100 sub-issues per
parent.

## House style

Everything written into the tracker is read by a person later, usually cold.

- Say what to DO. A title is a thing to be done, not a topic.
- Never invent state to fill a gap. A dash beats a zero.
- Give the file and line when you know it. `dispatch.ex:84` saves a search.

## What an issue holds

An issue says what is true when the work is done, never how the code gets
there. Four parts, in this order, under these headings:

- **Why:** one or two sentences: what a person cannot do today, or what goes
  wrong, with the file and line when known.
- **Scenarios:** one to five lines, each a thing a test can show, written
  "Given <starting state>, When <what happens>, Then <what is true>", and
  each naming what it rests on: a decision record, a project README rule, or
  the user's words quoted. Nothing about modules, calls or where a check runs:
  that is the worker's plan, written before code and checked by the foreman.
- **Out of scope:** what this issue leaves to another, by number when it
  exists.
- **Questions:** what the decision records, the README and memory do not
  settle, each as `[NEEDS CLARIFICATION: the question]`. Never guess an
  answer into a scenario. An issue with one open carries the
  `needs-decision` label and is not dispatched.

Done is the same for every issue and is not restated in one: every scenario
has a passing test, and the repository's pre-push check passes on the PR's
head.

**Size.** One issue is one PR, built and proved by one worker in one fresh
session. Split it the way scrum splits user stories, into thin slices that
each work on their own and fit one worker session. Then merge neighbouring
slices that share a file until each fills one worker session with room to
spare.

## Filing

Use `gh` where there is a terminal; in Claude Desktop, use the GitHub
connector's tools for the same calls. `<org>` is the repository's owner.

- Check first that it is not already filed:
  `gh issue list --search "<words>" --state all`.
- `gh issue create --repo <repo> --title "..." --body-file <file> --milestone "<milestone title>"`,
  then add it to its project: `gh project item-add <project number> --owner <org> --url <issue url>`.
- Set Status and Priority on the project. Status:
  `${CLAUDE_PLUGIN_ROOT}/skills/work-on/set-status.sh <n> "Backlog"`. Leave
  Priority empty unless there is a reason.
- Labels: `Bug`, `Feature` or `Improvement` for the kind of work (an existing
  `bug` label serves as Bug), plus any topic label already in the repository.
- A blocked-by link for a real sequence dependency, never for "this would be
  tidier after that":
  `gh api -X POST repos/<repo>/issues/<blocked>/dependencies/blocked_by -F issue_id=<blocker's id>`
  (the id is `gh api repos/<repo>/issues/<n> --jq .id`, not the number).
- A sub-issue: `gh api -X POST repos/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child's id>`.
- A new milestone: `gh api -X POST repos/<repo>/milestones -f title="<project>: <n>. <name>" -f description="..."`.
- A new project: `gh project create --owner <org> --title "<name>"`, then link
  it to its repository (`gh project link <number> --owner <org> --repo <repo>`)
  and write its README with the brief.

## Working an issue

- **One command.** `/work-on #<n>` from a session in the repository the issue
  lives in. The skill makes the worktree, reads the issue and its project
  README, makes a branch linked to the issue (`<user>/<n>-short-title`, with
  `gh issue develop`), and sets the Status to In Progress.
- **One checkout per issue**, deleted when the pull request merges.
- **One issue per session.** A session works one issue and nothing else, which
  is about the quality of its answers.
- **Status.** Nothing moves an issue's Status on its own when a branch is made
  or pushed; `/work-on` sets In Progress. `Fixes #<n>` in the pull request
  body closes the issue on merge. When a PR has merged and its `Fixes` line
  did not close the issue, close it and set the Status to Done, and say so.
- **`refs #<n>`** when a change touches an issue without finishing it.
- **"Close it" means closed as completed** when the issue's work shipped.
  Closed as not planned is only for work that will not be done, and only when
  the user says so in those words.

## Project status is a decision, not decoration

One project is being worked at a time, and it has a target date in its README.
Everything else waits on purpose.

Scope a project to one to three weeks. If it will not fit, break it into stages
and make the first stage the project. A backlog is a list of decisions still to
make; if you would not start it this quarter, close it.
