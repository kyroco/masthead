#!/usr/bin/env python3
"""Find the change that turned a batch red and say whose it is (INFRA-269, INFRA-288).

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
  run's failed jobs and names nothing.
- Otherwise it finds the first commit of the batch after which the Gate is red,
  then tests that commit alone on main. Red alone: it is the bad change. Green
  alone: it fails only together with earlier commits of the batch, and the
  search names each of them. Either way that commit, the latest-landed of those
  that fail, is the one named (Robert, November 19, 2026: "(and we send back the
  latest one)").
- It names the change, its issue and the failed check, and pushes nothing to
  landing or main: the change stays on the pile and its worker fixes it on top
  (Robert, November 19, 2026: "so why are you asking me?", INFRA-288). It prints
  the record and the worker's message as one block, which the foreman posts on
  the issue as a comment and sends to the worker.
- When none of its own Gate runs goes red, the red did not happen again: it
  names nothing and says so.
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

# The record's field names, one per line of the block the foreman posts on the issue.
T_BAD = "Masthead-Bad-Change"
T_ISSUE = "Masthead-Issue"
T_CHECK = "Masthead-Failed-Check"
T_WITH = "Masthead-Fails-With"
T_RUN = "Masthead-Red-Run"
T_BATCH = "Masthead-Batch"
NO_ISSUE = "none found"
BLOCK_START = "--- post on {issue} as a comment, word for word, and send it whole to its worker ---"
BLOCK_END = "--- end ---"

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
    """The search ends here and says why. Nothing is named."""


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
        raise Stop("Run {} stopped in its plan, before the Gate ran, so no change is to blame. "
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
        raise Stop("In run {} the Gate passed and the move of main failed, so no change is to blame and "
                   "nothing is named. Read the move's message in the run.".format(run_id))
    raise Stop("Run {} is not red: its Gate did not fail. Nothing is named.".format(run_id))


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


# The search's own memory of the changes it named, in the foreman's checkout: each change, its
# issue, and the batch it was last named in. A fix on top is a commit naming that issue that
# landed after that batch; the change's own other commits, and a fix already judged, are not.
NAMED_FILE = "named-changes.tsv"


def named_path(root):
    return os.path.join(project_fact.state_path(root), NAMED_FILE)


def named(root):
    """{commit: (issue, batch it was last named in, [commits it fails together with])} for every
    change this checkout's searches named."""
    found = {}
    try:
        with open(named_path(root)) as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and re.fullmatch(r"[0-9a-f]{40}", parts[0]) and \
                        re.fullmatch(r"[0-9a-f]{40}", parts[2]):
                    partners = [p for p in (parts[3].split(",") if len(parts) > 3 else [])
                                if re.fullmatch(r"[0-9a-f]{40}", p)]
                    found[parts[0]] = (parts[1], parts[2], partners)
    except OSError:
        pass
    return found


def remember(root, sha, issue, batch, partners):
    """Remember a named change with an issue, and the commits it fails together with, so a fix
    on top that is still red is handed back with them. One with no issue goes to the person,
    and is not held: nothing can be told apart as its fix."""
    if issue == NO_ISSUE:
        return
    path = named_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as handle:
        handle.write("{}\t{}\t{}\t{}\n".format(sha, issue, batch, ",".join(partners)))


def is_ancestor(a, b):
    return git("merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def new_fixes(commits, sha, known, root):
    """The commits after named change `sha` that name its issue and landed after the batch it was
    last named in: its fixes on top since then, oldest first."""
    issue, seen = known[sha][0], known[sha][1]
    return [c for c in commits[commits.index(sha) + 1:]
            if issue_of(c, root) == issue and not (rev(seen) and is_ancestor(c, seen))]


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
    """The search over a batch's commits, oldest first. Landing is linear, so main with the first
    k of them is the k-th commit itself; the Gate runs on that commit directly."""

    def __init__(self, root, gate_workflow, main, commits, red_run, batch, linear=True):
        """`linear`: `commits` are landing's own history after `main`, so the first k of them are
        the k-th commit itself, and all of them are the red batch. Otherwise every set is built on
        main with cherry-picks, and nothing is known red until a run says so."""
        self.root = root
        self.workflow = os.path.basename(gate_workflow)
        self.verdicts = verdict_names(root, gate_workflow)
        self.main = main
        self.commits = commits
        self.linear = linear
        self.batch = batch
        self.red_run = red_run
        self.cache = {(): ("green", None)}
        if linear:
            self.cache[tuple(commits)] = ("red", red_run)
        self.runs = 0
        self.saw_red = False
        self.count = 0

    def test(self, chosen):
        """"red", "green" or "no-apply" for main with `chosen` on it, and the run that said so."""
        key = tuple(chosen)
        if key in self.cache:
            return self.cache[key]
        if self.linear and list(key) == self.commits[:len(key)]:
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
                               "cannot tell if it is red. Nothing is named.".format(
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
        raise Stop("GitHub did not show the Gate run started on {}, so the search stops. Nothing is named.".format(
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
        """The bad change, the earlier commits it fails with, and the run that showed it red."""
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


# ---- What the foreman posts and sends -----------------------------------------

def record(bad, partners, checks, run, batch, root):
    """The record's lines: what the change is, whose it is, and what failed."""
    lines = ["{}: {}".format(T_BAD, bad), "{}: {}".format(T_ISSUE, issue_of(bad, root))]
    lines += ["{}: {}".format(T_CHECK, name) for name in checks]
    lines += ["{}: {} {}".format(T_WITH, sha, issue_of(sha, root)) for sha in partners]
    lines += ["{}: {}".format(T_RUN, run.get("url") or run.get("databaseId")), "{}: {}".format(T_BATCH, batch)]
    return "\n".join(lines)


def hand_back(bad, partners, checks, run, batch, root, tried=None):
    """The message for the worker of the bad change's issue, with the record at its end. A returned
    worker is a fresh session with no memory, so it carries everything the record holds. `tried` is
    the fix on top it already landed, when the Gate is still red there."""
    issue = issue_of(bad, root)
    lines = ["Your commit {} ({}) for {} turned the batch ending at {} red in {}.".format(
        bad, subject(bad), issue, batch[:9], run.get("url") or run.get("databaseId"))]
    if tried:
        lines.append("Your fix on top, {} ({}), is on landing, and the Gate is still red there: the change "
                     "is not fixed yet.".format(tried, subject(tried)))
    lines.append("Failed check: {}.".format(", ".join(checks) if checks else "not named by the run"))
    if partners:
        named = ", ".join("{} ({})".format(sha[:9], issue_of(sha, root)) for sha in partners)
        keys = [k for k in (issue_of(sha, root) for sha in partners) if k != NO_ISSUE]
        lines.append(
            "It passes on its own and fails only together with {}, which landed earlier. It is your job to "
            "figure out what needs to be fixed and fix it, end to end, whichever commit the fault sits in; "
            "it is not someone else's commit to hand on. Before you change anything, read {} and every "
            "comment on {}, which say what was done there, so your fix is not out of context. Once your fix "
            "lands, add a comment to {} and to {} saying what you changed and why, so the issues stay in "
            "sync.".format(named, " and ".join(keys) or "the issue of each of those commits",
                           "them" if len(keys) != 1 else "it", issue,
                           " and to ".join(keys) or "the issue of each of those commits"))
    else:
        lines.append("It fails that check on its own, on main.")
    lines.append(
        "Nothing was taken off landing: your commit stays on the pile, and main does not move until a later "
        "go runs green. Fix it on top: start from the newest `origin/landing`, commit the fix naming {}, prove "
        "it as /work-on says for {}, and land it on landing like any other commit.".format(issue, issue))
    lines.append(record(bad, partners, checks, run, batch, root))
    return "\n\n".join(lines)


# ---- The command --------------------------------------------------------------

def main(argv):
    if len(argv) != 1 or not argv[0].isdigit():
        say("Usage: bad-commit.py <id of the red batch run on landing>")
        return 2
    run_id = argv[0]
    try:
        root = project_fact.repo_root(None, os.getcwd())
    except project_fact.RepoUnclear as unclear:
        say(str(unclear))
        return 2
    # git and gh act on the folder they run in, so run them in the repository.
    os.chdir(root)
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
        raise Stop("The search needs git 2.40 or newer (git merge-tree --merge-base). Nothing is named.")
    stored = project_fact.gate(root)
    if not stored:
        raise Stop("No Gate is stored in .claude/gate.json, so the search does not start and names nothing. "
                   "Run /masthead:setup to store one.")
    if "workflow_dispatch" not in stored["starts"]:
        raise Stop("The stored Gate, {}, cannot be started with workflow_dispatch, which is how the search "
                   "tests one commit. The search does not start and names nothing.".format(stored["workflow"]))
    run = view(run_id)
    if run.get("status") != "completed":
        raise Stop("Run {} has not ended yet. Run the search once it is red.".format(run_id))
    if run.get("headBranch") != LANDING:
        raise Stop("Run {} is on {}, not landing, so it is not a batch run. Nothing is named.".format(
            run_id, run.get("headBranch")))
    if batch_verdict(run, run_id, verdict_names(root, stored["workflow"])) == "start":
        gh("run", "rerun", str(run_id), "--failed")
        say("Run {} went red only because a runner could not start or fetch the code. Its failed jobs run again; "
            "no change is named.".format(run_id))
        return 0

    git("fetch", "--quiet", "--no-tags", REMOTE,
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(MAIN, REMOTE),
        "+refs/heads/{0}:refs/remotes/{1}/{0}".format(LANDING, REMOTE))
    batch = run.get("headSha") or ""
    main_sha = rev("refs/remotes/{}/{}".format(REMOTE, MAIN))
    if not rev(batch) or git("merge-base", "--is-ancestor", main_sha, batch, check=False).returncode != 0:
        raise Stop("Batch {} does not sit on main, so the search cannot tell which commits are new. "
                   "Nothing is named.".format(batch[:9]))
    commits = git("rev-list", "--reverse", "--first-parent", "{}..{}".format(main_sha, batch)).stdout.split()
    if not commits:
        raise Stop("Batch {} holds no commit main does not, so nothing is named.".format(batch[:9]))
    # Main does not move past a red batch, so a batch can hold a change already named. With no fix
    # on top yet, it is the red the foreman already handed back: search nothing, send nothing again.
    known = {c: v for c, v in named(root).items() if c in commits}
    waiting = [c for c in known if not new_fixes(commits, c, known, root)]
    if waiting:
        say("Batch {} holds {}, already named and handed back, with no fix on top landed since. It is red for "
            "that reason; no Gate run is started and nothing is named again. Search the batch that holds the "
            "fix if it goes red.".format(
                batch[:9], ", ".join("{} ({})".format(c[:9], known[c][0]) for c in waiting)))
        return 0
    say("Batch {} holds {} commits after main {}. Searching with the stored Gate, {}.".format(
        batch[:9], len(commits), main_sha[:9], stored["workflow"]))

    # Each change named before has a fix on top landed since. Test each fix with only its own
    # issue's commits on what landed before the change, so no other commit's break is blamed on
    # it. Still red: the change is named again. Green: its commits are left out of the search.
    probe = Search(root, stored["workflow"], main_sha, commits, run, batch)
    left_out, tried, bad = [], None, None
    for sha in [c for c in commits if c in known]:
        issue = known[sha][0]
        last_fix = new_fixes(commits, sha, known, root)[-1]
        own = [c for c in commits[commits.index(sha):commits.index(last_fix) + 1] if issue_of(c, root) == issue]
        before = [c for c in commits[:commits.index(sha)] if c not in left_out]
        verdict, fix_run = probe.test(before + own)
        if verdict == "no-apply":
            raise Stop("The fix on top of {} ({}) does not apply without other commits of the batch, so the "
                       "search cannot tell if it works. Nothing is named; tell the person.".format(sha[:9], issue))
        if verdict == "red":
            # The commits it failed together with when first named still go with it.
            bad, evidence, tried = sha, fix_run, last_fix
            partners = [p for p in known[sha][2] if p in commits]
            break
        say("  {} ({}) is fixed on top by {}: left out of the search".format(sha[:9], issue, last_fix[:9]))
        left_out += own

    if bad is None:
        rest = [c for c in commits if c not in left_out]
        finder = Search(root, stored["workflow"], main_sha, rest, run, batch, linear=not left_out)
        if left_out:
            verdict, whole = finder.test(rest)
            if verdict != "red":
                raise Stop("With the fixed changes left out, the rest of batch {} is {} on main, so the red comes "
                           "only from them together with the rest. Nothing is named; tell the person.".format(
                               batch[:9], "green" if verdict == "green" else "not testable alone"))
        bad, partners, evidence = finder.find()
        if len(rest) > 1 and not finder.saw_red:
            # Every run the search started was green, so the only red is the batch run itself. Run the
            # Gate once more on the batch: a red that does not come back blames no change.
            verdict, again = finder.run_gate(batch, tuple(rest))
            if verdict != "red":
                raise Stop("None of the search's {} Gate runs went red, the batch itself included, so the red of "
                           "run {} did not happen again. No change is named.".format(
                               probe.runs + finder.runs, run_id))
            if evidence is run:
                evidence = again
        verdicts = finder.verdicts
        runs = probe.runs + finder.runs
    else:
        verdicts = probe.verdicts
        runs = probe.runs
    jobs = evidence.get("jobs") or []
    checks = failed_checks([j for j in jobs if part_of(j) == "gate"] if evidence is run else jobs, verdicts)

    issue = issue_of(bad, root)
    remember(root, bad, issue, batch, partners)
    say("")
    say("Named {} ({}) as the change that turned batch {} red, after {} Gate runs. Nothing was pushed to landing "
        "or main: the change stays on the pile, and its worker fixes it on top.".format(
            bad[:9], issue, batch[:9], runs))
    say("")
    if issue == NO_ISSUE:
        say("{} names no issue: tell the person, with this record.".format(bad[:9]))
        say("")
        say(record(bad, partners, checks, evidence, batch, root))
        return 0
    say(BLOCK_START.format(issue=issue))
    say(hand_back(bad, partners, checks, evidence, batch, root, tried))
    say(BLOCK_END)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
