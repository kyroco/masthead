
# The per-issue brief

Sent to one `reader` agent per issue, effort `high`. Fill in the number, the
repo and the Korium line, and send the rest as written.

```
read_only: true
This is a reading and judging job; you change no file and no issue.

Korium: <what this session's agent_search found about this issue's subsystem, or that it found nothing>.

Check issue #<n> in <repo> before it is built. Read, in full: the issue with
every comment (`gh issue view <n> --comments`), the project README
(`gh project view <number> --owner <org> --format json --jq .readme`), the
decision records the issue names, and
the mockup pages it names. Use code_locate with repo "<repo value>" to find
the modules the work would touch.

An issue has four parts, defined in ${CLAUDE_PLUGIN_ROOT}/skills/github-issues/SKILL.md
under "What an issue holds": Why, Scenarios, Out of scope, Questions. Read
that section and the size rule under it before you judge.

Report, in this order:

1. Shape: which of the four parts the issue has today, and every line that
   says how to build rather than what is true when it works (a module as a
   design, "on every X", a tech choice). Quote each.
2. Scenarios: each one you can read out of the issue, the README and the
   ADR, as "Given ..., When ..., Then ...", one line each, with the ADR
   decision, README rule or the user's quoted words it rests on. Count them.
3. Size: the modules the work touches (from the index), and whether the size
   rule says split or keep. If split: each sub-issue's four parts, and which
   waits on which.
4. Questions: what the sources do not settle and a worker would otherwise
   guess, each as [NEEDS CLARIFICATION: the question]. A design choice is not
   a question; leave it to the worker's plan. A gap in what the product does,
   who may do what, or what a customer sees, is.
5. The rewrite: the whole new body in the four parts, ready to paste. Keep
   every line the user wrote, every file:line, any folded history block,
   the Screens paragraph, and every block a tool maintains between
   `<!-- ...:start -->` and `<!-- ...:end -->` comments, each exactly as it is. A scenario about a
   screen names its mockup page and the rubric rules it makes hold: the
   project README requires both of every screen issue. Add nothing the
   sources do not support. Write every line out in full, never "as in
   section 2", and when you split, write each sub-issue's body out in full
   too: a writer pastes this section without the rest of your report.

Capture the whole report, sections 1 to 5 and what you could not read, in
Korium with agent_capture. Then return only this, in under 250 words: the
verdict (ready, split into how many, or waiting on questions); the scenario
count; if split, each sub-issue's title and which waits on which; every
[NEEDS CLARIFICATION] line word for word; anything wrong you found outside
this issue, one line each; and the thought_id. The rewrite stays in Korium,
where the writer reads it; the session that sent you does not need it.
```
