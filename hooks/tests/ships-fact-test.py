#!/usr/bin/env python3
"""Linear issue INFRA-276: a repository that has not opted in to the batch run keeps the pull request way.

`project_fact.py --ships` is the one fact a session reads to tell which way a
change reaches main. It prints `batch` only when the batch run's two committed
files, the stored Gate (.claude/gate.json) and the starter file
(.github/workflows/masthead-batch.yml), are both on `origin/landing`, as plain
files, with the Gate naming a workflow that is there too. Anything else prints
`pull-request`: the way Masthead 0.3.1 ships. Robert, November 19, 2026: "yes
that's the right recommendation, keep the old way, new way is an option".

Scenario 1: a repository with no batch setup ships the pull request way.
Scenario 2: a repository that opted in ships the batch way.
Scenario 4: a repository part way through opting in ships the way its committed
facts on `origin/landing` say, which is the pull request way until both files
are there.

Run from anywhere: python3 hooks/tests/ships-fact-test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
FACT = os.path.join(PLUGIN, "hooks", "project_fact.py")

passed = 0
failed = 0

GATE_JSON = json.dumps({"workflow": ".github/workflows/gate.yml", "starts": ["workflow_call", "workflow_dispatch"]})
GATE_YML = "name: Gate\non:\n  workflow_call:\n  workflow_dispatch:\njobs: {}\n"
STARTER = "name: Masthead batch\non:\n  push:\n    branches: [landing]\njobs: {}\n"


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
    if r.returncode != 0:
        raise SystemExit("git {} failed: {}".format(" ".join(args), r.stderr))
    return r.stdout


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def repo(landing=None, on_main=None):
    """A clone of a fresh origin. `landing` and `on_main` map paths to text
    (None for no such branch); a value "->target" commits a symlink."""
    base = os.path.realpath(tempfile.mkdtemp(prefix="ships-fact-"))
    origin, work = os.path.join(base, "origin"), os.path.join(base, "work")
    git(base, "init", "-q", "--bare", "-b", "main", origin)
    git(base, "clone", "-q", origin, work)
    write(work, "README.md", "hi\n")
    for rel, text in (on_main or {}).items():
        write(work, rel, text)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "main")
    git(work, "push", "-q", "origin", "HEAD:main")
    if landing is not None:
        git(work, "switch", "-q", "-c", "landing")
        for rel, text in landing.items():
            if text.startswith("->"):
                path = os.path.join(work, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.symlink(text[2:], path)
            else:
                write(work, rel, text)
        git(work, "add", "-A")
        git(work, "commit", "-q", "--allow-empty", "-m", "landing")
        git(work, "push", "-q", "origin", "HEAD:landing")
        git(work, "switch", "-q", "main")
        git(work, "branch", "-q", "-D", "landing")
    git(work, "fetch", "-q", "origin")
    return base, work


def ships(cwd, project="same"):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project == "same":
        env["CLAUDE_PROJECT_DIR"] = cwd
    elif project:
        env["CLAUDE_PROJECT_DIR"] = project
    r = subprocess.run([sys.executable, FACT, "--ships"], capture_output=True, text=True, cwd=cwd, env=env)
    return r.returncode, r.stdout.strip()


OPTED_IN = {".claude/gate.json": GATE_JSON, ".github/workflows/gate.yml": GATE_YML,
            ".github/workflows/masthead-batch.yml": STARTER}
made = []

# Scenario 1: no batch setup at all, no landing branch: the pull request way.
base, work = repo()
made.append(base)
expect("s1 no landing branch", ships(work), (0, "pull-request"))
# Scenario 1: a landing branch with nothing of the batch run on it (a hand run, as
# kyroco/masthead had on November 19, 2026) is still the pull request way.
base, work = repo(landing={"notes.txt": "hand run\n"})
made.append(base)
expect("s1 landing without batch files", ships(work), (0, "pull-request"))

# Scenario 2: both files on origin/landing, the Gate's workflow there too: the batch way.
base, work = repo(landing=OPTED_IN)
made.append(base)
expect("s2 opted in", ships(work), (0, "batch"))
# From a folder inside the checkout, and from no CLAUDE_PROJECT_DIR (the Bash tool sets none).
os.makedirs(os.path.join(work, "deep", "er"))
expect("s2 from a subfolder", ships(os.path.join(work, "deep", "er")), (0, "batch"))
expect("s2 with no project dir set", ships(work, project=None), (0, "batch"))
# From a worktree of the same repository: refs are shared, so the answer is the same.
tree = os.path.join(base, "tree")
git(work, "worktree", "add", "-q", "-b", "side", tree)
expect("s2 from a worktree", ships(tree), (0, "batch"))
# Another repository's session does not read this one's facts.
other_base, other = repo()
made.append(other_base)
expect("s2 untrusted root", ships(work, project=other), (0, "pull-request"))

# Scenario 4: part way through opting in.
# The Gate stored and committed, no starter (setup asked about the Gate, the batch run was declined or not yet asked).
base, work = repo(landing={k: v for k, v in OPTED_IN.items() if not k.endswith("masthead-batch.yml")})
made.append(base)
expect("s4 gate only", ships(work), (0, "pull-request"))
# The starter on landing but no stored Gate: the batch run could not start the Gate.
base, work = repo(landing={k: v for k, v in OPTED_IN.items() if k != ".claude/gate.json"})
made.append(base)
expect("s4 starter only", ships(work), (0, "pull-request"))
# Both written in the checkout, and even on main, but not yet landed on landing (setup step 4 not done).
base, work = repo(on_main=OPTED_IN)
made.append(base)
for rel, text in OPTED_IN.items():
    write(work, rel, text)
expect("s4 written and on main, not on landing", ships(work), (0, "pull-request"))
base, work = repo(landing={}, on_main=OPTED_IN)
made.append(base)
expect("s2 landing made from a main that holds both", ships(work), (0, "batch"))
# Both landed on origin's landing, but this checkout has not fetched since: it reads what it has.
base, work = repo(landing={"notes.txt": "x\n"})
made.append(base)
other_clone = os.path.join(base, "second")
git(base, "clone", "-q", os.path.join(base, "origin"), other_clone)
git(other_clone, "switch", "-q", "landing")
for rel, text in OPTED_IN.items():
    write(other_clone, rel, text)
git(other_clone, "add", "-A")
git(other_clone, "commit", "-q", "-m", "opt in")
git(other_clone, "push", "-q", "origin", "HEAD:landing")
expect("s4 before a fetch, the last fetched landing decides", ships(work), (0, "pull-request"))
git(work, "fetch", "-q", "origin")
expect("s4 after a fetch", ships(work), (0, "batch"))
# A stored Gate that names a workflow not on landing is no Gate.
base, work = repo(landing={k: v for k, v in OPTED_IN.items() if not k.endswith("gate.yml")})
made.append(base)
expect("s4 gate names a missing workflow", ships(work), (0, "pull-request"))
# A stored Gate that is not valid JSON, or names no way to start it.
broken = dict(OPTED_IN)
broken[".claude/gate.json"] = "{not json"
base, work = repo(landing=broken)
made.append(base)
expect("s4 gate not JSON", ships(work), (0, "pull-request"))
broken[".claude/gate.json"] = json.dumps({"workflow": ".github/workflows/gate.yml", "starts": ["push"]})
base, work = repo(landing=broken)
made.append(base)
expect("s4 gate with no way to start it", ships(work), (0, "pull-request"))
# A symlink committed in place of either file is not that file.
linked = dict(OPTED_IN)
linked[".github/workflows/masthead-batch.yml"] = "->gate.yml"
base, work = repo(landing=linked)
made.append(base)
expect("s4 starter is a symlink", ships(work), (0, "pull-request"))
linked = dict(OPTED_IN)
linked[".claude/gate.json"] = "->../README.md"
base, work = repo(landing=linked)
made.append(base)
expect("s4 gate is a symlink", ships(work), (0, "pull-request"))

# Round 1, arch-2: the Gate's workflow is checked by the same rule gate() uses, a plain
# file at any size. A Gate workflow between 64 KiB and 1 MiB, which setup stores and
# locks main to, is still the batch way.
big = dict(OPTED_IN)
big[".github/workflows/gate.yml"] = GATE_YML + "# padding\n" * 10000  # about 100 KiB
base, work = repo(landing=big)
made.append(base)
expect("arch-2 a Gate workflow over 64 KiB", ships(work), (0, "batch"))
big[".github/workflows/gate.yml"] = GATE_YML + "# padding\n" * 90000  # about 900 KiB
base, work = repo(landing=big)
made.append(base)
expect("arch-2 a Gate workflow near 1 MiB", ships(work), (0, "batch"))

# MAST-54: a cloud thread clones shallow and single-branch (`git clone --depth 1`), so origin/landing
# was never fetched. A ref this checkout never fetched says nothing about the remote: --ships fetches
# landing by name, then decides.
def cloned(base, name, *flags):
    path = os.path.join(base, name)
    git(base, "clone", "-q", *flags, "file://" + os.path.join(base, "origin"), path)
    return path


def is_shallow(path):
    return git(path, "rev-parse", "--is-shallow-repository").strip()


# Scenario 1: a shallow single-branch clone of a repository that opted in ships the batch way.
base, _ = repo(landing=OPTED_IN)
made.append(base)
shallow = cloned(base, "shallow", "--depth", "1")
expect("mast-54 s1 shallow clone has no origin/landing yet",
       subprocess.run(["git", "-C", shallow, "rev-parse", "-q", "--verify", "refs/remotes/origin/landing"],
                      capture_output=True).returncode, 1)
expect("mast-54 s1 shallow clone of an opted-in repository", ships(shallow), (0, "batch"))
expect("mast-54 s1 asked again", ships(shallow), (0, "batch"))
# Scenario 2: no landing branch on the remote: the pull request way, as before.
base, _ = repo()
made.append(base)
shallow = cloned(base, "shallow", "--depth", "1")
expect("mast-54 s2 shallow clone, no landing on the remote", ships(shallow), (0, "pull-request"))
# A landing with nothing of the batch run on it is still the pull request way.
base, _ = repo(landing={"notes.txt": "hand run\n"})
made.append(base)
shallow = cloned(base, "shallow", "--depth", "1")
expect("mast-54 s2 shallow clone, landing without batch files", ships(shallow), (0, "pull-request"))
# Scenario 3: a full clone answers as before, from landing as last fetched: no fetch is made for it.
# Round 1 fix (verifier s3): a full single-branch clone that never fetched landing still answers the
# pull request way, as it did before MAST-54, and is left untouched.
base, _ = repo(landing=OPTED_IN)
made.append(base)
full = cloned(base, "full")
expect("mast-54 s3 full clone", ships(full), (0, "batch"))
single = cloned(base, "single", "--single-branch", "--no-tags")
expect("mast-54 s3 full single-branch clone answers as before", ships(single), (0, "pull-request"))
expect("mast-54 s3 full single-branch clone fetched nothing",
       subprocess.run(["git", "-C", single, "rev-parse", "-q", "--verify", "refs/remotes/origin/landing"],
                      capture_output=True).returncode, 1)
expect("mast-54 s3 full single-branch clone stays full", is_shallow(single), "false")

# Outside a git repository, with none in the workspace: which repository is unclear, so the skill stops and
# prints nothing (MAST-48, repo_root step 4).
plain = os.path.realpath(tempfile.mkdtemp(prefix="ships-plain-"))
made.append(plain)
expect("outside a repository", ships(plain), (2, ""))

for path in made:
    shutil.rmtree(path, ignore_errors=True)
print("ships fact: {} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
