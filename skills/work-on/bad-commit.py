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


def failed_jobs(run):
    return [j for j in run.get("jobs") or [] if j.get("conclusion") in RED]


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


def is_verdict(job, jobs):
    """A job that started only after every other job ended, such as a Gate's own
    verdict job: it fails because others failed, so it says nothing of its own."""
    started = job.get("startedAt") or ""
    others = [j.get("completedAt") or "" for j in jobs if j is not job and j.get("conclusion") != "skipped"]
    return bool(started) and bool(others) and all(c and c <= started for c in others)


def own_failures(run, skip=()):
    """The failed jobs that say something: verdict jobs and the `skip` jobs left out."""
    jobs = [j for j in run.get("jobs") or [] if not j.get("name", "").split(" / ")[0] in skip]
    return [j for j in failed_jobs({"jobs": jobs}) if not is_verdict(j, jobs)]


def classify(run, skip=()):
    """"green", "start" (red only because a runner could not start or fetch the code), or "red"."""
    if run.get("conclusion") == "success":
        return "green"
    if run.get("conclusion") == "startup_failure":
        return "start"
    failures = own_failures(run, skip)
    if failures and all(could_not_start(j) for j in failures):
        return "start"
    if not failures and not failed_jobs(run):
        # Cancelled or skipped with no failed job: nothing says the code is red.
        return "start" if run.get("conclusion") in RED else "green"
    return "red"


def failed_checks(run, skip=()):
    """The names of the checks that failed in a red run, without verdict jobs and runner failures."""
    names = [j.get("name", "") for j in own_failures(run, skip) if not could_not_start(j)]
    return names or [j.get("name", "") for j in failed_jobs(run)]


# ---- The commits of a batch ---------------------------------------------------

def rev(ref):
    return git("rev-parse", "--verify", "--quiet", ref + "^{commit}").stdout.strip()


def message(sha):
    return git("log", "-1", "--format=%B", sha).stdout


def subject(sha):
    return git("log", "-1", "--format=%s", sha).stdout.strip()


def issue_of(sha, root):
    """The issue a commit belongs to, from its message: the Linear key or GitHub number it names."""
    text = message(sha)
    lines = text.splitlines()
    # A "Fixes KEY" or "refs KEY" line names the issue outright; then the subject, then the rest.
    ordered = [l for l in lines if re.match(r"\s*(fixes|closes|resolves|refs)\b", l, re.I)] + lines
    if project_fact.tracker(root) == "linear":
        team = project_fact.linear_team(root)
        pattern = re.compile(r"\b{}-\d+\b".format(re.escape(team)) if team else r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
        for line in ordered:
            m = pattern.search(line)
            if m:
                return m.group(0)
        return NO_ISSUE
    for line in ordered:
        m = re.search(r"(?<![\w/])#(\d+)\b", line)
        if m:
            return "#" + m.group(1)
    return NO_ISSUE


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
    def __init__(self, root, gate_workflow, main, commits, red_run):
        self.root = root
        self.workflow = os.path.basename(gate_workflow)
        self.main = main
        self.commits = commits
        self.batch = commits[-1]
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
        if list(key) == self.commits[:len(key)]:
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
            while classify(run) == "start":
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
            verdict = classify(run)
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

def trailer_block(dropped, partners, checks, run, batch, root):
    lines = ["{}: {}".format(T_DROPPED, dropped), "{}: {}".format(T_ISSUE, issue_of(dropped, root))]
    lines += ["{}: {}".format(T_CHECK, name) for name in checks]
    lines += ["{}: {} {}".format(T_WITH, sha, issue_of(sha, root)) for sha in partners]
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


def drop(dropped, text, tries=5):
    """Push a revert of `dropped` onto the newest landing, as a plain push. Its new sha."""
    for _ in range(tries):
        git("fetch", "--quiet", "--no-tags", REMOTE, "+refs/heads/{0}:refs/remotes/{1}/{0}".format(LANDING, REMOTE))
        tip = rev("refs/remotes/{}/{}".format(REMOTE, LANDING))
        if not tip:
            raise Stop("This repository has no landing branch, so nothing is dropped.")
        parent = git("rev-list", "--parents", "-n", "1", dropped).stdout.split()[1:]
        if len(parent) != 1:
            raise Stop("{} is a merge, and the search drops only plain commits. Nothing is dropped.".format(dropped[:9]))
        r = git("merge-tree", "--write-tree", "--merge-base=" + dropped, tip, parent[0], check=False)
        if r.returncode != 0:
            raise Stop("{} cannot be taken off landing cleanly: commits landed after it change the same lines. "
                       "Nothing is dropped; hand it back by hand.".format(dropped[:9]))
        tree = r.stdout.split()[0]
        made = subprocess.run(["git", "commit-tree", tree, "-p", tip, "-F", "-"], input=text,
                              capture_output=True, text=True)
        if made.returncode != 0:
            raise Stop("git commit-tree failed: " + made.stderr.strip())
        sha = made.stdout.strip()
        if git("push", "--quiet", REMOTE, "{}:refs/heads/{}".format(sha, LANDING), check=False).returncode == 0:
            return sha
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
    planned = [j for j in run.get("jobs") or [] if j.get("name", "").split(" / ")[0] == "plan"]
    if any(j.get("conclusion") in RED for j in planned):
        raise Stop("Run {} stopped in its plan, before the Gate ran, so no commit is to blame. "
                   "Read the plan's message in the run.".format(run_id))
    verdict = classify(run, skip=("plan", "move"))
    if verdict == "green":
        raise Stop("Run {} is not red: its Gate did not fail. Nothing is dropped.".format(run_id))
    if verdict == "start":
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
    commits = git("rev-list", "--reverse", "--first-parent", "{}..{}".format(main_sha, batch)).stdout.split()
    if not commits:
        raise Stop("Batch {} holds no commit main does not, so nothing is dropped.".format(batch[:9]))
    say("Batch {} holds {} commits after main {}. Searching with the stored Gate, {}.".format(
        batch[:9], len(commits), main_sha[:9], stored["workflow"]))

    finder = Search(root, stored["workflow"], main_sha, commits, run)
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
    skip = ("plan", "move") if evidence is run else ()
    checks = failed_checks(evidence, skip)
    text = revert_message(dropped, partners, checks, evidence, batch, root)
    revert = drop(dropped, text)
    say("")
    say("Dropped {} from landing with revert {}, after {} Gate runs. That push starts the next batch run, "
        "which tests the rest again.".format(dropped[:9], revert[:9], finder.runs))
    say("")
    say(trailer_block(dropped, partners, checks, evidence, batch, root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
