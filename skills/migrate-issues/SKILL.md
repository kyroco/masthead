---
name: migrate-issues
description: Move a set of issues from GitHub to Linear, or from Linear to GitHub. It reads the source, asks the person how to lay the work out and how to reach Linear, and writes nothing until they say yes to the plan.
disable-model-invocation: true
---

# Migrate issues

One skill moves issues both ways: GitHub to Linear, and Linear to GitHub. The
person calls it with a source and a target, such as
`/masthead:migrate-issues github acme#7 to linear WEB` or
`/masthead:migrate-issues linear "Website relaunch" to github acme/site`. Ask
for whatever is missing, one question at a time, in plain words.

Nothing is written to GitHub or Linear until the person has said yes to the
plan. Until then every call reads. The script beside this file,
`${CLAUDE_PLUGIN_ROOT}/skills/migrate-issues/migrate.py`, does the reading and
saves the plan; it never writes to either tracker.

## 1. What moves, and to where

- **GitHub to Linear.** The source is a GitHub project: its owner and number,
  or its link (`github.com/orgs/<owner>/projects/<number>`, or
  `github.com/users/<owner>/projects/<number>`). The target is a Linear team,
  by its key, such as `WEB`.
- **Linear to GitHub.** The source is a Linear project, or a list of issue
  keys. The target is a GitHub repository, `<owner>/<repo>`.

## 2. GitHub to Linear: read the project, then ask the layout

Read the project first, so the question uses its own names:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/migrate-issues/migrate.py layouts --owner <owner> --project <number>

Show its output as it is, then ask which layout they want:

- **the mirror layout**: the GitHub project becomes one Linear project, and
  each GitHub milestone a milestone inside it.
- **Linear's layout**: each GitHub milestone becomes its own Linear project,
  grouped under one Linear initiative named for the GitHub project. In
  Linear, a project is a body of work and a milestone is a stage inside it,
  such as build, test and deploy.

Say plainly that the choice is theirs. When `gh` cannot see the project, say
what the script printed and stop.

## 3. Linear to GitHub: the layout is not asked

Linear to GitHub keeps the structure as it is: a Linear project becomes a
GitHub project, a milestone becomes a milestone, and an issue an issue. Say
so in one line, and read the source once the person has chosen how to reach
Linear (step 4).

## 4. Ask how to reach Linear

In both directions, the person chooses an API key or the Linear connector:

- **The Linear connector**: the Linear tools already connected to this
  session. Nothing to set up. Check it by reading the target team (or the
  source project) through the connector. When no Linear tools are loaded, say
  so and offer the key instead.
- **A Linear API key**: a personal key made in Linear under Settings,
  Account, Security & Access. A key limited to reading is enough for this
  step; the copy will need one that can write. Ask where the key is kept: a 1Password reference such
  as `op://<vault>/<item>/<field>`, or the name of an environment variable
  already set in their shell.

Never ask for the key itself. When the person pastes one anyway, it is
already in this session's record: do not use it, tell them to revoke it in
Linear and make a new one, and ask where the new one is kept.

The key is read at run time, by the command that needs it, and never printed,
written to a file, an issue, a comment or a log. Check that it works, and
that it can see the team, without ever seeing it:

- From 1Password, through `op run`, which puts the key in the variable only
  for that one command and hides it in what the command prints:

      LINEAR_API_KEY='op://<vault>/<item>/<field>' op run -- python3 ${CLAUDE_PLUGIN_ROOT}/skills/migrate-issues/migrate.py check-linear --key-env LINEAR_API_KEY --team <KEY>

- From a variable already set:

      python3 ${CLAUDE_PLUGIN_ROOT}/skills/migrate-issues/migrate.py check-linear --key-env <NAME> --team <KEY>

Use `op run`, never `op read`, and never `echo` the variable: either would put
the key in this session's record. When the check fails, show what it printed
(the key is hidden in it) and ask the person to fix the key or choose the
connector.

## 5. The plan, and the person's yes

Save what the person chose:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/migrate-issues/migrate.py plan --direction github-to-linear --source <source> --target <target> --layout mirror|linear --access key --key-env <NAME> --kept '<where it is kept>'

For Linear to GitHub, use `--direction linear-to-github` and leave out
`--layout`. For the connector, use `--access connector` and leave out
`--key-env` and `--kept`. The plan holds where the key is kept, never the key,
and it refuses a key given as the place.

Show the plan in a table: the direction, the source, the target, the layout,
and how Linear is reached. Ask for a yes. Nothing is written until it comes.

## 6. After the yes

The copy itself (issues, comments, links, and closing the originals) is not
built yet. Say so, give the path of the saved plan, and stop.
