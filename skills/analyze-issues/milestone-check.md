
# The milestone brief

Sent to one `reader` agent with `model: "opus"`, effort `high`, after every
per-issue report is back. Fill in the names, the Korium ids and the Korium
line, and send the rest as written.

```
Model-choice: opus, this judges every issue of a milestone against the whole ADR at once, and no later step checks it.
read_only: true
This is a reading and judging job; you change no file and no issue.

Korium: <what this session's agent_search found, or that it found nothing>.

Check <milestone or project> in <repo> as one body of work before any of it
is built. Read, in full: the project README, the decision records and design
documents it names, every open issue with its comments (`gh issue list --milestone "<title>"`,
then `gh issue view <n> --comments` for each), and the per-issue reports in
Korium: <ids>.

Report only these, each with the issue numbers and the line it rests on:

1. Two issues that build the same thing, or one that undoes another.
2. An issue that contradicts the ADR: quote the issue line and the ADR line.
3. A gap: a decision the ADR makes for this stage that no issue builds.
4. Order: a blocked-by link that is missing, or one that is wrong.

Nothing else is a finding: not wording, not size (the per-issue checks hold
size), not a design you would prefer. Finding nothing is a fine result.

Capture your report in Korium with agent_capture, with every quote in full.
Then return, in under 500 words, each finding in one or two lines with the
issue numbers and where its lines are, what you could not read, and the
thought_id.
```
