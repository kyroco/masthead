#!/usr/bin/env python3
"""Which issues a batch run carried to main (INFRA-263, INFRA-288).

The foreman runs this by hand, from a checkout of the repository. It only reads:
it queues nothing, opens nothing and changes nothing on GitHub or in git
(Robert, November 18, 2026, on "No pull request and no Gate run per issue":
"I agree with 1 and 2").

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-issues.py merged <run id> [--since <commit>]

  Reads one batch run on `landing`, or on `hotfix`, a hotfix's own pile
  (INFRA-286). When it is green and main has reached its commit, it lists each
  issue the batch carried to main: those are merged, and the foreman closes them
  and sets them Done. The batch is the commits after the last earlier green
  batch run on either pile, or after `--since`, up to the run's commit. A merge
  that brought main into the pile carries no issue of its own: what it brought
  was merged by its own run.

A red batch takes nothing off landing (INFRA-288): bad-commit.py names the bad
change and prints the message for its worker, who fixes it on top. So every
issue a green batch carries, the named one and its fix included, is merged.

It finds issues the same way as bad-commit.py, so the two cannot disagree on
whose a commit is.
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bad_commit", os.path.join(HERE, "bad-commit.py"))
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)
project_fact = bc.project_fact

MAIN_REF = "refs/remotes/{}/{}".format(bc.REMOTE, bc.MAIN)
# The piles a batch run moves main from: the milestone pile and a hotfix's own pile (INFRA-286).
PILES = (bc.LANDING, "hotfix")

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
    # The hotfix pile may not exist; a green run's commit is read from main either way.
    git("fetch", "--quiet", "--no-tags", bc.REMOTE, "+refs/heads/hotfix:refs/remotes/{}/hotfix".format(bc.REMOTE),
        check=False)


def commits(spec):
    """[(sha, message)] for the commits `spec` names (a range or a ref), oldest first. Merges are left
    out: workers rebase, so a merge on a pile only brings main in, and what it brings was merged by the
    run that moved main there (INFRA-286)."""
    out = git("log", "--reverse", "--no-merges", "--format=%H%x1f%B%x1e", spec).stdout
    found = []
    for entry in out.split("\x1e"):
        if "\x1f" in entry:
            sha, body = entry.split("\x1f", 1)
            found.append((sha.strip(), body))
    return found


# ---- merged -----------------------------------------------------------------

RUN_FIELDS = "databaseId,status,conclusion,headSha,headBranch,url,workflowName,createdAt"


def earlier_green(run):
    """The commit of the newest earlier green batch run of the same workflow, on either pile, that is
    an ancestor of this run's commit, or None. A hotfix's green run counts, so a later batch that brought
    main in does not carry the hotfix again (INFRA-286)."""
    listed = []
    for pile in PILES:
        listed += bc.gh_json("run", "list", "--workflow", run.get("workflowName") or "", "--branch", pile,
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
    if run.get("headBranch") not in PILES:
        raise Stop("Run {} is not a batch run on landing or hotfix (it ran on {}), so nothing counts as merged."
                   .format(url, run.get("headBranch")))
    if run.get("status") != "completed":
        raise Stop("Run {} has not finished, so nothing counts as merged yet. Read it again when it ends."
                   .format(url))
    if run.get("conclusion") != "success":
        if run.get("headBranch") != bc.LANDING:
            raise Stop("Run {} is {}, not green, so nothing counts as merged and main did not move. The search "
                       "reads landing only: read the run. When its Gate failed, hand the hotfix back to its worker "
                       "to fix on top on hotfix; when only its move failed because main moved, start its go again."
                       .format(url, run.get("conclusion")))
        raise Stop("Run {} is {}, not green, so nothing counts as merged and main did not move. Run the "
                   "search on it (bad-commit.py {}) and hand the change it names back to its worker."
                   .format(url, run.get("conclusion"), run_id))
    if git("merge-base", "--is-ancestor", head, MAIN_REF, check=False).returncode != 0:
        raise Stop("Run {} is green, but main has not reached its commit {}, so nothing counts as merged "
                   "yet. Read the run's move job.".format(url, head[:9]))
    base = since or earlier_green(run)
    if not base:
        raise Stop("No earlier green batch run on landing or hotfix is an ancestor of {}, so where this batch "
                   "starts is not known. Run again with --since <the commit main was on before this batch>."
                   .format(head[:9]))
    if not known(base):
        raise Stop("--since {} is not a commit in this checkout.".format(base))

    issues = []
    for sha, _ in commits("{}..{}".format(base, head)):
        issue = bc.issue_of(sha, root)
        if issue != bc.NO_ISSUE and issue not in issues:
            issues.append(issue)

    say("Batch run {}: green, and main has reached {}. The batch is {}..{}.".format(url, head[:9], base[:9],
                                                                                      head[:9]))
    say("Merged, close and set Done: {}".format(", ".join(issues) if issues else "none"))
    return 0


def main(argv):
    try:
        root = project_fact.repo_root(None, os.getcwd())
    except project_fact.RepoUnclear as unclear:
        say(str(unclear))
        return 2
    try:
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
    say("Usage: batch-issues.py merged <batch run id> [--since <commit>]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
