# The stored Gate

How a repository's Gate is run, as Masthead's setup stored it after the
person's yes (INFRA-268). The batch run (INFRA-270) and the search for a bad
commit (INFRA-269) read this answer; neither works the Gate out for itself.

## Where it lives

`.claude/gate.json` at the top of the repository, committed with the code, so
a workflow on GitHub and a session on a Mac read the same answer. Only
`/masthead:setup` writes it, through `skills/setup/gate.py store`, and only
after a yes. No repository writes it by hand.

```json
{
  "workflow": ".github/workflows/gate.yml",
  "starts": ["workflow_call", "workflow_dispatch"]
}
```

- `workflow`: the Gate's workflow file, relative to the top of the repository,
  always under `.github/workflows/`.
- `starts`: the ways it can be started on its own, one or both of
  `workflow_call` (another workflow runs it with `uses: ./<workflow>`) and
  `workflow_dispatch` (`gh workflow run <workflow> --ref <branch>`).

## How to read it

- In a Masthead session or script: `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/project_fact.py --gate`
  prints the answer as one line of JSON and exits 0, or prints nothing and
  exits 1. From Python, `project_fact.gate(root)` returns the same dict or
  None. Both check the file names a workflow that exists and at least one way
  to start it.
- In a workflow on GitHub, where Masthead is not installed:
  `jq -r .workflow .claude/gate.json`. Check `starts` holds the way you mean
  to start it.

## When nothing is stored

Exit 1, or None, means the repository ships the way it does today: pull
requests and its own checks, no batch run. Robert, November 19, 2026: "yes
that's the right recommendation, keep the old way, new way is an option".
A reader never guesses the Gate in that case; it says so and stops.
