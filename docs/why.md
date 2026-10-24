# Why Masthead is built the way it is

This page is for someone who has never written a hook and does not want to.
Each section is one decision: what Masthead does, what you will notice, and
why we chose it. The pictures are in [images/](images/).

## 1. A rule is a gate, not a sentence

**What it does.** The rules that matter are small programs that run just
before Claude acts. If the action breaks the rule, the program says no, and
Claude sees why.

**What you notice.** Almost nothing, until Claude tries something a rule
forbids. Then you see a short refusal in the transcript, and Claude takes a
different route.

**Why.** We tried the other way first. We wrote the rules into the file Claude
reads at the start of every session, and they worked for about three hours.
Long sessions forget, and a forgotten rule fails silently: nobody notices
until the day it mattered. A gate cannot forget. If a rule is worth having,
it is worth enforcing; if it is not worth enforcing, we leave it out rather
than pretend.

![A rule in prose fades over a session; a gate holds](images/gates.svg)

## 2. Secrets are never read

**What it does.** Claude cannot open `.env` files, private keys, tokens,
password files, cloud credentials or SSH keys, and cannot pull a secret out
of a vault with a command. When a command's output looks like a credential,
Claude is warned so it does not repeat it.

**What you notice.** If Claude needs a value from a secret file, it asks you
instead of reading it. That is the whole point.

**Why.** A secret that enters the conversation is in the transcript, in the
logs, and in whatever Claude writes next. Refusing the read is the only
reliable place to stop that. A masked reader exists for the rare case where
the shape of a file matters and the values do not.

## 3. Nothing irreversible

**What it does.** Force pushes, history rewrites, deleting branches that are
not merged, destructive database commands, and the other things nothing
undoes are refused outright.

**Why.** Everything else Claude does can be reviewed and reverted. These
cannot. A refusal costs one sentence; the alternative costs a weekend.

## 4. Tests pass before anything is pushed

**What it does.** When you say yes at setup, a push or a pull request from a
Claude session is refused until the repository's test command has passed on
the exact commit being pushed. Claude runs the tests itself; the gate only
checks the receipt.

**What you notice.** A push is sometimes refused with "the tests have not
passed on this commit". Claude then runs them, fixes what failed, and pushes.

**Why.** "I ran the tests" is a claim. A receipt that names the commit is a
fact. The gate also refuses pushing a different commit than the one tested,
because that is the usual way a green test run gets attached to the wrong
code.

## 5. Reviewers are blind, and a judge keeps only what is proven

**What it does.** When Claude finishes a change, it sends the diff to several
reviewers, each with one angle (bugs, edge cases, contracts, reuse, cleanup)
and a security reviewer when the change touches authorization, secrets or
untrusted input. The reviewers never see the author's notes, cannot edit
anything, and cannot reach the network. A separate judge, the adjudicator,
reads the code and the findings, throws out what it cannot prove, and hands
the author a fix list. The author fixes those, test first.

**What you notice.** Changes come back with fewer, better findings, and the
findings name a file and a line.

**Why.** A reviewer who reads the author's explanation reviews the
explanation. A reviewer who can edit the code stops reviewing and starts
fixing. A reviewer who can reach the network can be talked to. Removing all
three is what makes the review worth reading. The judge exists because
reviewers disagree and the author should not be the one deciding which
findings count.

![The review wave: blind reviewers, one judge, one fix list](images/review.svg)

## 6. One issue per session

**What it does.** `/work-on #123` makes the current session the worker for
that one GitHub issue: a worktree, a branch linked to the issue, the build,
the review wave, the fixes, the push check, one pull request. A foreman mode
runs several workers in parallel, one fresh session each.

**Why.** A session that carries several pieces of work drifts: context from
one bleeds into the next, and the second piece gets a tired reviewer. Many
short sessions are cheap. One long one is not.

![One issue, one session, one pull request](images/workflow.svg)

## 7. Honest handoffs

**What it does.** When Claude sends work to a helper, the brief must say what
the author claims works, what was not proved, and how a fix will be proved.
A brief that asks a helper to take the author's conclusion as a rule is
refused.

**Why.** A helper starts with only its brief. Whatever is left out, it never
learns. The gate makes the omission visible before the helper starts, which
is the only time it can be fixed cheaply.

## 8. A memory across sessions, if you want one

**What it does.** With Korium connected, each session searches what earlier
sessions learned before its first change, and saves what it learned before
it finishes. Decisions, dead ends, gotchas and reversals survive the end of
the session that found them.

**What you notice.** Claude stops re-deriving things you settled last week.
At the end of a session it writes a short note of what was decided.

**Why it is optional.** Korium is a product from Kyroco, the company behind
Masthead. It has a free plan, but it is an account and a sign-in, and that is
your decision, not ours. Every other guard rail works without it.

## 9. Your repository states its facts; Masthead reads them

**What it does.** A repository tells Masthead a few things about itself in a
small settings file: the test command to run before a push, where it keeps
decision records, where Masthead may keep its own working files. A repository
that states nothing still gets every guard rail; the ones that need a fact
stand aside until it is there.

**Why.** We did not want a plugin that only works on our own repositories.
Facts belong to the repository, so a teammate who clones it gets the same
guard rails with nothing to configure. Setup writes the file for you after
you confirm it.

## 10. What is an option, and what is not

Some rails are opinions. We hold them, and we made them switches:

| Option | Default | Why it is a switch |
|---|---|---|
| Connect Korium memory | off | It is an account with a third party. |
| Keep AI attribution out of commits | on | Some teams want the trailers. |
| Ask for a reason before a helper runs on the biggest model | off | Saves money on parallel work; annoying if you never want to be asked. |

The safety rails (secrets, irreversible actions, web traffic) are not
switches. If you need one off for a real reason, the hook's own environment
variable turns it off, and [gates.md](gates.md) names it.
