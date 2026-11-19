#!/usr/bin/env python3
"""Start one batch run when the person says go (INFRA-285), and a hotfix's run as soon as it lands (INFRA-286).

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

A hotfix has its own pile, the branch `hotfix` (INFRA-286). Robert, November
19, 2026: "fine, figure out a way to make its own pile. On a hot fix, we land
and push that fix to main." Its worker lands it on `hotfix`, cut from main, and
the foreman starts its run as soon as it lands, with no wait for a go:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/batch-go.py --hotfix <issue> [<issue> ...]

The same checks run on `hotfix` instead of `landing`, and a green run moves main
to the hotfix alone. The milestone pile on `landing` is left as it is. Main then
holds the hotfix and `landing` does not, so the next go on a pile behind main
first makes one merge of main into it (with no checkout, and pushed plainly,
never forced; a push that loses the race with a worker landing is made again
on the new head) and starts the run on that merge. The run then tests the pile
with the hotfix, and a green run moves main to both. The pile check passes
over a merge that brings in only commits main already holds.

`--base` prints the branch a worker rebases onto before it lands on the pile:
`origin/landing`, or with `--hotfix`, `origin/hotfix` while a hotfix waits
there and `origin/main` otherwise. It starts nothing.
"""
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))
import project_fact  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The starter's triggers are read the way setup reads every workflow's.
gate = _load("gate", os.path.join(PLUGIN, "skills", "setup", "gate.py"))

REMOTE = "origin"
LANDING = "landing"
HOTFIX = "hotfix"
MAIN = "main"
STARTER = "masthead-batch.yml"
# The push check of INFRA-274, run on the merge a go makes before it is pushed.
CI_CHECK = os.path.join(PLUGIN, "hooks", "ci_change_ok.py")
# A push of that merge that loses the race with a worker landing at the same moment is made again on the
# new head; past this many tries the go stops and says so.
PUSH_TRIES = 3
LINEAR_KEY = re.compile(r"^([A-Z][A-Z0-9]{0,9})-\d+$")
GITHUB_KEY = re.compile(r"^#?(\d+)$")
OWNER_LINE = re.compile(r"\s*(fixes|closes|resolves|refs)\b", re.I)
# Any Linear key, for a commit that names an issue of another team or tracker than the go's (s3-J1):
# read only from a Fixes or refs line that names keys and nothing else ("Fixes ENG-5", "refs ENG-5,
# ENG-6"), or in brackets at the end of the subject, as the house style writes them. A sentence such as
# "Fixes UTF-8 decoding" names no issue (J-1).
_KEY = r"[A-Z][A-Z0-9]{1,9}-\d+"
# Read with the same case rule as KEYS_ONLY, so a line it takes always yields a key ("refs eng-8").
ANY_KEY = re.compile(r"\b{}\b".format(_KEY), re.I)
KEYS_ONLY = re.compile(r"^\s*(?:fixes|closes|resolves|refs)\s+{0}(?:\s*,?\s*(?:and\s+)?{0})*\s*\.?\s*$".format(_KEY),
                       re.I)
SUBJECT_KEY = re.compile(r"\(({})\)\s*$".format(_KEY))


class Stop(Exception):
    """Nothing starts, and the message says why."""


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Stop("git {} failed: {}".format(" ".join(args[:2]), (r.stderr or r.stdout).strip()))
    return r


def tracking(branch):
    return "refs/remotes/{}/{}".format(REMOTE, branch)


def rev(ref):
    r = git("rev-parse", "--verify", "-q", ref + "^{commit}", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def is_ancestor(a, b):
    return git("merge-base", "--is-ancestor", a, b, check=False).returncode == 0


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
    owning = [l for l in lines if OWNER_LINE.match(l)]
    for line in owning + lines:
        found = pattern.findall(line)
        if found:
            return found[-1].upper()
    for line in owning:
        if KEYS_ONLY.match(line):
            return ANY_KEY.findall(line)[-1].upper()
    m = SUBJECT_KEY.search(lines[0]) if lines else None
    return m.group(1) if m else None


def log(spec, pattern, *extra):
    """[(sha, parents, subject, issue)] for each commit of `git log spec`, oldest first."""
    out = git("log", "--reverse", *extra, "--format=%H%x1f%P%x1f%s%x1f%B%x1e", spec).stdout
    found = []
    for entry in out.split("\x1e"):
        if "\x1f" not in entry:
            continue
        sha, parents, subject, body = entry.split("\x1f", 3)
        found.append((sha.strip(), parents.split(), subject.strip(), owner(body, pattern)))
    return found


def pile(pattern, head):
    """[(sha, subject, issue, merge)] for each commit of `head` past main, oldest first. `merge` is
    true for a merge whose other parents are all on main: it brings in only work main already holds,
    such as a hotfix (INFRA-286), so it belongs to no issue and is passed over. A red batch puts
    nothing on the pile (INFRA-288: its bad change is fixed on top), so every other commit is a
    worker's."""
    found = []
    for sha, parents, subject, issue in log("{}..{}".format(tracking(MAIN), head), pattern):
        merge = len(parents) > 1 and all(is_ancestor(p, tracking(MAIN)) for p in parents[1:])
        found.append((sha, subject, None if merge else issue, merge))
    return found


def starter_on(branch):
    """Stop unless the starter on the pile's branch starts on a go and on nothing else (s3-C1)."""
    path = project_fact.STARTER_FILE
    text = git("show", "{}:{}".format(tracking(branch), path), check=False).stdout
    starts = gate.triggers(text)
    if "workflow_dispatch" not in starts or "push" in starts:
        raise Stop("The starter on {}, {}, is the older one: it runs on every push to landing and a go cannot "
                   "start it, so nothing starts. Run /masthead:setup to write it again (batch.py write), and land "
                   "it with the person's OK for the change to .github/.".format(branch, path))


def fetch(branch):
    """Read main and the pile's branch from GitHub. False when GitHub has no such branch."""
    git("fetch", "--quiet", "--no-tags", REMOTE, "+refs/heads/{0}:refs/remotes/{1}/{0}".format(MAIN, REMOTE))
    if git("fetch", "--quiet", "--no-tags", REMOTE,
           "+refs/heads/{0}:refs/remotes/{1}/{0}".format(branch, REMOTE), check=False).returncode == 0:
        return True
    if git("ls-remote", "--exit-code", "--heads", REMOTE, branch, check=False).returncode == 2:
        git("update-ref", "-d", tracking(branch), check=False)
        return False
    raise Stop("Could not read {} from GitHub, so nothing starts.".format(branch))


def base(branch):
    """The branch a worker rebases onto before it lands on the pile, and what to do next (INFRA-286)."""
    present = fetch(branch)
    if branch == HOTFIX and (not present or is_ancestor(tracking(HOTFIX), tracking(MAIN))):
        return "{}/{}".format(REMOTE, MAIN), ("No hotfix waits on {0}, so rebase onto main, then land with "
                                              "git push origin HEAD:{0}.".format(HOTFIX))
    if not present:
        return "{}/{}".format(REMOTE, MAIN), ("GitHub has no {0} yet, so rebase onto main; your push of "
                                              "HEAD:{0} makes it.".format(branch))
    return "{}/{}".format(REMOTE, branch), "Rebase onto it, then land with git push origin HEAD:{}.".format(branch)


def merge_main_into(branch, head, pattern):
    """One merge of main into the pile's head, made with no checkout (INFRA-286). Stops on a
    conflict, and on a change to the CI checks the push check would refuse (INFRA-274)."""
    r = git("merge-tree", "--write-tree", "--name-only", "--no-messages", head, tracking(MAIN), check=False)
    if r.returncode == 1:
        files = [l for l in r.stdout.splitlines()[1:] if l.strip()]
        # git stops on any conflict: the same lines changed on both sides, or a file one side deletes or
        # renames and the other changes (s3-2).
        raise Stop("Main and {0} cannot be put together on their own: they change the same lines of a file, or one "
                   "deletes or renames a file the other changes. So the go cannot bring main into {0}, and nothing "
                   "starts. A worker merges origin/main into {0} by hand and lands the merge, then say go again. "
                   "The files: {1}".format(branch, ", ".join(files) or "not named by git"))
    if r.returncode != 0:
        raise Stop("git could not merge main into {}: {}".format(branch, (r.stderr or r.stdout).strip()))
    tree = r.stdout.split()[0]
    issues = []
    for _, _, _, issue in log("{}..{}".format(head, tracking(MAIN)), pattern, "--no-merges"):
        if issue and issue not in issues:
            issues.append(issue)
    subject = "Bring main into {} for the go".format(branch) + (" ({})".format(", ".join(issues)) if issues else "")
    sha = git("commit-tree", tree, "-p", head, "-p", tracking(MAIN), "-m", subject).stdout.strip()
    check = subprocess.run([sys.executable, CI_CHECK], input=sha + "\n", capture_output=True, text=True)
    if check.returncode != 0:
        raise Stop("The merge of main into {0} changes the CI checks in a way neither side did alone, and the push "
                   "check refuses that without the person's OK, so nothing was pushed and nothing starts. A worker "
                   "merges origin/main into {0} by hand, with the OK line, and lands it. The check said:\n{1}".format(
                       branch, (check.stdout or check.stderr).strip()))
    return sha


def check_pile(commits, keys, name, branch):
    """Stop when the pile holds a commit of an issue the go did not name, or of none."""
    if not any(not merge for _, _, _, merge in commits):
        raise Stop("{} holds nothing main does not, so there is nothing to test and nothing starts.".format(
            branch.capitalize()))
    strays = [(sha, subject, issue) for sha, subject, issue, merge in commits if not merge and issue not in keys]
    if not strays:
        return
    lines = ["{} holds {} commit{} outside {}, so nothing starts. A run tests all of {}, and a green "
             "run moves main to all of it, so these would go to main too:".format(
                 branch.capitalize(), len(strays), "" if len(strays) == 1 else "s", name, branch)]
    lines += ["  {} {} ({})".format(sha[:9], subject, issue or "names no issue") for sha, subject, issue in strays]
    named = sorted({issue for _, _, issue in strays if issue})
    if named:
        lines.append("To send them to main as well, say go again with {} named too.".format(" ".join(named)))
    if any(issue is None for _, _, issue in strays):
        lines.append("A commit that names no issue goes nowhere until someone finds whose it is.")
    raise Stop("\n".join(lines))


def go(argv):
    milestone, check_only, hotfix, want_base, words = None, False, False, False, []
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
        elif arg == "--hotfix":
            hotfix = True
        elif arg == "--base":
            want_base = True
        elif arg in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        elif arg.startswith("--"):
            raise Stop("Unknown option {}.".format(arg))
        else:
            words.append(arg)
        i += 1
    branch = HOTFIX if hotfix else LANDING
    if hotfix and milestone:
        raise Stop("A hotfix has its own pile and is not part of a milestone; name only its issues with --hotfix.")

    top = git("rev-parse", "--show-toplevel").stdout.strip()
    os.chdir(top)
    os.environ.setdefault("CLAUDE_PROJECT_DIR", top)
    if want_base:
        ref, what = base(branch)
        print(ref)
        print(what, file=sys.stderr)
        return 0

    keys = keys_of(words)
    name = ("hotfix " + " ".join(keys)) if hotfix else (
        "milestone {}".format(milestone) if milestone else "issues " + " ".join(keys))
    fetch(LANDING)
    if project_fact.ships(top) != project_fact.SHIPS_BATCH:
        raise Stop("This repository has no batch run: landing on GitHub holds no {} starter with a stored Gate, so "
                   "nothing starts. Run /masthead:setup to opt in, or start the Gate on landing by hand."
                   .format(STARTER))
    if hotfix and not fetch(HOTFIX):
        raise Stop("GitHub has no {0} branch, so there is no hotfix to send and nothing starts. The hotfix's worker "
                   "lands it with git push origin HEAD:{0} first.".format(HOTFIX))
    pattern = key_pattern(keys, project_fact.linear_team(top))

    for attempt in range(1, PUSH_TRIES + 1):
        starter_on(branch)
        head = rev(tracking(branch))
        commits = pile(pattern, head)
        check_pile(commits, keys, name, branch)
        behind = not is_ancestor(tracking(MAIN), head)
        if not behind:
            break
        # --check makes the merge too, pushing nothing, so it promises a merge only the go could make (s3-1).
        merged = merge_main_into(branch, head, pattern)
        if check_only:
            break
        push = git("push", "--quiet", REMOTE, "{}:refs/heads/{}".format(merged, branch), check=False)
        if push.returncode == 0:
            git("update-ref", tracking(branch), merged)
            print("Main held work {} did not, so the go brought main into {} with one merge, {}.".format(
                branch, branch, merged[:9]))
            head, commits = merged, pile(pattern, merged)
            break
        moved = fetch(branch) and rev(tracking(branch)) != head
        if not moved:
            raise Stop("GitHub refused the merge of main into {}: {}\nNothing starts.".format(
                branch, (push.stderr or push.stdout).strip()))
        if attempt == PUSH_TRIES:
            raise Stop("{} moved each time the go pushed its merge of main, {} times, so nothing starts. Say go again "
                       "once workers stop landing.".format(branch.capitalize(), PUSH_TRIES))
        print("{} moved while the go pushed its merge of main; checking the new pile and trying again.".format(
            branch.capitalize()))

    carried = [k for k in keys if any(issue == k for _, _, issue, _ in commits)]
    absent = [k for k in keys if k not in carried]
    print("The pile for {}: {} commit{} on {} past main, up to {}.".format(
        name, len(commits), "" if len(commits) == 1 else "s", branch, head[:9]))
    for sha, subject, issue, merge in commits:
        print("  {} {} ({})".format(sha[:9], subject, "brings main in" if merge else issue))
    if absent:
        print("Nothing on the pile for {}: already on main, or not landed yet.".format(" ".join(absent)))
    if check_only:
        if behind:
            print("Main holds work {} does not; a go first brings main into {} with one merge.".format(branch, branch))
        print("Checked only; nothing started.")
        return 0

    r = subprocess.run(["gh", "workflow", "run", STARTER, "--ref", branch,
                        "-f", "pile=" + name, "-f", "issues=" + " ".join(carried), "-f", "sha=" + head],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Stop("GitHub did not start the batch run: {}\nGitHub starts a workflow by hand only when its file is "
                   "also on the default branch, so the starter must be on main, as well as on landing, before the "
                   "first go. If main lacks {}, put it there once, as setup's step 5 says, then say go again."
                   .format((r.stderr or r.stdout).strip(), project_fact.STARTER_FILE))
    print("Started one batch run on {} at {} for {}. Main moves to {} only when it is green.".format(
        branch, head[:9], name, head[:9]))
    print("Watch it: gh run list --workflow {} --event workflow_dispatch --branch {} --limit 1".format(STARTER, branch))
    return 0


def main(argv):
    try:
        return go(argv)
    except Stop as stop:
        print(str(stop), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
