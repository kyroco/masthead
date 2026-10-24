# Masthead

Masthead is a plugin for [Claude Code](https://code.claude.com) that turns a
team's working rules into guard rails the AI cannot talk its way past.

If you have ever written "never push without running the tests" into a
CLAUDE.md file and watched the AI do it anyway three hours later, this is for
you. A rule written in prose is a suggestion. Masthead makes the ones that
matter into **gates**: small checks that run just before an action and refuse
it when the rule is broken. The AI sees why it was refused and does the right
thing instead.

![A rule in prose fades over a session; a gate holds](docs/images/gates.svg)

It installs in a few minutes, works on any repository in any language, asks
you three short questions, and everything it adds can be turned off.

## What you get

| Guard rail | What it does for you | On by default |
|---|---|---|
| **Secrets stay secret** | Claude cannot read your `.env`, keys, tokens or password files, cannot fetch a secret out of a vault, and is warned when a command prints something that looks like one. | Yes |
| **Nothing irreversible** | Force pushes, history rewrites, deleting unmerged branches, dropped databases and the like are refused before they run. | Yes |
| **No surprise web traffic** | Fetches to paste sites and other places code should not go are refused. | Yes |
| **Tests before a push** | A push or a pull request is refused until the repository's tests have passed on that exact commit. | After setup, if you say so |
| **Blind review** | When Claude finishes a change, separate reviewers who never saw the author's notes read the code cold, and a judge keeps only the findings it can prove. The reviewers cannot edit anything. | Yes |
| **One issue per session** | `/work-on #123` takes one GitHub issue from a fresh branch to one reviewed pull request, and nothing else. | Yes |
| **Honest handoffs** | When Claude sends work to a helper, the brief has to say what is claimed and what is not proved, so the helper is not misled. | Yes |
| **A memory across sessions** | With [Korium](https://kyroco.ai) connected, every session searches what earlier sessions learned before its first change, and saves what it learned before it finishes. | Only if you connect it |
| **Clean git history** | Commit messages and pull requests carry no AI co-author lines or session links. | Yes, can be turned off |

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

You type one command with an issue number. Claude reads the issue and its
project README, makes a branch and a worktree, searches memory if it is
connected, builds on the branch, sends the change to blind reviewers, has a
judge keep only the proven findings, fixes those test-first, runs the push
check, and opens one pull request. It asks you only when something is
genuinely yours to decide.

![One issue, one session, one pull request](docs/images/workflow.svg)

Along the way the gates do their job quietly. You see them only when one
refuses something, and the refusal says what to do instead.

## The review, up close

When the change is finished, Claude does not grade its own work. It sends the
diff, and nothing else, to reviewers who each take one angle: bugs, edge
cases, contracts, reuse, cleanup, and a security reviewer when the change
touches authorization, secrets or untrusted input. They cannot edit, cannot
reach the network, and never see the author's explanation. A separate judge,
the adjudicator, reads the code and the findings, throws out what it cannot
prove, and hands the author a fix list with a file and line for each item.

![The review wave: blind reviewers, one judge, one fix list](docs/images/review.svg)

## Each decision, and why

**A rule is a gate, not a sentence.** The rules that matter are small
programs that run just before Claude acts and refuse when the rule is broken.
We tried prose first. We wrote the rules into the file Claude reads at the
start of every session, and they held for about three hours. Long sessions
forget, and a forgotten rule fails silently. A gate cannot forget. If a rule
is worth having, it is worth enforcing; if it is not worth enforcing, we leave
it out rather than pretend.

**Secrets are never read.** Claude cannot open `.env` files, private keys,
tokens, password files, cloud credentials or SSH keys, and cannot pull a
secret out of a vault with a command. If it needs a value, it asks you. A
secret that enters the conversation is in the transcript, in the logs, and in
whatever Claude writes next. Refusing the read is the only reliable place to
stop that.

**Nothing irreversible.** Force pushes, history rewrites, deleting branches
that are not merged, destructive database commands, and the other things
nothing undoes are refused outright. Everything else Claude does can be
reviewed and reverted. These cannot. A refusal costs one sentence; the
alternative costs a weekend.

**Tests pass before anything is pushed.** When you say yes at setup, a push or
a pull request is refused until the repository's test command has passed on
the exact commit being pushed. Claude runs the tests itself; the gate only
checks the receipt. "I ran the tests" is a claim. A receipt that names the
commit is a fact. The gate also refuses pushing a different commit than the
one tested, because that is the usual way a green run gets attached to the
wrong code.

**Reviewers are blind, and a judge keeps only what is proven.** A reviewer
who reads the author's explanation reviews the explanation. A reviewer who
can edit the code stops reviewing and starts fixing. A reviewer who can reach
the network can be talked to. Removing all three is what makes the review
worth reading. The judge exists because reviewers disagree and the author
should not be the one deciding which findings count.

**One issue per session.** `/work-on #123` makes the session the worker for
that one issue: a worktree, a branch linked to the issue, the build, the
review wave, the fixes, the push check, one pull request. A foreman mode runs
several workers in parallel, one fresh session each. A session that carries
several pieces of work drifts: context from one bleeds into the next, and the
second piece gets a tired reviewer. Many short sessions are cheap. One long
one is not.

**Honest handoffs.** When Claude sends work to a helper, the brief must say
what the author claims works, what was not proved, and how a fix will be
proved. A brief that asks a helper to take the author's conclusion as a rule
is refused. A helper starts with only its brief; whatever is left out, it
never learns. The gate makes the omission visible before the helper starts,
which is the only time it can be fixed cheaply.

**A memory across sessions, if you want one.** With Korium connected, each
session searches what earlier sessions learned before its first change, and
saves what it learned before it finishes. Decisions, dead ends and reversals
survive the end of the session that found them, and Claude stops re-deriving
what you settled last week. Korium is a product from Kyroco, the company
behind Masthead. It has a free plan, but it is an account and a sign-in, and
that is your decision, not ours.

**Your repository states its facts; Masthead reads them.** A small settings
file tells Masthead the test command to run before a push, where it keeps
decision records if it has them, and where Masthead may keep its own working
files. A repository that states nothing still gets every guard rail; the ones
that need a fact stand aside until it is there. Facts belong to the
repository, so a teammate who clones it gets the same guard rails with
nothing to configure. Setup writes the file for you after you confirm it.

**Opinions are switches; safety is not.**

| Option | Default | Why it is a switch |
|---|---|---|
| Connect Korium memory | off | It is an account with a third party. |
| Keep AI attribution out of commits | on | Some teams want the trailers. |
| Ask for a reason before a helper runs on the biggest model | off | Saves money on parallel work; annoying if you never want to be asked. |

The safety rails (secrets, irreversible actions, web traffic) are not
switches. If you need one off for a real reason, each has an environment
variable named in [docs/gates.md](docs/gates.md), which lists every gate with
what it refuses and its known limits.

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

Masthead is made by [Kyroco](https://kyroco.ai) and is the setup we use on our
own repositories every day. Apache 2.0.
