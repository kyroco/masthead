# Claude gate catalog

This is the human-readable catalog, not the enforcement surface. Hook code and
tests decide behavior. Korium holds the dated measurements, incidents and
rejected alternatives behind these rows.

Every gate runs from the plugin's `hooks/` folder, in every repo: wired by
`hooks/hooks.json` and proven by `bash hooks/run-tests.sh`, in CI and on any
machine. A repo holds no hooks. It states facts about itself in
the `env` block of its own `.claude/settings.json`, and
`hooks/project_fact.py` reads them: `ADR_DIR`, `ADR_REMOTE`,
`PROJECT_ELIXIR_ROOT`, `PROJECT_TOOLCHAIN_ENV`, `PROJECT_PUSH_CHECK` and
`PROJECT_STATE_DIR` (the folder the workflow keeps its per-checkout state in,
the scope file, review findings and lane locks: `.claude/state` when the repo
states none). A repo that states none still
gets every gate; the ones that need a fact look for it or stand aside. Facts are
read only from the session's own repository (its folder and that repository's
other worktrees): a fact names a file to source or a script to run, so a clone
the session changes into is never read. Its procedures in
`.claude/references/session-cliffs.md` are ignored for the same reason.

Every PreToolUse gate carries `"onFailure": "block"`: a gate that crashes, times
out or prints unreadable output blocks the action instead of letting it through.
Such a block carries no reason, so a refusal with no message means a gate
broke. The gates' own guards for missing input (no jq, empty stdin) still allow.
The commit attribution gate runs only on commands containing `commit` or `gh`,
and the two code-search gates only on ones containing `rg` or `grep` (hook `if`
filters); the push gate is not filtered, because two matching filters run a
gate twice.

## File, reply, and secret gates

| Gate | Current job | Known limit |
|---|---|---|
| `hooks/block-secret-reads.py` | Refuses any read of a credential file, the masked reader included, and says to ask the user | Matches paths and command text; the secrets convention remains the policy source |
| `hooks/block-secret-fetches.py` | Refuses commands that fetch a credential out of a secret store | Matches command text |
| `hooks/scan-tool-output-for-secrets.py` | Warns when a tool result carries something shaped like a credential | A backstop after the fact; it cannot unsee the output |

## Korium and dispatch gates

| Gate | Current job | Known limit |
|---|---|---|
| `hooks/engram-protocol.sh gate-edit` | Requires a Korium search before the first edit, and a second wording when the first found nothing | Cannot judge whether the search was about the task; no model judge |
| `hooks/engram-protocol.sh gate-discovery` | Refuses a Grep, Glob or shell `rg`/`grep` for a name the code index holds until a fresh `code_locate` lookup of it; a stale answer means reindex and search again. A plain-word Grep or shell search it lets through is told where the index holds any of its words as a name | `korium-index-judge.py` asks the index itself with `korium-cli` (status first, so a signed-out Mac never gets a browser sign-in), only for code-shaped words, and refuses on an exact match. A name the index lacks, a non-indexed file and a folder outside a repo go through. korium-cli signed out or Korium not answering refuses until the lookup. Off switch `MASTHEAD_CODE_GATE=off`. Proven by `tests/korium-index-judge-test.sh`. The plain-word hint is `korium-index-hint.py`: up to three words of four or more letters, each asked once per session, any letter case, and it never refuses; signed out or slow means no hint. Off switch `MASTHEAD_INDEX_HINT=off`. Proven by `tests/korium-index-hint-test.sh` |
| `hooks/model-choice-gate.sh` (run by `agent-brief-gates.sh`) | Refuses an Agent dispatch that would run on Opus (model opus on the call, or none set and no agent file naming one) unless the brief opens `Model-choice: opus, <why>`; Haiku is the default | Cannot judge whether the stated reason is true. Agents whose file names a model, forks, Explore, claude-code-guide, statusline-setup and plugin agents are not covered. Off switch `MASTHEAD_MODEL_GATE=off` |
| `hooks/engram-protocol.sh gate-redundant-grep` | Refuses, once, a search that repeats a name `code_locate` just answered | Reads the pattern or command text |
| `hooks/engram-protocol.sh gate-span-read` | Refuses, once, a whole-file read after `code_locate` returned a span | A read with an offset passes |
| `hooks/agent-brief-gates.sh` | Runs the one brief check, the model option and the dispatch record, and joins their refusals | A wrapper timeout can lose all of them at once. Proven by `test-shared-safety-gates.py` |
| `hooks/dispatch-record-gate.sh` | Records each dispatch's model (the call's field, else the agent file's `model:` line), its outcome (`dispatched`, `refused`, or `re-verify round N` for a brief whose line starts `Re-verify:`), any first-line Model-choice reason and the checkout's branch in the repo's `.claude/state/dispatches.tsv` | Never refuses. The row is written before the agent runs |
| `hooks/engram-protocol.sh gate-verify-brief` | Refuses a brief to `verifier` or `security-reviewer` with no claims list in the one exact form (a line that is exactly `Claims:` at column zero, then a `- ` bullet of at least four words; any other spelling is refused with the form), and a verifier's re-verify brief (a line that begins `Re-verify: round N` at column zero; any other spelling is refused) when the dispatch log already holds two of the verifier's re-verify rows for the session on this branch; the number in the brief is not read, and the security reviewer's row does not count. A dead or declined verifier still spends its round, so the worker reports to the foreman one round early rather than a round late. Retired with it on 2026-10-27 (issue #20): the Korium-line, fix-evidence, wave-brief and brief-inference checks, which refused four honest briefs in one day | Checks the line is there, not that the claims are the right ones. Off switch `MASTHEAD_BRIEF_GATE=off`. Proven by `test-brief-gates.py` |
| `hooks/engram-protocol.sh gate-capture` | Refuses a subagent capture filed under another acting agent's name | Main-session payloads carry no acting-agent field |
| `hooks/engram-protocol.sh gate-stop` and `gate-substop` | Refuse one finish when the session or subagent made no successful Korium capture | Refuse once, then stand down; a quota refusal stands aside |
| `hooks/capture-finding-reminder.py` | On Stop, reminds once per turn, on stderr, when the reply reported a finding (a verdict, a root cause, a correction, a measurement) and nothing was captured since the user last spoke | Never blocks: a reminder, not a gate. Runs only with the Korium memory option on |
| `hooks/korium-index-on-stop.sh` | On Stop, runs `korium-cli index` in the background for the session's checkout, one run per checkout at a time, logged in its git folder | Never refuses; stands aside with no `korium-cli`. Runs only with the Korium memory and code index options on. Off switch `MASTHEAD_INDEX_ON_STOP=off`, or `git config korium.indexOnStop false` |

## Ownership, safety, and review gates

| Gate | Current job | Known limit |
|---|---|---|
| `irreversible-action-gate.sh` | Refuses destructive git operations, safety-check bypasses, destructive data or infrastructure actions, and unproven pushes | It emits deny, not ask |
| `hooks/commit-attribution-gate.py` | Refuses a `git commit`, `gh pr create` or `gh pr edit` whose message or body carries AI attribution | Cannot see a message written in an interactive editor. Proven by `test-commit-attribution-gate.py` |
| `hooks/issue-edit-gate.py` | Refuses a `gh issue edit` whose new body drops a line quoted as the user's (three or more words in quotes, with the user's name on the line or on a heading above it, by the first name in git config or "the user" as the speaker), or adds a `[NEEDS CLARIFICATION]` question with no `looked in:` part naming the decision record, the README rule and the Korium query. Reads one form, `--body-file <path>` naming a real file inside the checkout, and refuses `--body`, standard input, a heredoc or a here-string with that form to use | The gate trusts whoever can comment on the issue, so on a public repository a commenter can make it protect their line; it keeps lines from being dropped and grants no authority, and every refusal marks the text it quotes as issue data. It guards against a line dropped by accident, like the other gates, and reads no other shell shape (a wrapper, a file the same command rewrites, a `cd`). Proven by `tests/issue-edit-gate-test.py` |
| `web-to-memory-gate.py` | Refuses verbatim open-web text entering Korium, memory directories, MEMORY.md or anything under `~/.claude*`, and requires a web-access marker on such writes from an agent that read the web | Files inside a git repository (a repo's CLAUDE.md, `.claude/references/`) are out of scope: the change shows in the diff and PR instead, but a later session in the same checkout loads it before review. Detects copied text, not every paraphrase or parent-to-child transfer |
| `hooks/untrusted-domain-deny.py` | Refuses web requests to disallowed hosts | The host list is in the hook |
| `skill-review-gate.py` | Refuses invoking a changed project skill or agent that has not been read | Project files only: a change to one of the plugin's own agents or skills is not caught |
| `scope-gate.py` | While `<state>/scope.json` exists in a checkout, refuses edit-tool writes outside its allowed paths or inside its forbidden ones, and puts back any protected file a call changed | Not covered: product files a Bash command writes, a background command's later writes, calls from outside the repository. An unparseable scope file refuses every edit in that checkout. Proven by `tests/scope-gate-test.sh` |
| `elixir-toolchain-env.sh` | On SessionStart and CwdChanged, loads the toolchain file the repo names as `PROJECT_TOOLCHAIN_ENV` through `CLAUDE_ENV_FILE`, so every Bash command, subagents included, finds the pinned Elixir | Stands aside with no toolchain file. Proven by `tests/elixir-hooks-test.sh` |
| `elixir-format-after-edit.sh` | After an edit to an Elixir file under the repo's `PROJECT_ELIXIR_ROOT`, runs `mix format` and `mix credo --strict` on that file and hands problems back | PostToolUse, so it never undoes the edit; stays off when deps are missing |
| `hard-gate.sh` | The push gate: on `git push` or `gh pr create`, runs the secret scan and each changed stack's format, compile, lint and type checks, then refuses unless the repo's `PROJECT_PUSH_CHECK` script, run with `--check`, finds a local test receipt for HEAD's tree covering every tier the change needs, and refuses a push that sends anything but HEAD | The hook reads the receipt and runs no tests; a hand-written receipt and a push from the user's own terminal are not covered. Proven by `tests/hard-gate-test.sh` |
| `adr-sections-gate.py` | Refuses a new ADR written without Principle Alignment, Acceptance Criteria, or You Are Done When, in the folder `ADR_DIR` names, including one outside the repo such as a wiki clone | Cannot judge whether a criterion is real; a shell write by a relative path is not seen |
| `adr-structure-gate.sh` | On Stop, refuses a finish that left an ADR with an unmarked Factual Claims list, reading uncommitted changes in the checkout and in the `ADR_DIR` clone | Checks markers, not the claims |
| `wiki-refresh.sh` | On SessionStart, pulls the local clone that holds `ADR_DIR` (clones it from `ADR_REMOTE` when missing), in the background | Refreshes, never refuses; skips a clone that cannot fast-forward. Retired with it on 2026-10-03: `adr-immutable-gate.sh`, since ADRs live in the wiki and are revised in place |
| `hooks/bash-scope-reviewer.sh` | Refuses a network command, or any command carrying a URL, from `verifier` and `security-reviewer` | Scoped by `agent_type` |
| `hooks/review-write-fence.py` | Refuses a write from `verifier` or `security-reviewer` to anything but its own findings file in `<checkout>/<state>/review/` | Not covered: a shell write. Proven by `tests/review-write-fence-test.sh` |
| `hooks/bash-scope-diagnoser.sh` | Allowlists the `diagnoser` and `reader` shells to test runners and read-only inspection | Scoped by `agent_type` |
| `verdict-gate.sh` | Refuses a Stop when a changed case file has no `file:line` in its verdict or fewer than two numbered observations | Project-wide on Stop |
| `hooks/prime-context.py` | At SessionStart, prints the Korium memory protocol; on each user prompt, injects the procedure from `session-cliffs.md` whose bold lead matches the prompt (a commit, a push, a PR, a test result) | Injects, never refuses, and fails open; a subagent's report, another session's message or a task notice gets no procedure |



## Permission boundary

Hooks are not the whole permission system: deny, ask and allow rules merge from
managed, command-line, local, project and user settings, and a deny wins.

When this catalog conflicts with wiring, code, tests, or a newer Korium
correction, the newer evidence wins and this file must be updated.
