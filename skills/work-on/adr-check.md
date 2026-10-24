# The ADR review: one issue's work against its whole ADR

A worker dispatched you once its build was done, before its PR review. You
did not write this code and have not seen the worker's reasoning; keep it that
way. You change no file, push nothing and message no one.

## 1. Read, in full

1. The issue: `gh issue view <n> --json title,body,comments`.
2. The branch's whole change: `git diff origin/main...HEAD` in the worktree
   the brief names.
3. The ADR the issue links, every line, never a section. Read it from the
   local wiki clone the repo's `ADR_DIR` names (pull it first), else from the
   link. Read no other ADR unless this one names it.
4. The architecture doc and the UX mockups the ADR or the project README names
   for what this issue touches, in full.

Nothing else is a source for what should have been built: not Korium, not the
worker's account of its work.

## 2. Check

Assume nothing was built correctly, and that some of what the issue needs was
not built at all. For the part of the ADR this issue builds:

- Every requirement (each decision, acceptance criterion and rule): is it in
  the code exactly as the ADR says? Quote the ADR line and give the code's
  `file:line`.
- Every changed line: does it contradict any line of the ADR, the architecture
  doc or the mockups? Quote it.
- Anything the change does that the issue did not ask for.

A reviewer asked for gaps will usually report some even when the work is
sound, so each finding quotes the line it breaks, or it is not a finding.
Level each one Important (it breaks a line of the ADR, the architecture doc,
the mockups, or the issue's scenarios) or Nit. A style preference is not a
finding.

## 3. Report

Capture the result in Korium, then return: the branch and its head commit,
the number of Important findings, and each finding as the level, the quoted
line, where that line is, the code's `file:line`, and the gap in one plain
sentence.
