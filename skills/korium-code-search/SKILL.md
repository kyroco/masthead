---
name: korium-code-search
description: How to search your own indexed repository in Korium with the code_locate tool, and what to do when the answer is empty or out of date. Read this before hunting for where something is defined in a large repo. Triggers on the specific multi-word phrases "search the code index", "korium code search", "where is this function defined", "find the symbol in korium", and "code index returned nothing". NOT triggered by bare "search" or bare "find" - those words alone must never activate this skill.
---

# Korium code search

The search tool, whose name ends in `code_locate`, searches the symbol index built
from your repository. It answers with ranked locations: file, line span, and the
commit the index was built from. It never returns your code, because the index
never held any.

The map is built by `korium-cli index`. An empty answer can mean the wrong
repository identity, a missing index, an unsupported file type, or a query that
did not find the symbol. Those need different next steps.

## Building the index first

Indexing is the command line client's job, not something to ask an assistant to
do over the connection:

```
korium-cli index --repo-root .
```

Run it once to start, then whenever you want the index to catch up. Add
`--dry-run` first if you want to see what it would send without sending it.

Many teams wire this to a git hook so it runs at commit time and nobody has to
remember. That is a per-person choice; the command is the same either way.

The default publication check is bounded. Exit zero can mean the upload finished
while publication is still unverified; read the final message and search for a
known symbol at the expected commit. `--no-wait` never proves publication.

Each branch has its own index. `korium-cli index` indexes the branch the checkout
is on, and indexing one branch never replaces another. A search that names no
branch reads the repository's trunk: the branch the remote (`origin`) points at.
Korium removes a branch's index once nobody has indexed that branch for 14 days,
and never removes the trunk's that way. The tool whose name ends in
`code_repositories` lists the indexes this workspace holds, branch by branch. See
the [release checks](https://kyroco.ai/docs/korium/release-status.html#code)
before upgrading hooks, and use the installed release's help for available flags.

## Your first query

Three arguments are required.

| Argument | What to pass |
|---|---|
| `query` | Prefer a likely symbol or identifier, with enough context to distinguish it. |
| `repo` | The canonical repository identity printed by the indexer, such as `rootsha:<root commit sha>`. |
| `head_sha` | The commit you have checked out, exactly. `git rev-parse HEAD`. |

Optional: `branch` names the branch whose index to search (the trunk when you
leave it out), `rel_path` narrows to one file, `limit` sets the page size (10 by
default, 50 at most).

`head_sha` is required on purpose. The search resolves the index for that exact
commit, so the answer either matches the code in front of you or says plainly
that it does not.

## Reading the answer

Each result carries a file and a line span plus the commit the index was built
from. Treat the span as a pointer: open the file and read it. Nothing in the
index is a copy of your code.

The answer carries a staleness signal, and a plain warning sentence appears when
it is stale:

- **fresh**: the index matches the commit you are on.
- **anchor candidates**: the results come from an older build of the index. The
  symbol may have moved. Open the file before trusting the line numbers.
- **sha miss**: nothing was indexed for this exact commit.
- **branch unknown**: the repository is indexed, but not for the branch you
  named.

When the index is missing or behind, the answer also carries `next_step`: the
command to run, why, and how. Run it in the checkout, or ask the person to, then
search again with `branch` set to the branch the checkout is on.

Always read the file before editing. A matching commit does not certify an
uncommitted working tree, and an older span may have moved.

## An empty result

An empty result does not establish that the symbol or the index is absent. Check
the reason, then the query and file coverage. The index holds code symbols in
Elixir, Rust, Swift, Python, shell, JavaScript, TypeScript, Go, Java and Ruby,
plus YAML, TOML and JSON keys, Terraform and HCL blocks, SQL CREATE statements,
justfile recipes, Dockerfile stages, Cedar policies and XML keys. Markdown,
HTML and `.heex` are not indexed, nor are values, comments or callers of a
name; those need local text search, not a differently worded symbol query.

Retry once with a plainer `query` and no `rel_path`. A search narrowed to a file
with no indexed symbols comes back empty for a reason that has nothing to do with
the index as a whole.

If it is still empty, **read `staleness.reason` before you do anything**. It
separates a question about the index from a question about what you asked for,
and they have different answers.

### `repo_unknown` - you named a repository Korium does not have

Do NOT index before you look. Nothing here is filed under the `repo` you passed, which
usually means the identity is wrong rather than the index missing. The answer
carries `known_repositories`: the repositories that do exist, each with the
commit it is serving. Look for yours there and pass that `fingerprint` value as
`repo`. Index only when the answer carries `next_step`; it is left off whenever
the answer cannot tell a wrong name from a missing index.

`repo` takes a plain name or a tagged fingerprint - `rootsha:<root commit sha>`,
`origin:<host>/<path>`, `display:<name>` - and a bare name only matches a
repository indexed under that plain name. A repository indexed by `korium-cli` is
filed under `rootsha:`, so asking for it by its directory name finds nothing.

Three shapes to read carefully:

- `known_branches` is present: the repository is indexed, but it has no trunk,
  so a search that names no branch has nothing to read. Send one of
  `known_branches` as `branch`, or index the repository's default branch.
- `known_repositories` is `[]`: this account really has indexed nothing. Now
  indexing is the right move.
- `known_repositories_truncated` is `true`: you are seeing the most recently used
  ones and there are more, so a repository missing from the list may still exist.

### `sha_miss` - the repository is here, this commit is not indexed

No index is serving that commit yet: either an index of it is still being
processed, or nobody has indexed it. Run `korium-cli index` in the checkout, as
`next_step` says, then search again with `branch` set to the branch the checkout
is on. A finished upload is not proof the new index is searchable yet; search
for a symbol you know at the expected commit.

### `branch_unknown` - the repository is here, that branch is not

`known_branches` lists the branches Korium holds for this repository. Send one
of those as `branch`, or index the branch you named by running `korium-cli index`
in a checkout of it.

## What not to do

- Do not go back to searching the whole tree by hand because one query came back
  empty. Read `staleness.reason` first, then do what it asks for.
- Do not index on a `repo_unknown` that carries no `next_step`. That answer
  means the repository you named is not here, and indexing rebuilds something
  that may already be indexed and answering under a name you did not use. It
  cost a real session forty minutes.
- Do not pass a `head_sha` from memory. A commit you did not read from the
  working tree turns a stale answer into one that looks fresh.
- Do not treat a line span as the code. Open the file. Spans age, files move, and
  the answer tells you when it is behind rather than guessing for you.
