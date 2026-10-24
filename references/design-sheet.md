# The sheet: the user approves every issue before it is built


A code review cannot catch a wrong design or a wrong reading of an issue; only
the user can, and only before the code exists. So every issue gets a one-page
sheet, the user approves or steers it, the issue is updated, and only then is
it built.

## Which issues get a sheet

- Only an issue a worker the user started with `/work-on #1418` builds, when
  the issue has the `design-sheet` label and builds no ADR. Otherwise its step
  7 brief, which the user approves before any code, does the same job.
- Never an issue in a foreman run, and never an issue that builds an ADR. The
  whole ADR is that issue's spec, and a fresh reviewer checks the work
  against it once before the PR (`skills/work-on/adr-check.md`). The ADR is
  the source of truth; a sheet never carries a decision the ADR did not make.


## The worker: write it into the issue, stop

After step 6's audit (the code read, the plan clear), and before any code:

1. Write the sheet, checked against the code, under a page, in plain words:
   - **Decision it builds**: when the issue builds an ADR, the decision it
     rests on, quoted with the user's words and the link, and the mockup page
     for any screen. "None" when no ADR covers it.
   - **What changes**, in one or two sentences.
   - **How**: the approach, the modules or files it touches, and what it
     reuses that already exists.
   - **What the customer sees**: one real example of a save or a question and
     the reply after the change, or "nothing" for internal work.
   - **Outside model calls**: every call this adds or changes, what triggers
     it, which model, what text is sent and how much, whether a local model
     could do it, and what gates it. "None" when there are none.
   - **Settings**: every setting or switch it adds or reads, whether it belongs
     to the organization or the workspace, and who may change it. "None" when
     there are none.
   - **Free plan**: what a Free customer gets, when the change touches what
     customers get.
   - **Split**: the sub-issues step 6 would make, if any.
   - **Questions**: anything the issue leaves open that would change a line
     above, each with the answer the worker recommends.
2. Put it in the issue itself, never in a comment: a `## Sheet` section at the
   end of the issue body, with everything above it unchanged. Read the body to
   a file with `gh issue view <n> --json body --jq .body`, append the section,
   and write it back with `gh issue edit <n> --body-file <file>`.
3. Give the user the issue link, then stop and wait. Write no product code
   until the user approves it.
4. On an adjustment or an answer, rewrite the sheet in place (GitHub keeps the
   edit history), change the issue's `Done when:` if the answer changed it, and
   report again.
5. If the build has to leave the approved sheet (a line becomes false), stop
   and report before going on; that is a new sheet, not a judgment call.

## A foreman run

A foreman run has no sheets. Each worker builds from its issue and, when the
issue builds one, the whole ADR, the architecture doc and the mockups, and
takes a question none of them nor Korium answers to its foreman
(`skills/work-on/worker.md` step 6, `foreman.md`).



Enforced by: nothing mechanical. No hook checks for the sheet or the approval
before a worker writes code.
