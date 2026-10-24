# Masthead

Masthead is a plugin for [Claude Code](https://code.claude.com) that turns a
team's working rules into guard rails the AI cannot talk its way past.

If you have ever written "never push without running the tests" into a
CLAUDE.md file and watched the AI do it anyway three hours later, Masthead is
for you. A rule written in prose is a suggestion. Masthead makes the ones that
matter into **gates**: small checks that run before an action and refuse it
when the rule is broken. The AI sees why it was refused and does the right
thing instead.

It installs in a few minutes, works on any repository in any language, and
asks you three short questions. Everything it adds can be turned off.

## What you get

| Guard rail | What it does for you | On by default |
|---|---|---|
| **Secrets stay secret** | Claude cannot read your `.env`, keys, tokens or password files, cannot fetch a secret out of a vault, and is warned when a command prints something that looks like one. | Yes |
| **Nothing irreversible** | Force pushes, history rewrites, `rm -rf` on the wrong thing, dropped databases and the like are refused before they run. | Yes |
| **No surprise web traffic** | Fetches to paste sites and other places code should not go are refused. | Yes |
| **Tests before a push** | A push or a pull request is refused until the repository's tests have passed on that exact commit. | After setup, if you say so |
| **Blind review** | When Claude finishes a change, separate reviewers who never saw the author's notes read the code cold, and a judge keeps only the findings it can prove. The reviewers cannot edit anything. | Yes |
| **One issue per session** | `/work-on #123` takes one GitHub issue from a fresh branch to one reviewed pull request, and nothing else. | Yes |
| **Honest handoffs** | When Claude sends work to a helper, the brief has to say what is claimed and what is not proved, so the helper is not misled. | Yes |
| **A memory across sessions** | With [Korium](https://kyroco.ai) connected, every session searches what earlier sessions learned before its first change, and saves what it learned before it finishes. | Only if you connect it |
| **Clean git history** | Commit messages and pull requests carry no AI co-author lines or session links. | Yes, can be turned off |

[docs/why.md](docs/why.md) explains each one, what it refuses, and why we
built it that way. [docs/images/](docs/images/) has the pictures.

## Install

Masthead ships as a Claude Code plugin from its own marketplace. In a terminal:

```
claude plugin marketplace add kyroco/masthead
claude plugin install masthead@masthead
```

Then open Claude Code in a repository and run:

```
/masthead:setup
```

Setup asks three questions, in plain words:

1. **Just you, or the team?** Whether this repository's settings are shared
   with everyone who clones it, or stay on your machine.
2. **Tests before a push?** It finds your test command and asks whether a
   push should be refused until the tests passed on that commit.
3. **A memory across sessions?** Whether to connect Korium now, later, or not
   at all. Everything else works without it.

Nothing is written until you say yes. Run `/masthead:setup` again any time to
change an answer, and `/plugin configure masthead@masthead` to change the
install options (Korium, clean git history, the model gate for helpers).

## How a session looks with Masthead on

```
you:     /work-on #123
Claude:  reads the issue and its project README, makes a branch and a
         worktree, searches memory (if connected), builds on the branch,
         sends five blind reviewers and a security reviewer, has a judge
         keep only the proven findings, fixes those test-first, runs the
         push check, opens one pull request. Asks you only when something
         is genuinely yours to decide.
```

Along the way the gates do their job quietly. You see them only when one
refuses something, and the refusal says what to do instead.

## What Masthead never does

- It sends nothing anywhere. There is no telemetry. The only network use is
  the Korium memory, and only if you connect it.
- It never edits your code on its own. Gates refuse actions; they do not take
  them.
- It never reads a secret file, not even to check it.
- It stays out of your git history: no co-author trailers, no footers.

## Uninstall

```
claude plugin uninstall masthead@masthead
```

The small settings file setup wrote (`.claude/settings.json` or
`.claude/settings.local.json`) and the push check script
(`.claude/push-check.sh`) are yours to delete.

## For the curious

The guard rails are shell and Python scripts under `hooks/`, wired by
`hooks/hooks.json`, with a test suite under `hooks/tests/` you can run with
`bash hooks/run-tests.sh`. The skills under `skills/` are the written
procedures the AI follows, and `agents/` holds the reviewers and the judge.
[docs/gates.md](docs/gates.md) lists every gate with what it refuses and its
known limits.

Masthead is made by [Kyroco](https://kyroco.ai) and is the setup we use on our
own repositories every day. Apache 2.0.
