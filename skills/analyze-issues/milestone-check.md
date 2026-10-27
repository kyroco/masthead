# The milestone brief

Sent to one `general-purpose` agent with `model: "opus"`, after every
per-issue agent is back. Fill in the names and the Korium line, and send the
rest as written.

```
Model-choice: opus, this checks every issue of a milestone against the whole ADR, fixes copying mistakes and verifies size, and no later step checks it.
no code change
This checks and corrects GitHub issues; it changes no file in the repo.

Korium: <what this session's agent_search found, or that it found nothing>.

Check <milestone or project> in <repo> as one body of work before any of it
is built. Read, in full: the project README, the decision records and design
documents it names, the mockup pages the issues name, and every open issue with its comments
(`gh issue list --milestone "<title>"`, then `gh issue view <n> --comments`).
For each issue edited today, read its body before the edit from the
edit history:
gh api graphql -f query='{repository(owner:"<owner>",name:"<name>"){issue(number:<n>){userContentEdits(first:10){nodes{editedAt diff}}}}}'

Fix these yourself, on GitHub:

1. A copying mistake: a line the user wrote that is gone, a history
   block, Screens paragraph or :start/:end block that changed, or a
   placeholder ("as in section 2") where the text belongs. Put back the old
   text exactly.
2. A blocked-by link between these issues that is missing or wrong.

Each fix rests on a line you quote from the ADR, the architecture doc, the
mockups or the old body. If no line settles it, do not change it: report
it. Write the new body to a file inside the checkout, then edit with
`gh issue edit <n> --body-file <path>`, the one form the edit check reads.

Report, and change nothing for, these:

3. Two issues that build the same thing, or one that undoes another.
4. An issue that contradicts the ADR: quote the issue line and the ADR line.
5. A gap: a decision the ADR makes for this stage that no issue builds.
6. Size: an issue or sub-issue that does not fit one worker session by the Size rule
   in ${CLAUDE_PLUGIN_ROOT}/skills/github-issues/SKILL.md. Check every
   issue and every sub-issue, and name each one that does not fit, with the
   reason (what it touches).

Nothing else is a finding: not wording, not a design you would prefer.
Finding nothing is a fine result.

Capture your report in Korium with agent_capture, every quote in full. Then
return, in under 500 words: each fix (the issue, what you changed, the line
it rests on), each finding in one or two lines with the issue numbers and
where its lines are, what you could not read, and the thought_id.
```
