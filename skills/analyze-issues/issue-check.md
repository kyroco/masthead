# The per-issue brief

Sent to one `general-purpose` agent per issue, with `model: "haiku"`. Fill in
the number, the repo, the project number and the Korium line, and send the
rest as written.

```
no code change
This checks one GitHub issue against its sources and edits only the part that fails; it may create sub-issues; it changes no file in the repo.

Korium: <what this session's agent_search found about this issue's subsystem, or that it found nothing>.

Check issue #<n> in <repo> before it is built. Read, in full: the issue
with every comment (`gh issue view <n> --comments`), the project README
(`gh project view <number> --owner <org> --format json --jq .readme`), the
decision records the issue names, and the mockup pages it names. Use code_locate with repo "<repo value>" to find
the modules the work would touch.

An issue has four parts, defined in ${CLAUDE_PLUGIN_ROOT}/skills/github-issues/SKILL.md
under "What an issue holds": Why, Scenarios, Out of scope, Questions. Read
that section and the Size rule under it before you check.

Run these six checks, in this order, and keep a verdict for each with its
evidence (the line of the issue, the source or the comment it rests on):

1. Parts: the four parts are present, in that order, under those headings.
2. The user's lines: every line the user wrote (a comment on the issue, or
   words quoted with the user's name) is still quoted under the scenario it
   rules on.
3. Sources: each scenario cites a source line (a decision record, a README
   rule, or the user's words) that exists. Open the source and quote the
   line. A citation you cannot open, or cannot find in the source, fails.
4. Shape: each scenario is "Given ..., When ..., Then ..." on one line, and
   a test can show it.
5. No how: nothing says how to build (a module as a design, "on every X",
   a tech choice). What is true when it works is what stays.
6. Size: the issue fits one worker session by the Size rule, with the
   reason in one line (what it touches, from code_locate).

Every check passes: change nothing on GitHub. No edit, no comment.

A check fails: edit only the part that fails, and keep every other line
exactly as it is: every line the user wrote, every file:line, any folded
history block, the Screens paragraph, and every block between
`<!-- ...:start -->` and `<!-- ...:end -->` comments. Write every line out
in full; never "as in section 2". Add nothing the sources do not support.

- Check 6 fails: split as the github-issues skill says (same milestone and
  project, its own four parts, the sub-issue link, a blocked-by link where
  one waits on another), and leave the parent as the summary.
- A question the sources leave open, which a worker would otherwise guess,
  goes in the Questions part as
  [NEEDS CLARIFICATION: the question; looked in: <decision-record section>, <README rule>, Korium "<query>"].
  Look in the issue's comments, the README, the decision record, the
  architecture doc, the mockups and Korium first, and name where you looked;
  a question a source settles is written into the issue with the line
  quoted, not asked. A design choice is not a question. Add the
  needs-decision label when a question is open.
- Edit the body, passing it on standard input:
  `gh issue edit <n> --body-file - <<'BODY'` ... `BODY`. A check in front of
  the edit refuses a body that drops a line quoted as the user's, or a
  question without its "looked in:" part. Fix the body; never work around
  the check.

Change no other issue. Capture what you did in Korium with agent_capture.
Return only this, in under 150 words: one line per check (pass or fail,
with its evidence), what you edited or "untouched", the sub-issue numbers,
every [NEEDS CLARIFICATION] line word for word, and the thought_id.
```
