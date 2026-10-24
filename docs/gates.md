# Every gate, what it refuses, and its limits

A gate is a small script under `hooks/` that Claude Code runs at a fixed
moment (before a tool call, after one, when a session or helper stops). It
reads what is about to happen and either lets it through or refuses it with a
reason. `hooks/hooks.json` wires each one. This page is the plain-English
list; the scripts themselves are short and say what each part does.

Every "off switch" is an environment variable read from the hook's own
environment, so a session cannot switch a gate off for itself. Set it in your
shell before starting Claude Code if you must.

## Safety: always on

| Gate | Runs | Refuses | Known limit |
|---|---|---|---|
| `block-secret-reads.py` | before a Read, Grep or shell command | reading a credential file (`.env`, keys, tokens, password files, cloud and SSH credentials), even through the masked reader | matches file names and command text; a file with an unusual name is not recognized |
| `block-secret-fetches.py` | before a shell command | pulling a secret out of a vault or secret store on the command line | matches command text |
| `scan-tool-output-for-secrets.py` | after a shell command | nothing; warns when the output looks like a credential | a backstop after the fact |
| `irreversible-action-gate.sh` | before a shell command | force pushes, history rewrites, deleting unmerged branches, destructive data and infrastructure commands, and pushing without the push check | emits a refusal, not a question |
| `untrusted-domain-deny.py` | before a web fetch or search | requests to paste sites and other hosts code should not reach | the host list is in the hook |
| `web-to-memory-gate.py` | after a web fetch; before a write | copying text fetched from the web into files that every session loads, or into memory, without a marker saying the web was read | files inside a git repository are out of scope, since a pull request shows them |

## The work: always on

| Gate | Runs | Refuses | Known limit |
|---|---|---|---|
| `agent-brief-gates.sh` | before a helper is sent | a brief to a reviewer that omits the author's claims or the code outside the diff the change depends on; a brief that asks for a fix without saying how it is proved; a brief that passes a conclusion off as a rule | checks the shape of the brief, not its truth |
| `dispatch-record-gate.sh` | before a helper is sent | nothing; records which model each helper ran on, in the repository's state folder | |
| `review-write-fence.py` | before a file write | a reviewer writing anything but its own findings file, or a scratch copy under the review folder | a shell write is not seen |
| `bash-scope-reviewer.sh` | before a shell command | a reviewer reaching the network | scoped by the agent's type |
| `bash-scope-diagnoser.sh` | before a shell command | the diagnoser or reader doing anything but running tests, reading git history and inspecting files | scoped by the agent's type |
| `verdict-gate.sh` | when a session or helper stops | a diagnosis case file whose verdict names no file and line, or carries fewer than two numbered observations | |
| `scope-gate.py` | before and after a write | while a scope file exists in the checkout, writes outside its allowed paths; puts back a protected file a command changed | a background command's later writes are not seen |
| `skill-review-gate.py` | before a skill or helper runs | invoking a changed project skill or agent that nobody in the session has read | project files only |
| `prime-context.py` | at session start and on each prompt | nothing; injects the matching procedure (before a commit, before a push, before reading a test result) | |
| `hard-gate.sh` | before `git push` or `gh pr create` | a push until the repository's push check reports the tests passed on this exact commit; a push of any other commit | reads the receipt, runs no tests itself; only when the repository names a push check |
| `adr-sections-gate.py`, `adr-structure-gate.sh`, `wiki-refresh.sh` | before a write; at stop; at session start | a decision record written without its required sections; a finish that leaves one with an unchecked claims list; keeps the records folder fresh | only when the repository names a records folder |
| `elixir-toolchain-env.sh`, `elixir-format-after-edit.sh` | at session start; after an edit | nothing; pins the Elixir toolchain and formats an edited file | only when the repository names an Elixir root |

## Options: on or off at install

| Gate | Option | Refuses |
|---|---|---|
| `engram-protocol.sh` (gate-edit, gate-stop, gate-substop, gate-agent, gate-capture, the code index gates) | Connect Korium memory | the first edit before a memory search; a finish with nothing saved; a brief that hides what memory found; a capture filed under another agent's name; a grep for a name the code index already answered |
| `capture-finding-reminder.py`, `korium-index-on-stop.sh` | Connect Korium memory | nothing; reminders and index refreshes |
| `commit-attribution-gate.py` | Keep AI attribution out of commits | a commit message or pull request body that carries an AI co-author line, a session link or a generated-with footer |
| `model-choice-gate.sh` | Ask for a reason before a helper runs on Opus | a helper sent to the largest model without a reason on the first line of its brief |

## Off switches

| Variable | Turns off |
|---|---|
| `MASTHEAD_CODE_GATE=off` | the code index gate |
| `MASTHEAD_SEARCH_GATE=off` | the search-before-edit gate |
| `MASTHEAD_CAPTURE_GATE=off` | the capture-name gate |
| `MASTHEAD_MODEL_GATE=off` | the model gate |
| `MASTHEAD_BRIEF_GATE=off` | the brief gates |
| `MASTHEAD_DONE_GATE=off` | the push check |
| `MASTHEAD_INDEX_ON_STOP=off` | the index refresh at stop |

## Proving it

`bash hooks/run-tests.sh` runs every gate's test suite: each one feeds the
hook real payloads and checks what it refuses and what it lets through. The
suites run in CI on Linux and macOS.
