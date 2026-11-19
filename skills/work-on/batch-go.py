#!/usr/bin/env python3
"""Start one batch run when the person says go (INFRA-285).

Commits pile up on `landing` with no run at all; a push starts nothing. The
batch run starts only when the person says go, for a milestone or, where no
milestone exists, for a set of issues they name. Robert, November 19, 2026:
"Isn't the whole point of this change is to keep throwing things on the
landing until I say: go to main?", "batch means milestone", "and when no
milestone exists, then it is a set of issues I say: go on to make a push",
and "I can say go when I want."

The foreman runs this from a checkout of the repository the moment the person
says go:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-go.py --milestone "<name>" <issue> [<issue> ...]
    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-go.py <issue> [<issue> ...]

The issues are the milestone's issues, read from the tracker, or the ones the
person named: Linear keys such as INFRA-285, or GitHub numbers such as #1418.

It reads `main` and `landing` from GitHub and checks that every commit on
`landing` past main belongs to one of those issues, since the run tests
landing's last commit and a green run moves main to exactly that commit. A
commit of any other issue stops it, and it names each such commit and its
issue. Then it starts the starter file, `masthead-batch.yml`, on `landing`
once, with landing's last commit, so the run tests the pile this script
checked and no other: the run's plan step stops when landing moved in between.

`--check` checks the pile and starts nothing.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "hooks"))
import project_fact  # noqa: E402

REMOTE = "origin"
LANDING = "landing"
MAIN = "main"
STARTER = "masthead-batch.yml"
LINEAR_KEY = re.compile(r"^([A-Z][A-Z0-9]{0,9})-\d+$")
GITHUB_KEY = re.compile(r"^#?(\d+)$")
OWNER_LINE = re.compile(r"\s*(fixes|closes|resolves|refs)\b", re.I)


class Stop(Exception):
    """Nothing starts, and the message says why."""


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Stop("git {} failed: {}".format(" ".join(args[:2]), (r.stderr or r.stdout).strip()))
    return r


def keys_of(words):
    """The issue keys the person named, written one way: INFRA-285, or #1418."""
    keys = []
    for word in words:
        for part in re.split(r"[\s,]+", word.strip()):
            if not part:
                continue
            m = LINEAR_KEY.match(part.upper())
            g = GITHUB_KEY.match(part)
            if m:
                key = part.upper()
            elif g:
                key = "#" + g.group(1)
            else:
                raise Stop("'{}' is not an issue: name each as a Linear key such as INFRA-285 "
                           "or a GitHub number such as #1418.".format(part))
            if key not in keys:
                keys.append(key)
    if not keys:
        raise Stop("No issue was named, so nothing starts. Name the milestone's issues, or the issues to send to main.")
    return keys


def key_pattern(keys, team):
    """What counts as an issue key in a commit message: the families of the named keys and the team's."""
    prefixes = {LINEAR_KEY.match(k).group(1) for k in keys if LINEAR_KEY.match(k)}
    if team:
        prefixes.add(team)
    parts = []
    if prefixes:
        parts.append(r"\b(?:{})-\d+\b".format("|".join(sorted(map(re.escape, prefixes)))))
    if any(k.startswith("#") for k in keys) or not prefixes:
        parts.append(r"(?<![\w/])#\d+\b")
    return re.compile("|".join(parts))


def owner(body, pattern):
    """The issue a commit belongs to, the way bad-commit.py reads it: a Fixes or refs line first,
    then the subject, then the rest, and within a line the last key. None when it names none."""
    lines = body.splitlines()
    for line in [l for l in lines if OWNER_LINE.match(l)] + lines:
        found = pattern.findall(line)
        if found:
            return found[-1].upper()
    return None


def pile(pattern):
    """[(sha, subject, issue)] for each commit on landing past main, oldest first."""
    out = git("log", "--reverse", "--format=%H%x1f%s%x1f%B%x1e",
              "refs/remotes/{0}/{1}..refs/remotes/{0}/{2}".format(REMOTE, MAIN, LANDING)).stdout
    found = []
    for entry in out.split("\x1e"):
        if "\x1f" not in entry:
            continue
        sha, subject, body = entry.split("\x1f", 2)
        found.append((sha.strip(), subject.strip(), owner(body, pattern)))
    return found


def go(argv):
    milestone, check_only, words = None, False, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--milestone":
            if i + 1 >= len(argv) or not argv[i + 1].strip():
                raise Stop("--milestone needs the milestone's name.")
            milestone = argv[i + 1].strip()
            i += 2
            continue
        if arg == "--check":
            check_only = True
        elif arg in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        elif arg.startswith("--"):
            raise Stop("Unknown option {}.".format(arg))
        else:
            words.append(arg)
        i += 1
    keys = keys_of(words)
    name = "milestone {}".format(milestone) if milestone else "issues " + " ".join(keys)

    top = git("rev-parse", "--show-toplevel").stdout.strip()
    os.chdir(top)
    os.environ.setdefault("CLAUDE_PROJECT_DIR", top)
    git("fetch", "--quiet", "--no-tags", REMOTE,
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(MAIN, REMOTE),
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(LANDING, REMOTE))
    if project_fact.ships(top) != project_fact.SHIPS_BATCH:
        raise Stop("This repository has no batch run: landing on GitHub holds no {} starter with a stored Gate, so "
                   "nothing starts. Run /masthead:setup to opt in, or start the Gate on landing by hand."
                   .format(STARTER))
    head = git("rev-parse", "refs/remotes/{}/{}^{{commit}}".format(REMOTE, LANDING)).stdout.strip()
    if git("merge-base", "--is-ancestor", "refs/remotes/{}/{}".format(REMOTE, MAIN), head, check=False).returncode:
        raise Stop("Main holds a commit landing does not, so a green run could not move main to landing. "
                   "Nothing starts.")

    commits = pile(key_pattern(keys, project_fact.linear_team(top)))
    if not commits:
        raise Stop("Landing holds nothing main does not, so there is nothing to test and nothing starts.")
    strays = [(sha, subject, issue) for sha, subject, issue in commits if issue not in keys]
    if strays:
        lines = ["Landing holds {} commit{} outside {}, so nothing starts. A run tests all of landing, and a green "
                 "run moves main to all of it, so these would go to main too:".format(
                     len(strays), "" if len(strays) == 1 else "s", name)]
        lines += ["  {} {} ({})".format(sha[:9], subject, issue or "names no issue") for sha, subject, issue in strays]
        named = sorted({issue for _, _, issue in strays if issue})
        if named:
            lines.append("To send them to main as well, say go again with {} named too.".format(" ".join(named)))
        if any(issue is None for _, _, issue in strays):
            lines.append("A commit that names no issue goes nowhere until someone finds whose it is.")
        raise Stop("\n".join(lines))

    carried = [k for k in keys if any(issue == k for _, _, issue in commits)]
    absent = [k for k in keys if k not in carried]
    print("The pile for {}: {} commit{} on landing past main, up to {}.".format(
        name, len(commits), "" if len(commits) == 1 else "s", head[:9]))
    for sha, subject, issue in commits:
        print("  {} {} ({})".format(sha[:9], subject, issue))
    if absent:
        print("Nothing on the pile for {}: already on main, or not landed yet.".format(" ".join(absent)))
    if check_only:
        print("Checked only; nothing started.")
        return 0

    r = subprocess.run(["gh", "workflow", "run", STARTER, "--ref", LANDING,
                        "-f", "pile=" + name, "-f", "issues=" + " ".join(carried), "-f", "sha=" + head],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Stop("GitHub did not start the batch run: {}".format((r.stderr or r.stdout).strip()))
    print("Started one batch run on landing at {} for {}. Main moves to {} only when it is green.".format(
        head[:9], name, head[:9]))
    print("Watch it: gh run list --workflow {} --event workflow_dispatch --limit 1".format(STARTER))
    return 0


def main(argv):
    try:
        return go(argv)
    except Stop as stop:
        print(str(stop), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
