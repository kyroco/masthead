# The per-issue brief

Sent to one `general-purpose` agent per issue, with `model: "haiku"`. Fill in
the number, the repo, the project number and the Korium line, and send the
rest as written.

```
no code change
This rewrites one GitHub issue and may create its sub-issues; it changes no file in the repo.

Korium: <what this session's agent_search found about this issue's subsystem, or that it found nothing>.

Rewrite issue #<n> in <repo> before it is built. Read, in full: the issue
with every comment (`gh issue view <n> --comments`), the project README
(`gh project view <number> --owner <org> --format json --jq .readme`), the
decision records the issue names, and the mockup pages it names. Use code_locate with repo "<repo value>" to find
the modules the work would touch.

An issue has four parts, defined in ${CLAUDE_PLUGIN_ROOT}/skills/github-issues/SKILL.md
under "What an issue holds": Why, Scenarios, Out of scope, Questions. Read
that section and the size rule under it before you write.

Write the new body:

1. Why: what is wrong or missing today, from the issue, the README and the
   ADR. Drop every line that says how to build rather than what is true when
   it works (a module as a design, "on every X", a tech choice).
2. Scenarios: each as "Given ..., When ..., Then ...", one line each, with
   the ADR decision, README rule or the user's quoted words it rests on. A
   scenario about a screen names its mockup page and the rubric rules it
   makes hold. Add nothing the sources do not support.
3. Out of scope: what this issue does not build, with the issue that does.
4. Questions: what the sources do not settle and a worker would otherwise
   guess, each as [NEEDS CLARIFICATION: the question]. Look in the issue's
   comments, the README, the ADR, the architecture doc and the mockups
   first. A design choice is not a question.

Keep exactly as they are: every line the user wrote (quoted under the
scenario it rules on), every file:line, any folded history
block, the Screens paragraph, and every block between `<!-- ...:start -->`
and `<!-- ...:end -->` comments. Write every line out in full; never "as in
section 2".

Then, on GitHub:

- Edit the body, passing it on standard input:
  `gh issue edit <n> --body-file - <<'BODY'` ... `BODY`
- If the size rule says split, create each sub-issue as the github-issues
  skill says (same milestone and project, its own four parts, the sub-issue
  link, a blocked-by link where one waits on another), and leave the parent
  as the summary.
- If any question is open, add the needs-decision label.
- Add one comment: "Rewritten by /analyze-issues on <date>; the old body is
  in the edit history."

Change no other issue. Capture what you did in Korium with agent_capture.
Return only this, in under 150 words: the verdict (ready, split, or waiting
on questions), the sub-issue numbers, every [NEEDS CLARIFICATION] line word
for word, and the thought_id.
```
