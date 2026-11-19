#!/usr/bin/env python3
"""Refuse to push a change to the CI checks that carries no OK line (INFRA-274).

Robert, November 19, 2026: "any time we add a lane to CI I want to know why" and
"I want it caught before it hits github". The OK is the person's own words quoted
in a comment on the issue; the commit points to that comment with a line

    CI-change-OK: <link to the comment>

Usage: printf '%s\\n' SOURCE... | ci_change_ok.py, from the top of the checkout.
Each SOURCE is what one push of the command line sends: a ref, HEAD, or --branches,
--all or --tags for a push of many. A source git cannot name (a branch written
through the shell, such as "$B", or a glob) is read as every local branch and HEAD,
since what it sends is not known. It reads every commit those hold that no
remote-tracking branch holds, which is what the pushes send as far as this checkout
knows. Each such commit that adds, changes, moves or deletes a file under .github/
or scripts/ci/ needs its own line. A merge counts only the files it leaves different
from every parent, so bringing in a change that is already on origin asks for
nothing.

A line "moves SUB" says a git command that makes or moves a commit runs ahead of the
push, so the commits, and their messages, can change after this reads them. A merge,
cherry-pick, revert, reset, am, checkout, switch or branch repoint can bring in a CI
change from a commit origin already holds, so that line is refused, with the advice
to run that command on its own first. For a commit, rebase or pull, whose new commits
come only from local ones, every local branch, HEAD and the files not committed yet
are read, and the line is refused when any of them touches a CI file, OK line or
not. Otherwise it adds nothing.

Exit 0 when all is well, 1 with the reason on stdout when not.

What it trusts: the line itself. It does not read the tracker to see that the
comment exists or that its words are an OK. Sessions that push are trusted (Robert,
November 19, 2026), so this catches a mistake, not a session that writes the line
without an OK.
"""
import re
import subprocess
import sys

PATHS = (".github/", "scripts/ci/")
MANY = {"--branches", "--all", "--tags"}
WIDE = ["HEAD", "--branches"]
# The commands ahead of a push whose new commits come only from local ones: a commit is made from the files
# not committed yet, and a rebase or pull replays local commits onto origin's. Every other one is refused.
KEEPS = {"commit", "rebase", "pull"}
OK_LINE = re.compile(r"^[ \t]*CI-change-OK:[ \t]*(\S+)[ \t]*$", re.M)
# A link to one comment: Linear's #comment-<id>, GitHub's #issuecomment-<n>.
COMMENT_LINK = re.compile(r"^https?://\S+#(comment-[0-9A-Za-z-]+|issuecomment-[0-9]+)$")
ADVICE = ("The OK is the person's own words (\"OK\", \"OK makes sense\") in a comment on the issue, asked for with the"
          " reason for the change. Once they have said it, add a line to each commit above, then push again:\n"
          "CI-change-OK: <link to that comment, such as https://linear.app/<team>/issue/KOR-12/<slug>#comment-<id>>")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout.decode("utf-8", "surrogateescape")


def names(*args):
    """Paths from a git command run with -z, so no name comes back quoted."""
    return [p for p in git(*args).split("\0") if p]


def ci(paths):
    return sorted({p for p in paths if p.startswith(PATHS)})


def resolvable(rev):
    if rev in MANY:
        return True
    return subprocess.run(["git", "rev-parse", "--verify", "-q", rev + "^{commit}"], capture_output=True).returncode == 0


def changed_files(commit):
    """The files COMMIT touches, both names of a move. A merge counts a file only when it differs from every parent."""
    parents = git("rev-list", "--parents", "-n", "1", commit).split()[1:]
    if len(parents) > 1:
        return names("diff-tree", "-r", "-c", "--no-renames", "--no-commit-id", "--name-only", "-z", commit)
    base = parents or ["--root"]
    return names("diff-tree", "-r", "--no-renames", "--no-commit-id", "--name-only", "-z", *base, commit)


def unsent_ci_commits(revs):
    """Each commit REVS hold that no remote-tracking branch holds and that touches a CI file, with those files."""
    revs = list(dict.fromkeys(r for r in revs if resolvable(r)))
    commits = git("rev-list", "--reverse", *revs, "--not", "--remotes").split() if revs else []
    return [(c, files) for c in commits for files in [ci(changed_files(c))] if files]


def describe(commit, files, why=""):
    subject = git("log", "-1", "--format=%s", commit).strip()
    return f"  {commit[:10]} {subject}{': ' + why if why else ''}. It changes {', '.join(files)}"


def main(lines):
    moved = next((line[6:] for line in lines if line.startswith("moves ")), "")
    revs = []
    for line in lines:
        if line and not line.startswith("moves "):
            revs.extend([line] if resolvable(line) else WIDE)
    if moved and moved not in KEEPS:
        # A merge, cherry-pick, revert, reset, checkout or branch repoint can bring in a CI change from a
        # commit origin already holds, which nothing here can read before it is made.
        print(f"this command runs 'git {moved}' before it pushes, and that can change which commits are pushed, or their"
              " messages, after this check reads them, so a change to the CI checks (files under .github/ or scripts/ci/)"
              " could go out without the person's OK.")
        print(f"Run 'git {moved}' on its own, then push, so this check reads the commits as they will go.")
        return 1
    if moved:
        against =["HEAD"] if resolvable("HEAD") else ["--cached"]  # no commit yet: what is staged
        pending = ci(names("diff", "--name-only", "--no-renames", "-z", *against)
                     + names("ls-files", "--others", "--exclude-standard", "-z"))
        found = [describe(c, files) for c, files in unsent_ci_commits(revs + WIDE)]
        if pending:
            found.append(f"  not committed yet: {', '.join(pending)}")
        if not found:
            return 0
        print(f"this command runs 'git {moved}' before it pushes, and that can change which commits are pushed, or their"
              " messages, after this check reads them, while these changes to the CI checks (files under .github/ or"
              " scripts/ci/) are not on GitHub yet:")
        print("\n".join(found))
        print(f"Run 'git {moved}' on its own, then push, so this check reads the commits as they will go."
              " Each commit that changes the CI checks needs a CI-change-OK line pointing to the comment where the person said OK.")
        return 1
    missing = []
    for commit, files in unsent_ci_commits(revs):
        links = OK_LINE.findall(git("log", "-1", "--format=%B", commit))
        if any(COMMENT_LINK.match(link) for link in links):
            continue
        why = "its CI-change-OK line does not point to a comment" if links else "it has no CI-change-OK line"
        missing.append(describe(commit, files, why))
    if not missing:
        return 0
    print("this push carries a change to the CI checks (a file under .github/ or scripts/ci/) without the person's OK on record.")
    print("\n".join(missing))
    print(ADVICE)
    return 1


if __name__ == "__main__":
    sys.exit(main([line.strip() for line in sys.stdin.read().splitlines() if line.strip()] or ["HEAD"]))
