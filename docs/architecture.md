# Masthead architecture

Masthead is a plugin for Claude Code. People who build software with Claude
Code install it to get checks that run before an action, blind review, and a
workflow that builds issues from GitHub or Linear. This doc is the target shape
every decision record and pull request is checked against. Keep it to a page or
two. This project keeps no numbered principles file, so the rules below stand
on their own and cite none.

## The parts

- **Hooks** (`hooks/`): the checks. Each is one small script that reads what
  Claude is about to do and lets it through or refuses it. This is the core.
- **The settings reader** (`hooks/project_fact.py`): the one script that reads
  a repository's answers and says where working files go. Part of the core.
- **Skills** (`skills/`): the workflows a person starts by name, such as
  setup and work-on, with the scripts each one runs. Extensions.
- **Agents** (`agents/`): the six helpers (four reviewers, a diagnoser and a
  reader). Extensions.
- **References** (`references/`): the shared pages that skills and agents read.
- **Docs and their builders** (`docs/`, `scripts/`): the explainer page and
  its pictures. They ship with the plugin but nothing runs them in a session.

## One way in and out for each body of data

- A repository's answers (the `env` block of its `.claude/settings.json` and
  `.claude/settings.local.json`): reached only through `hooks/project_fact.py`,
  which hands back one value, or a named answer such as the tracker.
- The stored Gate (`.claude/gate.json`): written only by
  `skills/setup/gate.py store`, and read only through `project_fact.py`, which
  hands back the checked record or nothing.
- Working files for one checkout (`.claude/state` unless the repository names
  another folder): the path comes only from `project_fact.py`.
- Private files for one person (session markers and snapshots): the folder
  comes only from `project_fact.py`, which makes it readable by that person
  alone and hands back nothing when it cannot be trusted.
- Install options (the four switches in `.claude-plugin/plugin.json`): read
  only in `hooks/run.sh`.

## Core and extensions

Skills and agents may name and call the hooks folder. The hooks folder never
calls a skill or an agent. A new hook plugs in with one entry in
`hooks/hooks.json` that starts it through `hooks/run.sh`. A new skill or agent
plugs in as a file in its folder. Korium memory, the code index, the two issue
trackers and the Elixir helpers are optional: when one is switched off, not
connected or not installed, its hooks stand down and every other check still
runs.

## What each build ships

- **The plugin**, one build: the whole repository, installed from the
  marketplace file in `.claude-plugin/`. There are no editions.
- The four install options switch parts on or off inside that one build. With
  all four off, the always-on checks (dangerous commands, secret reads, blind
  review) must still work.

## The seven rules

Each line is a rule for this project, in plain words, or says why it does not
apply here. The architecture reviewer holds every pull request to these.

- **Direction.** A script in the hooks folder never imports or runs anything from the skills or agents folders; skills and agents may use the hooks folder.
- **One way in and out.** A repository's answers, its stored Gate and every working-file path are reached only through `hooks/project_fact.py`; no other script opens the settings files or builds those paths itself.
- **Call shape.** Every hook is started by `hooks/run.sh` from an entry in `hooks/hooks.json`, and a hook that refuses says in plain words what it refused and why.
- **Seams.** A script reaches GitHub only by running the `gh` command, so a test can put a fake `gh` in its place; no script calls the GitHub web address directly.
- **What each build carries.** There is one build, and it must work with every install option off, with Korium not connected, and with issues in either GitHub or Linear.
- **Leftovers.** A hook, skill or agent that is removed takes its `hooks.json` entry, its tests and its lines in the README with it, in the same pull request.
- **Tests and checks.** Every hook and every script a skill runs has a test listed in `hooks/run-tests.sh`, which the tests workflow runs on Linux and macOS for every push.
