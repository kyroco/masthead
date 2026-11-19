#!/usr/bin/env python3
"""Refuse to push a change to the CI checks that carries no OK line (INFRA-274).

Robert, November 19, 2026: "any time we add a lane to CI I want to know why" and
"I want it caught before it hits github". The OK is the person's own words quoted
in a comment on the issue; the commit points to that comment with a line

    CI-change-OK: <link to the comment>

Usage: ci_change_ok.py REV. Run from the top of the checkout. It reads every commit
REV holds that no remote-tracking branch holds, which is what the push sends as far
as this checkout knows. Each such commit that adds, changes, moves or deletes a file
under .github/ or scripts/ci/ needs its own line. Exit 0 when every one has it, 1
with the reason on stdout when one does not.

What it trusts: the line itself. It does not read the tracker to see that the
comment exists or that its words are an OK. Sessions that push are trusted (Robert,
November 19, 2026), so this catches a mistake, not a session that writes the line
without an OK.
"""
import re
import subprocess
import sys

PATHS = (".github/", "scripts/ci/")
OK_LINE = re.compile(r"^CI-change-OK:[ \t]*(\S+)[ \t]*$", re.M)
# A link to one comment: Linear's #comment-<id>, GitHub's #issuecomment-<n>.
COMMENT_LINK = re.compile(r"^https?://\S+#(comment-[0-9A-Za-z-]+|issuecomment-[0-9]+)$")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def changed_files(commit):
    """The files COMMIT touches against its first parent, both names of a move."""
    parents = git("rev-list", "--parents", "-n", "1", commit).split()[1:]
    base = parents[:1] or ["--root"]
    return git("diff-tree", "-r", "--no-renames", "--no-commit-id", "--name-only", *base, commit).splitlines()


def main(rev):
    try:
        commits = git("rev-list", "--reverse", rev, "--not", "--remotes").split()
    except subprocess.CalledProcessError:
        return 0  # nothing git can name is sent; the push itself will say so
    missing = []
    for commit in commits:
        ci = [f for f in changed_files(commit) if f.startswith(PATHS)]
        if not ci:
            continue
        links = OK_LINE.findall(git("log", "-1", "--format=%B", commit))
        if any(COMMENT_LINK.match(link) for link in links):
            continue
        why = "its CI-change-OK line does not point to a comment" if links else "it has no CI-change-OK line"
        missing.append((commit[:10], git("log", "-1", "--format=%s", commit).strip(), why, ci))
    if not missing:
        return 0
    print("this push carries a change to the CI checks (a file under .github/ or scripts/ci/) without the person's OK on record.")
    for short, subject, why, files in missing:
        print(f"  {short} {subject}: {why}. It changes {', '.join(files)}")
    print("The OK is the person's own words (\"OK\", \"OK makes sense\") in a comment on the issue, asked for with the reason for the change."
          " Once they have said it, add a line to each commit above, then push again:\n"
          "  CI-change-OK: <link to that comment, such as https://linear.app/<team>/issue/KOR-12/<slug>#comment-<id>>")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "HEAD"))
