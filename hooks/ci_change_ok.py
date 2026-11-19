#!/usr/bin/env python3
"""Refuse to push a change to the CI checks that carries no OK line (INFRA-274).

Robert, November 19, 2026: "any time we add a lane to CI I want to know why" and
"I want it caught before it hits github". The OK is the person's own words quoted
in a comment on the issue; the commit points to that comment with a line

    CI-change-OK: <link to the comment>

Usage: ci_change_ok.py [--uncommitted] REV... Run from the top of the checkout.
Each REV is what one push sends: a ref, HEAD, or --branches, --all or --tags. It
reads every commit those hold that no remote-tracking branch holds, which is what
the pushes send as far as this checkout knows. Each such commit that adds, changes,
moves or deletes a file under .github/ or scripts/ci/ needs its own line. A merge
counts only the files it leaves different from every parent, so bringing in a
change that is already on origin asks for nothing. --uncommitted is for a line that
commits and then pushes: a CI file changed but not committed yet is refused, since
the commit that will carry it cannot be read. Exit 0 when all is well, 1 with the
reason on stdout when not.

What it trusts: the line itself. It does not read the tracker to see that the
comment exists or that its words are an OK. Sessions that push are trusted (Robert,
November 19, 2026), so this catches a mistake, not a session that writes the line
without an OK.
"""
import os
import re
import subprocess
import sys

PATHS = (".github/", "scripts/ci/")
MANY = {"--branches", "--all", "--tags"}
OK_LINE = re.compile(r"^[ \t]*CI-change-OK:[ \t]*(\S+)[ \t]*$", re.M)
# A link to one comment: Linear's #comment-<id>, GitHub's #issuecomment-<n>.
COMMENT_LINK = re.compile(r"^https?://\S+#(comment-[0-9A-Za-z-]+|issuecomment-[0-9]+)$")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout.decode("utf-8", "surrogateescape")


def names(*args):
    """Paths from a git command run with -z, so no name comes back quoted."""
    return [p for p in git(*args).split("\0") if p]


def ci(paths):
    return sorted({p for p in paths if p.startswith(PATHS)})


def changed_files(commit):
    """The files COMMIT touches, both names of a move. A merge counts a file only when it differs from every parent."""
    parents = git("rev-list", "--parents", "-n", "1", commit).split()[1:]
    if len(parents) > 1:
        return names("diff-tree", "-r", "-c", "--no-renames", "--no-commit-id", "--name-only", "-z", commit)
    base = parents or ["--root"]
    return names("diff-tree", "-r", "--no-renames", "--no-commit-id", "--name-only", "-z", *base, commit)


def resolvable(rev):
    if rev in MANY:
        return True
    return subprocess.run(["git", "rev-parse", "--verify", "-q", rev + "^{commit}"], capture_output=True).returncode == 0


def main(args):
    uncommitted = "--uncommitted" in args
    revs = [r for r in args if r != "--uncommitted" and resolvable(r)]
    lines = []
    if uncommitted:
        against = ["HEAD"] if resolvable("HEAD") else ["--cached"]  # no commit yet: what is staged
        pending = ci(names("diff", "--name-only", "--no-renames", "-z", *against)
                     + names("ls-files", "--others", "--exclude-standard", "-z"))
        if pending:
            lines.append(f"  not committed yet: {', '.join(pending)}. This line commits and pushes at once, so that commit cannot be"
                         " read before it goes. Commit it on its own first, with its CI-change-OK line, then push.")
    commits = git("rev-list", "--reverse", *revs, "--not", "--remotes").split() if revs else []
    for commit in commits:
        files = ci(changed_files(commit))
        if not files:
            continue
        links = OK_LINE.findall(git("log", "-1", "--format=%B", commit))
        if any(COMMENT_LINK.match(link) for link in links):
            continue
        why = "its CI-change-OK line does not point to a comment" if links else "it has no CI-change-OK line"
        subject = git("log", "-1", "--format=%s", commit).strip()
        lines.append(f"  {commit[:10]} {subject}: {why}. It changes {', '.join(files)}")
    if not lines:
        return 0
    print("this push carries a change to the CI checks (a file under .github/ or scripts/ci/) without the person's OK on record.")
    print("\n".join(lines))
    print("The OK is the person's own words (\"OK\", \"OK makes sense\") in a comment on the issue, asked for with the reason for the change."
          " Once they have said it, add a line to each commit above, then push again:\n"
          "CI-change-OK: <link to that comment, such as https://linear.app/<team>/issue/KOR-12/<slug>#comment-<id>>")
    return 1


if __name__ == "__main__":
    os.environ.setdefault("GIT_OPTIONAL_LOCKS", "0")
    sys.exit(main(sys.argv[1:] or ["HEAD"]))
