# <Project name> architecture

<One or two sentences: what this project is and who uses it.> This doc is the
target shape every decision record and pull request is checked against. Keep it
to a page or two. The principles live in <the file that holds them, usually
CLAUDE.md>; this doc cites them by number (P1, P2 and on) and never copies them.

## The parts

<Each app or part that exists, one line each: its name, its folder, and what it
is for. Say which part is the core and which are extensions.>

## One way in and out for each body of data

<One line for each body of data: the one module it is reached through, and what
that module hands back (an object or struct, never raw rows). Cite the principle
it applies, if one does.>

## Core and extensions

<The rules between the core and its extensions: which way the names point, how
an extension plugs in, and what the core does when an extension is absent.>

## What each build ships

<Each build or edition this project ships, one line each: which parts it
carries, and what must still work when a part is left out.>

## The seven rules

Each line is a rule for this project, in plain words, or says why it does not
apply here. The architecture reviewer holds every pull request to these.

- **Direction.** <rule, such as "the core never names an extension">
- **One way in and out.** <rule, such as "billing data is reached only through one module, which hands back an object">
- **Call shape.** <rule>
- **Seams.** <rule, or "Does not apply:" and why>
- **What each build carries.** <rule>
- **Leftovers.** <rule>
- **Tests and checks.** <rule>
