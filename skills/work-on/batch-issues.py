#!/usr/bin/env python3
"""Which issues a batch run carried to main, and which commits went back to their workers (INFRA-263).

The foreman runs this by hand, from a checkout of the repository. It only reads:
it queues nothing, opens nothing and changes nothing on GitHub or in git
(Robert, November 18, 2026, on "No pull request and no Gate run per issue":
"I agree with 1 and 2").

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-issues.py merged <run id> [--since <commit>]

  Reads one batch run on `landing`. When it is green and main has reached its
  commit, it lists each issue the batch carried to main: those are merged, and
  the foreman closes them and sets them Done. An issue with a dropped commit
  that has not come back yet is listed apart, as sent back, never as merged.
  The batch is the commits after the last earlier green batch run, or after
  `--since`, up to the run's commit.

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-issues.py returned

  Lists every commit a red batch dropped from landing (the records
  bad-commit.py writes as git trailers, references/bad-commit.md) that has not
  come back yet, each with the message the foreman sends the worker of its
  issue: which check failed, what to read first, and how to bring it back.

It reads the same records and finds issues the same way as bad-commit.py, so
the two cannot disagree on whose a commit is.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bad_commit", os.path.join(HERE, "bad-commit.py"))
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)
project_fact = bc.project_fact

LANDING_REF = "refs/remotes/{}/{}".format(bc.REMOTE, bc.LANDING)
MAIN_REF = "refs/remotes/{}/{}".format(bc.REMOTE, bc.MAIN)
REVERTS = re.compile(r"This reverts commit ([0-9a-f]{40})")
PICKED = re.compile(r"\(cherry picked from commit ([0-9a-f]{40})\)")

say = bc.say
git = bc.git
Stop = bc.Stop


def known(ref):
    """The full id of commit `ref`, or "" when this checkout has no such commit."""
    r = git("rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def fetch():
    git("fetch", "--quiet", "--no-tags", bc.REMOTE,
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(bc.MAIN, bc.REMOTE),
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(bc.LANDING, bc.REMOTE))


def commits(spec):
    """[(sha, message)] for the commits `spec` names (a range or a ref), oldest first."""
    out = git("log", "--reverse", "--format=%H%x1f%B%x1e", spec).stdout
    found = []
    for entry in out.split("\x1e"):
        if "\x1f" in entry:
            sha, body = entry.split("\x1f", 1)
            found.append((sha.strip(), body))
    return found


def trailers(body):
    """{trailer name: [values]} for the Masthead trailers of one record's message."""
    values = {}
    for line in body.splitlines():
        m = re.match(r"^(Masthead-[A-Za-z-]+):\s*(.*?)\s*$", line)
        if m:
            values.setdefault(m.group(1), []).append(m.group(2))
    return values


def one(values, name):
    found = values.get(name) or []
    return found[0] if found else ""


def records(tip):
    """Every drop record on `tip`'s history: one dict per dropped commit, oldest first."""
    found = []
    for revert, body in commits(tip):
        values = trailers(body)
        dropped = one(values, bc.T_DROPPED)
        if not re.fullmatch(r"[0-9a-f]{40}", dropped):
            continue
        found.append({
            "body": body,
            "revert": revert,
            "dropped": dropped,
            "issue": one(values, bc.T_ISSUE) or bc.NO_ISSUE,
            "checks": values.get(bc.T_CHECK, []),
            "with": [v.split(None, 1) + ([bc.NO_ISSUE] if len(v.split(None, 1)) == 1 else [])
                     for v in values.get(bc.T_WITH, [])],
            "builds_on": (one(values, bc.T_BUILDS_ON).split(None, 1) + [bc.NO_ISSUE])[:2]
            if one(values, bc.T_BUILDS_ON) else None,
            "run": one(values, bc.T_RUN),
            "batch": one(values, bc.T_BATCH),
        })
    # A dropped commit whose message names no issue may be a worker's revert of an earlier record,
    # bringing that record's commit back: it belongs to that record's issue (arch-3).
    by_revert = {r["revert"]: r for r in found}
    for r in found:
        if r["issue"] == bc.NO_ISSUE and known(r["dropped"]):
            brought = brings_back(bc.message(r["dropped"]), by_revert)
            if brought:
                r["issue"] = brought["issue"]
    return found


def brings_back(body, by_revert):
    """The drop record a commit brings back, when its message says it reverts that record's revert."""
    for sha in REVERTS.findall(body):
        if sha in by_revert:
            return by_revert[sha]
    return None


def open_records(tip):
    """The drop records on `tip` whose commit has not come back: no later commit reverts the
    revert, and none is the dropped commit cherry-picked again with -x."""
    history = commits(tip)
    reverted = {m for _, body in history for m in REVERTS.findall(body)}
    picked = {m for _, body in history for m in PICKED.findall(body)}
    return [r for r in records(tip) if r["revert"] not in reverted and r["dropped"] not in picked]


# ---- merged -----------------------------------------------------------------

RUN_FIELDS = "databaseId,status,conclusion,headSha,headBranch,url,workflowName,createdAt"


def earlier_green(run):
    """The commit of the newest earlier green batch run of the same workflow on landing that is an
    ancestor of this run's commit, or None."""
    listed = bc.gh_json("run", "list", "--workflow", run.get("workflowName") or "", "--branch", bc.LANDING,
                        "--status", "success", "--limit", "100",
                        "--json", "databaseId,headSha,conclusion,createdAt") or []
    head = run["headSha"]
    for other in sorted(listed, key=lambda r: int(r.get("databaseId") or 0), reverse=True):
        sha = other.get("headSha") or ""
        if int(other.get("databaseId") or 0) >= int(run["databaseId"]) or other.get("conclusion") != "success":
            continue
        if sha and sha != head and git("merge-base", "--is-ancestor", sha, head, check=False).returncode == 0:
            return sha
    return None


def merged(run_id, since, root):
    fetch()
    run = bc.gh_json("run", "view", str(run_id), "--json", RUN_FIELDS)
    if not run:
        raise Stop("gh found no run {}.".format(run_id))
    head = run.get("headSha") or ""
    url = run.get("url") or run_id
    if run.get("headBranch") != bc.LANDING:
        raise Stop("Run {} is not a batch run on landing (it ran on {}), so nothing counts as merged."
                   .format(url, run.get("headBranch")))
    if run.get("status") != "completed":
        raise Stop("Run {} has not finished, so nothing counts as merged yet. Read it again when it ends."
                   .format(url))
    if run.get("conclusion") != "success":
        raise Stop("Run {} is {}, not green, so nothing counts as merged and main did not move. Run the "
                   "search on it (bad-commit.py {}), then hand back what it dropped (batch-issues.py returned)."
                   .format(url, run.get("conclusion"), run_id))
    if git("merge-base", "--is-ancestor", head, MAIN_REF, check=False).returncode != 0:
        raise Stop("Run {} is green, but main has not reached its commit {}, so nothing counts as merged "
                   "yet. Read the run's move job.".format(url, head[:9]))
    base = since or earlier_green(run)
    if not base:
        raise Stop("No earlier green batch run on landing is an ancestor of {}, so where this batch starts is "
                   "not known. Run again with --since <the commit main was on before this batch>."
                   .format(head[:9]))
    if not known(base):
        raise Stop("--since {} is not a commit in this checkout.".format(base))

    # Judged at the run's own commit, never at landing's tip: a commit brought back after this run
    # did not reach main with it (s2-1).
    by_revert = {r["revert"]: r for r in records(head)}
    issues = []
    for sha, body in commits("{}..{}".format(base, head)):
        if sha in by_revert:
            continue  # a drop record: the search's commit, no issue's work
        brought = brings_back(body, by_revert)
        # A revert of a record is the work of that record's issue, whatever its message names
        # (s3-1); any other revert is an ordinary commit of the issue it names (arch-2).
        issue = brought["issue"] if brought else bc.issue_of(sha, root)
        if issue != bc.NO_ISSUE and issue not in issues:
            issues.append(issue)
    back = {}
    for r in open_records(head):
        back.setdefault(r["issue"], r)
    done = [i for i in issues if i not in back]
    held = [i for i in issues if i in back]

    say("Batch run {}: green, and main has reached {}. The batch is {}..{}.".format(url, head[:9], base[:9],
                                                                                      head[:9]))
    say("Merged, close and set Done: {}".format(", ".join(done) if done else "none"))
    if held:
        say("Sent back, not merged, leave open: {}".format(
            ", ".join("{} (dropped {})".format(i, back[i]["dropped"][:9]) for i in held)))
        # The dropped commit and its revert both reached main, so a "Fixes <issue>" line in the
        # dropped commit can have closed the issue on GitHub or set it Done in Linear (s4-judge-1).
        for i in held:
            say("If its commit's closing words closed {} or set it Done, reopen it and set it back to "
                "In Progress.".format(i))
    return 0


# ---- returned ---------------------------------------------------------------

def hand_back(r):
    """The message for the worker of a dropped commit's issue. A returned worker is a fresh session
    with no memory, so it carries everything the record holds."""
    issue, dropped, revert = r["issue"], r["dropped"], r["revert"]
    subject = bc.subject(dropped) if known(dropped) else dropped[:9]
    lines = ["Your commit {} ({}) for {} was dropped from landing by the revert {}, because the batch "
             "ending at {} went red in {}.".format(dropped, subject, issue, revert, r["batch"][:9], r["run"])]
    if r["builds_on"]:
        bad, bad_issue = r["builds_on"]
        lines.append("It failed no check of its own. It came off only because it changes lines that {} ({}) "
                     "changed, and that commit failed. Wait until {} is back on landing with its fix. Then "
                     "run `git revert {}` to put your change back, fix what no longer fits, and push both "
                     "commits to landing in one push.".format(bad[:9], bad_issue, bad_issue, revert))
        return "\n\n".join(lines)
    lines.append("Failed check: {}.".format(", ".join(r["checks"]) if r["checks"] else "not named in the record"))
    if r["with"]:
        partners = ", ".join("{} ({})".format(sha[:9], key) for sha, key in r["with"])
        keys = [key for _, key in r["with"] if key != bc.NO_ISSUE]
        lines.append(
            "It passes on its own and fails only together with {}, which landed earlier. It is your job to "
            "figure out what needs to be fixed and fix it, end to end, whichever commit the fault sits in; "
            "it is not someone else's commit to hand on. Before you change anything, read {} and every "
            "comment on {}, which say what was done there, so your fix is not out of context. Once your fix "
            "lands, add a comment to {} and to {} saying what you changed and why, so the issues stay in "
            "sync.".format(partners, " and ".join(keys) or "the issue of each of those commits",
                           "them" if len(keys) != 1 else "it", issue,
                           " and to ".join(keys) or "the issue of each of those commits"))
    else:
        lines.append("It fails that check on its own, on main.")
    lines.append(
        "To bring it back: run `git revert {}` to put your change back as it was, commit the fix on top, and "
        "prove it as /work-on says for {}. Then push both commits to landing in one push, so no batch tests "
        "your change without its fix. The record is in the revert's message: "
        "`git log -1 {}`.".format(revert, issue, revert))
    return "\n\n".join(lines)


def returned():
    fetch()
    found = open_records(LANDING_REF)
    if not found:
        say("No dropped commit is waiting to come back.")
        return 0
    for r in found:
        if r["issue"] == bc.NO_ISSUE:
            # No issue to hand it to: never a worker of an issue called "none found" (arch-3).
            say("{} names no issue: tell the person. It was dropped from landing by the revert {}, which "
                "failed {} in {}.".format(r["dropped"][:9], r["revert"][:9],
                                         ", ".join(r["checks"]) or "no check of its own", r["run"]))
            say()
            continue
        say("{} goes back to its worker: {} was dropped from landing. Do not set {} Done.".format(
            r["issue"], r["dropped"][:9], r["issue"]))
        say("--- message for the worker ---")
        say(hand_back(r))
        say("--- end ---")
        say()
    return 0


def main(argv):
    root = project_fact.checkout_top(os.getcwd())
    os.environ.setdefault("CLAUDE_PROJECT_DIR", root)
    try:
        if argv[:1] == ["returned"] and len(argv) == 1:
            return returned()
        if argv[:1] == ["merged"] and len(argv) in (2, 4) and argv[1].isdigit():
            since = None
            if len(argv) == 4:
                if argv[2] != "--since":
                    raise IndexError
                since = argv[3]
            return merged(argv[1], since, root)
    except IndexError:
        pass
    except Stop as stop:
        say(str(stop))
        return 1
    say("Usage: batch-issues.py merged <batch run id> [--since <commit>]\n       batch-issues.py returned")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
