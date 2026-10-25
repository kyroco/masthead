# The rewrite brief

Sent to one `general-purpose` agent per issue with `model: "sonnet"`, after
the user's go in step 4, all in one message. Fill in the number, the repo,
the report's thought id and the Korium line, and send the rest as written.

```
no code change
This edits one GitHub issue and may create its sub-issues; it changes no file in the repo.

Korium: <what this session's agent_search found, or that it found nothing>.

Apply the /analyze-issues report in Korium <thought id> to issue #<n> in <repo>.

1. Read the report with korium_reconstruct, every piece: call again with
   next_from until it is null. Section 5 is the new body; section 3 holds
   the split, if there is one. If the report cannot be read, stop and say
   so; never write a body from memory.
2. Make a scratch folder with mktemp -d and save the issue's current body in
   it as old.md: gh issue view <n> --json body --jq .body
3. Write the new body there as new.md, exactly as section 5 gives it. Where
   it keeps a part of the old body (a folded history block, the Screens
   paragraph, a block between <!-- ...:start --> and <!-- ...:end -->
   comments), copy that part from old.md byte for byte. Where it points
   back to another section, write those lines out in full.
4. Before you edit, check that every kept part is in new.md exactly as in
   old.md, and that every line the user wrote in old.md is still there (grep -F
   each line). If one is missing, fix new.md; never edit the issue with a
   part missing.
5. gh issue edit <n> --body-file <scratch>/new.md
6. If the report splits the issue, create each sub-issue as
   ${CLAUDE_PLUGIN_ROOT}/skills/github-issues/SKILL.md says: same milestone and project,
   its own four parts from the report, the sub-issue link, and a blocked-by
   link where one waits on another. Leave the parent as the summary.
7. Add one comment to issue #<n>: "Rewritten by /analyze-issues on <date>;
   the old body is in the edit history."

Capture what you did in Korium with agent_capture. Return one line: the
issue, whether the body was edited, the sub-issue numbers made, and the
thought_id.
```
