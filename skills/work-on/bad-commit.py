#!/usr/bin/env python3
"""Find the commit that turned a batch red, drop it from landing, and say whose it is (INFRA-269).

The foreman runs this by hand, from a checkout of the repository, when a batch
run on `landing` goes red:

    python3 ${CLAUDE_PLUGIN_ROOT}/skills/work-on/bad-commit.py <red run id>

It reads the Gate Masthead's setup stored (.claude/gate.json, read with
project_fact.gate) and never works the Gate out: with none stored it stops and
says so. It runs that Gate on GitHub, one throwaway `masthead-search/...` branch
per commit set it tests, with `gh workflow run`, so the stored Gate must list
workflow_dispatch among its starts.

What it does with a red batch (references/bad-commit.md has the whole of it):

- Red only because a runner could not fetch the code or start: it reruns the
  run's failed jobs and drops nothing.
- Otherwise it finds the first commit of the batch after which the Gate is red,
  then tests that commit alone on main. Red alone: it is the bad commit. Green
  alone: it fails only together with earlier commits of the batch, and the
  search names each of them. Either way that commit, the latest-landed of those
  that fail, is dropped (Robert, November 19, 2026: "(and we send back the
  latest one)").
- It drops the commit with a revert pushed to landing as a plain push, never a
  force push, so workers landing at the same moment lose nothing. That push
  starts the next batch run, which tests the rest again. The revert's message
  carries the record as git trailers (Masthead-Dropped and the rest), where the
  foreman reads it: git log origin/landing --grep='^Masthead-Dropped:'.
- When none of its own Gate runs goes red, the red did not happen again: it
  drops nothing and says so.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "hooks"))
import project_fact  # noqa: E402

LANDING = "landing"
MAIN = "main"
REMOTE = "origin"
SEARCH_PREFIX = "masthead-search/"

# The record's trailer names. INFRA-263 parses them: change them only together with it.
T_DROPPED = "Masthead-Dropped"
T_ISSUE = "Masthead-Issue"
T_CHECK = "Masthead-Failed-Check"
T_WITH = "Masthead-Fails-With"
T_BUILDS_ON = "Masthead-Builds-On"
T_RUN = "Masthead-Red-Run"
T_BATCH = "Masthead-Batch"
T_BRING_BACK = "Masthead-Bring-Back"
BRING_BACK = "revert-this-commit-and-fix-in-one-push"
NO_ISSUE = "none found"

# A failed step with one of these names, or a job with no steps, means the runner
# never got as far as a check: it could not start, or could not fetch the code.
START_STEPS = re.compile(
    r"^(set up job|set up runner|initialize containers|complete runner|"
    r"run actions/checkout@.*|checkout( code| the code| repository)?|check out( the)?( code| repository)?)$",
    re.IGNORECASE)
RED = ("failure", "timed_out", "startup_failure")
POLL = float(os.environ.get("MASTHEAD_SEARCH_POLL_SECONDS", "30"))
FIND_RUN_TRIES = int(os.environ.get("MASTHEAD_SEARCH_FIND_TRIES", "40"))
START_RERUNS = 2


class Stop(Exception):
    """The search ends here and says why. Nothing is dropped."""


def say(line=""):
    print(line, flush=True)


def git(*args, check=True, cwd=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    if check and r.returncode != 0:
        raise Stop("git {} failed: {}".format(" ".join(args[:2]), (r.stderr or r.stdout).strip()))
    return r


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise Stop("gh {} failed: {}".format(" ".join(args[:2]), (r.stderr or r.stdout).strip()))
    return r.stdout


def gh_json(*args):
    try:
        return json.loads(gh(*args) or "null")
    except ValueError:
        raise Stop("gh {} did not answer with JSON.".format(" ".join(args[:2])))


# ---- Reading a Gate run -------------------------------------------------------

RUN_FIELDS = "databaseId,status,conclusion,headSha,headBranch,url,attempt,jobs"


def view(run_id):
    return gh_json("run", "view", str(run_id), "--json", RUN_FIELDS)


def wait(run_id, attempt=None):
    """The run once it has completed (and, when `attempt` is given, that attempt or a later one)."""
    while True:
        run = view(run_id)
        if run.get("status") == "completed" and (attempt is None or (run.get("attempt") or 1) >= attempt):
            return run
        time.sleep(POLL)


def failed_jobs(jobs):
    return [j for j in jobs if j.get("conclusion") in RED]


def failed_step(job):
    for step in job.get("steps") or []:
        if step.get("conclusion") in RED:
            return step.get("name") or ""
    return ""


def could_not_start(job):
    """The job failed before any check ran: no steps, or its first failed step is setting up or fetching code."""
    if job.get("conclusion") == "startup_failure" or not job.get("steps"):
        return True
    return bool(START_STEPS.match(failed_step(job).strip()))


# Not !cancelled(): Gates use it to run a check when an earlier job was skipped (Kyroco's Static
# job does), and such a job's failure is its own.
VERDICT_IF = re.compile(r"\b(always|failure)\(\s*\)")


def verdict_names(root, workflow):
    """The names of the stored Gate's verdict jobs, read from its own workflow file: a job that
    needs others and runs even when they failed (its `if:` holds always() or failure()), as
    Kyroco's `gate` job does. Such a job fails because others failed, so it says nothing of its own."""
    text = project_fact.read_repo_file(project_fact.checkout_top(root), workflow) or ""
    jobs, current, in_jobs, in_if = [], None, False, False
    for line in text.replace("\r", "").splitlines():
        if re.match(r"^jobs:\s*(#.*)?$", line):
            in_jobs = True
            continue
        if re.match(r"^\S", line):
            in_jobs = False
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)
        if m:
            current = {"id": m.group(1), "name": None, "if": "", "needs": False}
            jobs.append(current)
            in_if = False
            continue
        if current is None:
            continue
        m = re.match(r"^    (name|if|needs):\s*(.*)$", line)
        if m:
            key, value = m.groups()
            in_if = key == "if"
            if key == "name":
                current["name"] = value.split(" #")[0].strip().strip("'\"")
            elif key == "if":
                current["if"] += value
            else:
                current["needs"] = True
            continue
        if re.match(r"^    \S", line):
            in_if = False
        elif in_if and re.match(r"^      ", line):
            current["if"] += line
    return {j["name"] or j["id"] for j in jobs if j["needs"] and VERDICT_IF.search(j["if"])}


def is_verdict(job, verdicts):
    """One of the Gate's verdict jobs, as the batch run ("gate / <name>") or the Gate itself names it.
    A job that failed while starting is never one: its runner failed, whatever the job is."""
    if could_not_start(job):
        return False
    name = job.get("name", "")
    return name in verdicts or (name.startswith("gate / ") and name[len("gate / "):] in verdicts)


def own_failures(jobs, verdicts):
    """The failed jobs that say something of their own: verdict jobs left out."""
    return [j for j in failed_jobs(jobs) if not is_verdict(j, verdicts)]


def judge(jobs, verdicts):
    """One Gate's jobs: "green", "start" (red only because a runner could not start or fetch
    the code), or "red"."""
    if not failed_jobs(jobs):
        return "green"
    failures = own_failures(jobs, verdicts)
    if failures and all(could_not_start(j) for j in failures):
        return "start"
    return "red"


def classify(run, verdicts):
    """A Gate run the search started, judged as judge() says. One that ended without
    passing and with no failed job (cancelled) counts as a run to start again."""
    if run.get("conclusion") == "success":
        return "green"
    if run.get("conclusion") == "startup_failure":
        return "start"
    verdict = judge(run.get("jobs") or [], verdicts)
    return "start" if verdict == "green" else verdict


def part_of(job):
    """Which part of the batch run a job is: "plan", "move", or "gate" (the starter's Gate job)."""
    first = job.get("name", "").split(" / ")[0]
    return first if first in ("plan", "move") else "gate"


def batch_verdict(run, run_id, verdicts):
    """The red batch run judged part by part: the plan, then the Gate, then the move of main.
    Only the Gate's jobs say whether the batch's code is red; a plan or move job whose runner
    could not start or fetch the code makes the batch one to run again."""
    parts = {"plan": [], "gate": [], "move": []}
    for job in run.get("jobs") or []:
        parts[part_of(job)].append(job)
    plan_failed = failed_jobs(parts["plan"])
    if plan_failed:
        if all(could_not_start(j) for j in plan_failed):
            return "start"
        raise Stop("Run {} stopped in its plan, before the Gate ran, so no commit is to blame. "
                   "Read the plan's message in the run.".format(run_id))
    if run.get("conclusion") == "startup_failure":
        return "start"
    verdict = judge(parts["gate"], verdicts)
    if verdict != "green":
        return verdict
    move_failed = failed_jobs(parts["move"])
    if move_failed and all(could_not_start(j) for j in move_failed):
        return "start"
    if move_failed:
        raise Stop("In run {} the Gate passed and the move of main failed, so no commit is to blame and "
                   "nothing is dropped. Read the move's message in the run.".format(run_id))
    raise Stop("Run {} is not red: its Gate did not fail. Nothing is dropped.".format(run_id))


def failed_checks(jobs, verdicts):
    """The names of the checks that failed in a red run, without verdict jobs and runner failures."""
    names = [j.get("name", "") for j in own_failures(jobs, verdicts) if not could_not_start(j)]
    return names or [j.get("name", "") for j in failed_jobs(jobs)]


# ---- The commits of a batch ---------------------------------------------------

def rev(ref):
    return git("rev-parse", "--verify", "--quiet", ref + "^{commit}").stdout.strip()


def message(sha):
    return git("log", "-1", "--format=%B", sha).stdout


def subject(sha):
    return git("log", "-1", "--format=%s", sha).stdout.strip()


def issue_of(sha, root):
    """The issue a commit belongs to, from its message: the Linear key or GitHub number it names.

    A "Fixes KEY" or "refs KEY" line names the issue outright; then the subject, then the rest.
    Within a line the last key wins: a subject names its own issue at the end, "(INFRA-422)",
    and may name another one earlier ("Undo part of INFRA-421 ...")."""
    lines = message(sha).splitlines()
    ordered = [l for l in lines if re.match(r"\s*(fixes|closes|resolves|refs)\b", l, re.I)] + lines
    if project_fact.tracker(root) == "linear":
        team = project_fact.linear_team(root)
        pattern = re.compile(r"\b{}-\d+\b".format(re.escape(team)) if team else r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
    else:
        pattern = re.compile(r"(?<![\w/])#\d+\b")
    for line in ordered:
        found = pattern.findall(line)
        if found:
            return found[-1]
    return NO_ISSUE


DROPPED_LINE = re.compile(r"^{}: ([0-9a-f]{{40}})\s*$".format(T_DROPPED), re.MULTILINE)


def drops(base, tip):
    """{dropped commit: the revert that took it off landing}, for every record between base and tip."""
    out = git("log", "--format=%H%x1f%B%x1e", "--grep=^{}:".format(T_DROPPED), "{}..{}".format(base, tip)).stdout
    found = {}
    for entry in out.split("\x1e"):
        if "\x1f" not in entry:
            continue
        revert, body = entry.split("\x1f", 1)
        for m in DROPPED_LINE.finditer(body):
            found.setdefault(m.group(1), revert.strip())
    return found


def apply_on(base, commits):
    """A commit holding `commits` cherry-picked onto `base` in order, or None when one does not apply cleanly."""
    head = base
    for sha in commits:
        parents = git("rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
        if len(parents) != 1:
            return None
        r = git("merge-tree", "--write-tree", "--merge-base=" + parents[0], head, sha, check=False)
        if r.returncode != 0:
            return None
        tree = r.stdout.split()[0]
        head = git("commit-tree", tree, "-p", head, "-m", "Masthead search: " + subject(sha)).stdout.strip()
    return head


# ---- Running the stored Gate on one commit set -------------------------------

class Search:
    """The search over a batch's live commits: those not already dropped. `clean` holds the live
    commits whose own tree is main with exactly the live commits up to them, because every
    dropped commit before them has its revert before them too; the Gate runs on those directly."""

    def __init__(self, root, gate_workflow, main, commits, red_run, batch, clean):
        self.root = root
        self.workflow = os.path.basename(gate_workflow)
        self.verdicts = verdict_names(root, gate_workflow)
        self.main = main
        self.commits = commits
        self.batch = batch
        self.clean = clean
        self.red_run = red_run
        self.cache = {(): ("green", None)}
        self.cache[tuple(commits)] = ("red", red_run)
        self.runs = 0
        self.saw_red = False
        self.count = 0

    def test(self, chosen):
        """"red", "green" or "no-apply" for main with `chosen` on it, and the run that said so."""
        key = tuple(chosen)
        if key in self.cache:
            return self.cache[key]
        if list(key) == self.commits[:len(key)] and key[-1] in self.clean:
            sha = key[-1]
        else:
            sha = apply_on(self.main, key)
            if sha is None:
                self.cache[key] = ("no-apply", None)
                say("  {}: does not apply on main without more of the batch; no Gate run".format(self.label(key)))
                return self.cache[key]
        result = self.run_gate(sha, key)
        self.cache[key] = result
        return result

    def label(self, key):
        return " + ".join(c[:9] for c in key)

    def run_gate(self, sha, key):
        self.count += 1
        branch = "{}{}-{}".format(SEARCH_PREFIX, self.batch[:12], self.count)
        git("push", "--quiet", REMOTE, "{}:refs/heads/{}".format(sha, branch))
        try:
            gh("workflow", "run", self.workflow, "--ref", branch)
            self.runs += 1
            run_id = self.find_run(branch, sha)
            run = wait(run_id)
            reruns = 0
            while classify(run, self.verdicts) == "start":
                if reruns >= START_RERUNS:
                    raise Stop("The Gate run {} on {} could not start or fetch the code {} times, so the search "
                               "cannot tell if it is red. Nothing is dropped.".format(
                                   run.get("url", run_id), self.label(key), reruns + 1))
                reruns += 1
                attempt = (run.get("attempt") or 1) + 1
                say("  {}: a runner could not start or fetch the code; running the failed jobs again".format(
                    self.label(key)))
                gh("run", "rerun", str(run_id), "--failed")
                self.runs += 1
                run = wait(run_id, attempt)
            verdict = classify(run, self.verdicts)
            if verdict == "red":
                self.saw_red = True
            say("  {}: {} ({})".format(self.label(key), verdict, run.get("url", run_id)))
            return verdict, run
        finally:
            git("push", "--quiet", REMOTE, "--delete", branch, check=False)

    def find_run(self, branch, sha):
        for _ in range(FIND_RUN_TRIES):
            runs = gh_json("run", "list", "--workflow", self.workflow, "--branch", branch,
                           "--event", "workflow_dispatch", "--json", "databaseId,headSha", "--limit", "5") or []
            for run in runs:
                if run.get("headSha") == sha:
                    return run["databaseId"]
            time.sleep(POLL)
        raise Stop("GitHub did not show the Gate run started on {}, so the search stops. Nothing is dropped.".format(
            branch))

    # The search itself.

    def first_red_prefix(self):
        """The smallest k with main + the batch's first k commits red; the whole batch is known red."""
        lo, hi = 1, len(self.commits)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.test(self.commits[:mid])[0] == "red":
                hi = mid
            else:
                lo = mid + 1
        return hi

    def find(self):
        """The commit to drop, the earlier commits it fails with, and the run that showed it red."""
        k = self.first_red_prefix()
        evidence = self.test(self.commits[:k])[1]
        fixed = [self.commits[k - 1]]
        pool = self.commits[:k - 1]
        # Invariant: main + pool + fixed is red, and `evidence` is the run that showed it.
        while pool:
            verdict, run = self.test(fixed)
            if verdict == "red":
                evidence = run
                break
            lo, hi = 1, len(pool)
            while lo < hi:
                mid = (lo + hi) // 2
                if self.test(pool[:mid] + fixed)[0] == "red":
                    hi = mid
                else:
                    lo = mid + 1
            evidence = self.test(pool[:hi] + fixed)[1]
            fixed = [pool[hi - 1]] + fixed
            pool = pool[:hi - 1]
        return fixed[-1], fixed[:-1], evidence


# ---- Dropping the commit ------------------------------------------------------

def trailer_block(dropped, partners, checks, run, batch, root, builds_on=None):
    lines = ["{}: {}".format(T_DROPPED, dropped), "{}: {}".format(T_ISSUE, issue_of(dropped, root))]
    lines += ["{}: {}".format(T_CHECK, name) for name in checks]
    lines += ["{}: {} {}".format(T_WITH, sha, issue_of(sha, root)) for sha in partners]
    if builds_on:
        lines += ["{}: {} {}".format(T_BUILDS_ON, builds_on, issue_of(builds_on, root))]
    lines += ["{}: {}".format(T_RUN, run.get("url") or run.get("databaseId")),
              "{}: {}".format(T_BATCH, batch), "{}: {}".format(T_BRING_BACK, BRING_BACK)]
    return "\n".join(lines)


def revert_message(dropped, partners, checks, run, batch, root):
    why = "it fails the Gate alone on main" if not partners else \
        "it fails the Gate together with {}, and it landed last".format(
            ", ".join("{} ({})".format(p[:9], issue_of(p, root)) for p in partners))
    body = [
        "Drop {} from landing: it turned batch {} red".format(dropped[:9], batch[:9]),
        "",
        "Dropped: {} ({}). The Masthead search found that {}. Failed: {}.".format(
            subject(dropped), issue_of(dropped, root), why, ", ".join(checks)),
        "",
        "To bring it back, its worker reverts this commit and commits the fix on top,",
        "and pushes both to landing at once, so no batch holds the change without its fix.",
        "",
        trailer_block(dropped, partners, checks, run, batch, root),
    ]
    return "\n".join(body) + "\n"


def builds_on_message(later, dropped, run, batch, root):
    body = [
        "Drop {} from landing: it builds on {}, which turned batch {} red".format(later[:9], dropped[:9], batch[:9]),
        "",
        "Dropped with {} ({}): {} ({}) changes the same lines, so {} could not come off landing".format(
            dropped[:9], issue_of(dropped, root), subject(later), issue_of(later, root), dropped[:9]),
        "without it. It failed no check of its own.",
        "",
        "To bring it back, its worker waits until {} is back with its fix, then reverts this".format(dropped[:9]),
        "commit, fixes what no longer fits, and pushes both to landing at once.",
        "",
        trailer_block(later, [], [], run, batch, root, builds_on=dropped),
    ]
    return "\n".join(body) + "\n"


def touched(sha):
    return set(git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split())


def revert_tree(head, sha):
    """The tree of `head` with `sha`'s change taken off, or None when that does not apply cleanly."""
    parents = git("rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
    if len(parents) != 1:
        return None
    r = git("merge-tree", "--write-tree", "--merge-base=" + sha, head, parents[0], check=False)
    return r.stdout.split()[0] if r.returncode == 0 else None


def take_off(main, dropped, tip):
    """The commits to take off landing, newest first, ending with `dropped`: alone when its revert
    applies on `tip`, else with each later commit that changes a file it or one of those changes.
    Records, and commits already dropped, are never taken off. None when even that does not apply."""
    if revert_tree(tip, dropped):
        return [dropped]
    done = drops(main, tip)
    skip = set(done) | set(done.values())
    paths, builds = touched(dropped), []
    for sha in git("rev-list", "--reverse", "--first-parent", "{}..{}".format(dropped, tip)).stdout.split():
        if sha in skip:
            continue
        files = touched(sha)
        if files & paths:
            builds.append(sha)
            paths |= files
    order = list(reversed(builds)) + [dropped]
    head = tip
    for sha in order:
        tree = revert_tree(head, sha)
        if not tree:
            return None
        head = git("commit-tree", tree, "-p", head, "-m", "check").stdout.strip()
    return order


def drop(main, dropped, message_for, tries=5):
    """Take `dropped` off the newest landing, with the later commits that build on its lines, one
    revert each, in one plain push. The commits taken off, newest first, and landing's new tip; or
    None when landing already took `dropped` off."""
    for _ in range(tries):
        git("fetch", "--quiet", "--no-tags", REMOTE, "+refs/heads/{0}:refs/remotes/{1}/{0}".format(LANDING, REMOTE))
        tip = rev("refs/remotes/{}/{}".format(REMOTE, LANDING))
        if not tip:
            raise Stop("This repository has no landing branch, so nothing is dropped.")
        if dropped in drops(main, tip):
            return None
        order = take_off(main, dropped, tip)
        if not order:
            raise Stop("{} cannot be taken off landing cleanly, even with the later commits that change the same "
                       "files. Nothing is dropped; hand it back by hand.".format(dropped[:9]))
        head = tip
        for sha in order:
            made = subprocess.run(["git", "commit-tree", revert_tree(head, sha), "-p", head, "-F", "-"],
                                  input=message_for(sha), capture_output=True, text=True)
            if made.returncode != 0:
                raise Stop("git commit-tree failed: " + made.stderr.strip())
            head = made.stdout.strip()
        if git("push", "--quiet", REMOTE, "{}:refs/heads/{}".format(head, LANDING), check=False).returncode == 0:
            return order, head
        say("  landing moved while the revert was made; trying again on the newest landing")
    raise Stop("landing kept moving, so the revert could not be pushed after {} tries. Nothing is dropped.".format(tries))


# ---- The command --------------------------------------------------------------

def main(argv):
    if len(argv) != 1 or not argv[0].isdigit():
        say("Usage: bad-commit.py <id of the red batch run on landing>")
        return 2
    run_id = argv[0]
    root = project_fact.checkout_top(os.getcwd())
    os.environ.setdefault("CLAUDE_PROJECT_DIR", root)
    try:
        return search(run_id, root)
    except Stop as stop:
        say(str(stop))
        return 1


def git_new_enough():
    """git 2.40 or newer, for merge-tree --write-tree --merge-base (2.40 added --merge-base); an older
    git would make every commit set look as if it does not apply."""
    m = re.search(r"(\d+)\.(\d+)", git("--version").stdout)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (2, 40)


def search(run_id, root):
    if not git_new_enough():
        raise Stop("The search needs git 2.40 or newer (git merge-tree --merge-base). Nothing is dropped.")
    stored = project_fact.gate(root)
    if not stored:
        raise Stop("No Gate is stored in .claude/gate.json, so the search does not start and drops nothing. "
                   "Run /masthead:setup to store one.")
    if "workflow_dispatch" not in stored["starts"]:
        raise Stop("The stored Gate, {}, cannot be started with workflow_dispatch, which is how the search "
                   "tests one commit. The search does not start and drops nothing.".format(stored["workflow"]))
    run = view(run_id)
    if run.get("status") != "completed":
        raise Stop("Run {} has not ended yet. Run the search once it is red.".format(run_id))
    if run.get("headBranch") != LANDING:
        raise Stop("Run {} is on {}, not landing, so it is not a batch run. Nothing is dropped.".format(
            run_id, run.get("headBranch")))
    if batch_verdict(run, run_id, verdict_names(root, stored["workflow"])) == "start":
        gh("run", "rerun", str(run_id), "--failed")
        say("Run {} went red only because a runner could not start or fetch the code. Its failed jobs run again; "
            "no commit is dropped.".format(run_id))
        return 0

    git("fetch", "--quiet", "--no-tags", REMOTE,
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(MAIN, REMOTE),
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(LANDING, REMOTE))
    batch = run.get("headSha") or ""
    main_sha = rev("refs/remotes/{}/{}".format(REMOTE, MAIN))
    if not rev(batch) or git("merge-base", "--is-ancestor", main_sha, batch, check=False).returncode != 0:
        raise Stop("Batch {} does not sit on main, so the search cannot tell which commits are new. "
                   "Nothing is dropped.".format(batch[:9]))
    history = git("rev-list", "--reverse", "--first-parent", "{}..{}".format(main_sha, batch)).stdout.split()
    if not history:
        raise Stop("Batch {} holds no commit main does not, so nothing is dropped.".format(batch[:9]))
    in_batch = set(history)
    # Main does not move past a drop, so a batch can hold commits already dropped. A revert made
    # after this run started means landing has moved on: the batch run after it is the one to search.
    done = drops(main_sha, rev("refs/remotes/{}/{}".format(REMOTE, LANDING)))
    later = {d: r for d, r in done.items() if d in in_batch and r not in in_batch}
    if later:
        say("Batch {} holds {}, which revert {} already took off landing after this run started. The batch run "
            "on that revert tests the rest; search that run if it goes red. Nothing more is dropped.".format(
                batch[:9], ", ".join(d[:9] for d in later), ", ".join(r[:9] for r in later.values())))
        return 0
    pairs = {d: r for d, r in done.items() if d in in_batch and r in in_batch}
    commits, clean, open_drops = [], set(), set()
    reverted_by = {r: d for d, r in pairs.items()}
    for sha in history:
        if sha in pairs:
            open_drops.add(sha)
        elif sha in reverted_by:
            open_drops.discard(reverted_by[sha])
        else:
            commits.append(sha)
            if not open_drops:
                clean.add(sha)
    if not commits:
        raise Stop("Every commit of batch {} was already dropped, so nothing more is dropped.".format(batch[:9]))
    say("Batch {} holds {} commits after main {}{}. Searching with the stored Gate, {}.".format(
        batch[:9], len(commits), main_sha[:9],
        ", leaving out {} already dropped".format(len(pairs)) if pairs else "", stored["workflow"]))

    finder = Search(root, stored["workflow"], main_sha, commits, run, batch, clean)
    dropped, partners, evidence = finder.find()
    if len(commits) > 1 and not finder.saw_red:
        # Every run the search started was green, so the only red is the batch run itself. Run the
        # Gate once more on the batch: a red that does not come back blames no commit.
        verdict, again = finder.run_gate(batch, tuple(commits))
        if verdict != "red":
            raise Stop("None of the search's {} Gate runs went red, the batch itself included, so the red of "
                       "run {} did not happen again. No commit is dropped.".format(finder.runs, run_id))
        if evidence is run:
            evidence = again
    jobs = evidence.get("jobs") or []
    checks = failed_checks([j for j in jobs if part_of(j) == "gate"] if evidence is run else jobs, finder.verdicts)

    def message_for(sha):
        if sha == dropped:
            return revert_message(dropped, partners, checks, evidence, batch, root)
        return builds_on_message(sha, dropped, evidence, batch, root)

    result = drop(main_sha, dropped, message_for)
    if result is None:
        say("{} is already off landing: a revert pushed while the search ran took it off. "
            "Nothing more is dropped.".format(dropped[:9]))
        return 0
    order, tip = result
    say("")
    with_it = order[:-1]
    say("Dropped {} from landing{}, after {} Gate runs; landing is now {}. That push starts the next batch run, "
        "which tests the rest again.".format(
            dropped[:9], " with {}, which build on its lines".format(", ".join(c[:9] for c in with_it))
            if with_it else "", finder.runs, tip[:9]))
    say("")
    say(trailer_block(dropped, partners, checks, evidence, batch, root))
    for sha in with_it:
        say("")
        say(trailer_block(sha, [], [], evidence, batch, root, builds_on=dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
