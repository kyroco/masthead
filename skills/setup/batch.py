#!/usr/bin/env python3
"""Put Masthead's batch run into a repository and lock its main to it (INFRA-272).

Run by /masthead:setup, each part only after the person's yes:

    batch.py write        write the starter file, .github/workflows/masthead-batch.yml
    batch.py landing      make the landing branch from main, when it is missing
    batch.py environment  make the masthead-batch environment, open to `landing` only
    batch.py lock --app-id N   lock main: only the batch App may update, force-push or delete it;
                               refused until landing holds the starter and the environment both secrets
    batch.py check [--app-id N]   say, as JSON, which parts are in place and whether to offer the batch run; changes nothing
    batch.py steps        print the click-by-click GitHub App steps, from the README

Every command takes [--root DIR] (the repository's checkout) and
[--repo OWNER/NAME] (else `gh repo view` names it).

The App key lives as two secrets of the masthead-batch environment. GitHub
hands an environment's secrets only to a job that names the environment, and
the environment lets only `landing` use it, so the move job of the batch run
is the one workflow that can read the key: not the repository's own Gate, not
a workflow on any other branch (scenario 5, SEC-270-2). A person stores the
two secrets; no session may (`gh secret set` is refused by Masthead's gates).

The batch run itself lives in kyroco/masthead (references/batch-run.md).
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate  # noqa: E402
import project_fact  # noqa: E402  (gate.py puts hooks/ on the path)

PLUGIN = os.path.dirname(os.path.dirname(HERE))
README = os.path.join(PLUGIN, "README.md")
STARTER_PATH = ".github/workflows/masthead-batch.yml"
ENVIRONMENT = "masthead-batch"
LANDING = "landing"
MAIN = "refs/heads/main"
RULESET = "Masthead batch: only the batch run moves main"
SECRETS = ("BATCH_APP_ID", "BATCH_APP_PRIVATE_KEY")
KEY = "BATCH_APP_PRIVATE_KEY"
STEPS_HEADING = "### Set up the batch run's GitHub App"


class GitHubError(Exception):
    pass


def gh_api(*args, body=None):
    """One `gh api` call: its parsed answer, or GitHubError with what gh said."""
    cmd = ["gh", "api", *args]
    if body is not None:
        cmd += ["--input", "-"]
    try:
        proc = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                              capture_output=True, text=True)
    except OSError as error:
        raise GitHubError("gh could not run: {}".format(error))
    if proc.returncode != 0:
        raise GitHubError((proc.stderr or proc.stdout).strip() or "gh exited {}".format(proc.returncode))
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def not_found(error):
    return "HTTP 404" in str(error)


def repository(top, given):
    if given:
        name = given
    else:
        proc = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                              cwd=top, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitHubError("gh could not tell which GitHub repository this is: " + proc.stderr.strip())
        name = proc.stdout.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
        raise GitHubError("'{}' is not an OWNER/NAME repository.".format(name))
    return name


# ---- the starter file ------------------------------------------------------

def unsafe(top, rel):
    """Why `rel` cannot be written safely in `top`, or None: no link anywhere on the way (SEC-1)."""
    path = top
    parts = rel.split("/")
    for i, part in enumerate(parts):
        path = os.path.join(path, part)
        last = i == len(parts) - 1
        if os.path.islink(path):
            return "{} is a link, so nothing was written through it.".format("/".join(parts[:i + 1]))
        if os.path.lexists(path) and (os.path.isdir(path) if last else not os.path.isdir(path)):
            return "{} is not a plain {}, so nothing was written.".format(
                "/".join(parts[:i + 1]), "file" if last else "folder")
    return None


def write(top):
    text, error = gate.starter(top)
    if error:
        return None, error
    why = unsafe(top, STARTER_PATH)
    if why:
        return None, why
    os.makedirs(os.path.join(top, os.path.dirname(STARTER_PATH)), exist_ok=True)
    path = os.path.join(top, STARTER_PATH)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except OSError as error:
        return None, "{} could not be written: {}".format(STARTER_PATH, error)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return STARTER_PATH, None


# ---- GitHub: landing, the environment, the lock ------------------------------

def landing(repo):
    try:
        gh_api("repos/{}/git/ref/heads/{}".format(repo, LANDING))
        return "The landing branch is already there; it was left where it is."
    except GitHubError as error:
        if not not_found(error):
            raise
    main = gh_api("repos/{}/git/ref/heads/main".format(repo))
    sha = main["object"]["sha"]
    gh_api("-X", "POST", "repos/{}/git/refs".format(repo), body={"ref": "refs/heads/" + LANDING, "sha": sha})
    return "Made the landing branch at main's commit {}.".format(sha[:12])


def policies(repo):
    found = gh_api("repos/{}/environments/{}/deployment-branch-policies?per_page=100".format(repo, ENVIRONMENT))
    return (found or {}).get("branch_policies", [])


def is_landing_rule(policy):
    return policy.get("name") == LANDING and policy.get("type", "branch") == "branch"


def environment(repo):
    gh_api("-X", "PUT", "repos/{}/environments/{}".format(repo, ENVIRONMENT),
           body={"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}})
    have = False
    for policy in policies(repo):
        if is_landing_rule(policy) and not have:
            have = True
            continue
        # Any other rule lets another branch or a tag read the App key.
        gh_api("-X", "DELETE", "repos/{}/environments/{}/deployment-branch-policies/{}".format(
            repo, ENVIRONMENT, policy["id"]))
    if not have:
        gh_api("-X", "POST", "repos/{}/environments/{}/deployment-branch-policies".format(repo, ENVIRONMENT),
               body={"name": LANDING, "type": "branch"})
    return "The {} environment is open to the landing branch only.".format(ENVIRONMENT)


def app_bypass(app_id):
    return [{"actor_id": int(app_id), "actor_type": "Integration", "bypass_mode": "always"}]


def ruleset_body(app_id):
    return {
        "name": RULESET,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": [MAIN], "exclude": []}},
        "rules": [{"type": "update"}, {"type": "non_fast_forward"}, {"type": "deletion"}],
        "bypass_actors": app_bypass(app_id),
    }


def own_ruleset(repo):
    listed = gh_api("repos/{}/rulesets?includes_parents=false&per_page=100".format(repo)) or []
    mine = [r for r in listed if r.get("name") == RULESET]
    return mine[0] if mine else None


def landed_starter(repo):
    """The starter file as the landing branch holds it on GitHub, or None when it holds none."""
    import base64
    try:
        found = gh_api("repos/{}/contents/{}?ref={}".format(repo, STARTER_PATH, LANDING))
    except GitHubError as error:
        if not_found(error):
            return None
        raise
    return base64.b64decode(found.get("content", "")).decode("utf-8", "replace")


def environment_secrets(repo):
    listed = gh_api("repos/{}/environments/{}/secrets?per_page=100".format(repo, ENVIRONMENT))
    return {s.get("name") for s in (listed or {}).get("secrets", [])}


def lock_refusal(top, repo):
    """Why main must not be locked yet, or None. A lock with nothing able to move main would freeze it (F2)."""
    want, error = gate.starter(top)
    if error:
        return error
    have = landed_starter(repo)
    if have is None:
        return ("The landing branch on GitHub does not hold {} yet. Commit it with .claude/gate.json and land it on "
                "landing first; locking main before that would leave nothing able to move it.").format(STARTER_PATH)
    if have != want:
        return ("The starter file on the landing branch differs from what setup writes for the stored Gate. Run "
                "batch.py write, land the file, then lock main.")
    try:
        names = environment_secrets(repo)
    except GitHubError as error:
        if not not_found(error):
            raise
        names = set()
    gone = [s for s in SECRETS if s not in names]
    if gone:
        return ("The {} environment lacks {}, so the batch run could not move main. The person stores them first "
                "(batch.py steps gives the commands).").format(ENVIRONMENT, " and ".join(gone))
    return None


def lock(repo, app_id):
    mine = own_ruleset(repo)
    if mine:
        gh_api("-X", "PUT", "repos/{}/rulesets/{}".format(repo, mine["id"]), body=ruleset_body(app_id))
        return "Updated the ruleset on main: only the batch App ({}) may move it.".format(app_id)
    gh_api("-X", "POST", "repos/{}/rulesets".format(repo), body=ruleset_body(app_id))
    return "Locked main: only the batch App ({}) may move it.".format(app_id)


# ---- check: what is in place, read only -------------------------------------

def guards_main(ruleset):
    names = (ruleset.get("conditions") or {}).get("ref_name") or {}
    include = names.get("include") or []
    exclude = names.get("exclude") or []
    hits = {MAIN, "~DEFAULT_BRANCH", "~ALL", "main", "refs/heads/*", "refs/heads/**", "*", "**"}
    return bool(set(include) & hits) and not set(exclude) & {MAIN, "~DEFAULT_BRANCH", "main"}


def lets_app_through(ruleset, app_id):
    for actor in ruleset.get("bypass_actors") or []:
        if actor.get("actor_type") == "Integration" and actor.get("bypass_mode") == "always" and \
                (app_id is None or str(actor.get("actor_id")) == str(app_id)):
            return True
    return False


def check(top, repo, app_id):
    found = []

    def part(name, ok, say):
        found.append({"part": name, "ok": bool(ok), "say": say})

    want, error = gate.starter(top)
    have = project_fact.read_repo_file(top, STARTER_PATH, limit=1024 * 1024)
    if error:
        part("starter file", False, error)
    elif have is None:
        part("starter file", False, "{} is not there. Run batch.py write, then commit it.".format(STARTER_PATH))
    elif have != want:
        part("starter file", False, "{} differs from what setup writes for the stored Gate. Run batch.py write again.".format(
            STARTER_PATH))
    else:
        part("starter file", True, "{} runs the stored Gate.".format(STARTER_PATH))

    def ask(name, call, missing_say):
        try:
            return call()
        except GitHubError as e:
            part(name, False, missing_say if not_found(e) else "GitHub did not answer: {}".format(e))
            return None

    if ask("landing branch", lambda: gh_api("repos/{}/git/ref/heads/{}".format(repo, LANDING)),
           "There is no landing branch. Run batch.py landing.") is not None:
        part("landing branch", True, "The landing branch is there.")

    env = ask("environment", lambda: gh_api("repos/{}/environments/{}".format(repo, ENVIRONMENT)),
              "There is no {} environment. Run batch.py environment.".format(ENVIRONMENT))
    rules = []
    if env is not None:
        policy = env.get("deployment_branch_policy") or {}
        rules = ask("environment", lambda: policies(repo), "") if policy.get("custom_branch_policies") else []
        if rules is not None:
            only = policy.get("custom_branch_policies") and not policy.get("protected_branches") and \
                len(rules) == 1 and is_landing_rule(rules[0])
            part("environment", only, "Only the landing branch may use the {} environment.".format(ENVIRONMENT) if only
                 else "Branches other than landing may use the {} environment, so they could read the App key. "
                      "Run batch.py environment.".format(ENVIRONMENT))

    if env is None:
        part("key in the environment", False, "There is no {} environment to hold the App's secrets.".format(ENVIRONMENT))
    else:
        listed = ask("key in the environment",
                     lambda: gh_api("repos/{}/environments/{}/secrets?per_page=100".format(repo, ENVIRONMENT)), "")
        if listed is not None:
            names = {s.get("name") for s in listed.get("secrets", [])}
            gone = [s for s in SECRETS if s not in names]
            part("key in the environment", not gone,
                 "The {} environment holds {}.".format(ENVIRONMENT, " and ".join(SECRETS)) if not gone else
                 "The {} environment lacks {}. The person stores them; batch.py steps gives the commands.".format(
                     ENVIRONMENT, " and ".join(gone)))

    repo_names = ask("key nowhere else", lambda: gh_api("repos/{}/actions/secrets?per_page=100".format(repo)), "")
    org_names = ask("key nowhere else",
                    lambda: gh_api("repos/{}/actions/organization-secrets?per_page=100".format(repo)), "")
    if repo_names is not None and org_names is not None:
        where = []
        if KEY in {s.get("name") for s in repo_names.get("secrets", [])}:
            where.append("a repository secret")
        if KEY in {s.get("name") for s in org_names.get("secrets", [])}:
            where.append("an organization secret this repository can read")
        part("key nowhere else", not where,
             "The App key is in the environment only." if not where else
             "{} is also {}, so every workflow on every branch, the Gate too, can read it and move main. "
             "Delete it there, or stop sharing it with this repository.".format(KEY, " and ".join(where)))

    listed = ask("lock", lambda: gh_api("repos/{}/rulesets?includes_parents=true&per_page=100".format(repo)), "")
    if listed is not None:
        mine, others = None, []
        for summary in listed:
            if summary.get("target") not in (None, "branch") or summary.get("enforcement") != "active":
                if summary.get("name") != RULESET:
                    continue
            detail = ask("lock", lambda: gh_api("repos/{}/rulesets/{}".format(repo, summary["id"])), "")
            if detail is None:
                continue
            if detail.get("name") == RULESET and detail.get("source_type", "Repository") == "Repository":
                mine = detail
            elif guards_main(detail) and not lets_app_through(detail, app_id):
                others.append(detail.get("name", str(detail.get("id"))))
        if mine is None:
            part("lock", False, "Main is not locked to the batch run. Run batch.py lock --app-id N.")
        else:
            types = sorted(r.get("type") for r in mine.get("rules", []))
            actors = mine.get("bypass_actors") or []
            ok = mine.get("enforcement") == "active" and guards_main(mine) and \
                {"update", "non_fast_forward", "deletion"} <= set(types) and \
                len(actors) == 1 and lets_app_through(mine, app_id)
            part("lock", ok, "Main is locked: only the batch App may move it." if ok else
                 "The ruleset on main is not as setup makes it (active, on main, no update, force push or delete, "
                 "the batch App{} its only bypass). Run batch.py lock --app-id N.".format(
                     " " + str(app_id) if app_id else ""))
        try:
            gh_api("repos/{}/branches/main/protection".format(repo))
            others.append("classic branch protection")
        except GitHubError as e:
            if not not_found(e):
                others.append("classic branch protection (GitHub would not say: {})".format(e))
        part("other rules on main", not others,
             "Nothing else on main stops the batch App." if not others else
             "Also on main, and not letting the batch App through: {}. Main will not move until each lets the "
             "App through or stops guarding main.".format(", ".join(others)))
    return found


def offer(top, repo, found):
    """Whether setup should ask the batch run question here, and why not (F1, F4)."""
    _, error = gate.starter(top)
    if error:
        return False, error
    try:
        owner = (gh_api("repos/{}".format(repo)) or {}).get("owner", {}).get("type")
    except GitHubError as e:
        return False, "GitHub would not say who owns {}: {}".format(repo, e)
    if owner != "Organization":
        return False, ("The batch run's GitHub App steps are for a repository an organization owns, and {} is on a "
                       "personal account, so it keeps shipping the way it does today.").format(repo)
    if all(p["ok"] for p in found):
        return False, "The batch run is already in place here."
    return True, ""


def steps(repo):
    text = open(README, encoding="utf-8").read()
    start = text.find("\n" + STEPS_HEADING + "\n")
    if start < 0:
        return None
    body = text[start + 1:]
    end = re.search(r"\n#{1,3} ", body[len(STEPS_HEADING):])
    body = body[:len(STEPS_HEADING) + end.start() + 1] if end else body
    return body.replace("OWNER/REPO", repo) if repo else body


# ---- the command line --------------------------------------------------------

def option(argv, name):
    if name not in argv:
        return argv, None
    i = argv.index(name)
    if i + 1 >= len(argv):
        raise SystemExit("{} needs a value".format(name))
    return argv[:i] + argv[i + 2:], argv[i + 1]


def main(argv):
    argv, root = option(argv, "--root")
    argv, given = option(argv, "--repo")
    argv, app_id = option(argv, "--app-id")
    top = project_fact.checkout_top(root or os.getcwd())
    os.environ["CLAUDE_PROJECT_DIR"] = top
    if app_id is not None and not re.fullmatch(r"[1-9][0-9]{0,11}", app_id):
        print("The App id is the number GitHub shows as App ID on the App's page, such as 5832645; '{}' is not one.".format(
            app_id), file=sys.stderr)
        return 2
    if argv == ["write"]:
        path, error = write(top)
        if error:
            print(error, file=sys.stderr)
            return 1
        print("Wrote {}. Commit it with .claude/gate.json; it runs once it is on the landing branch.".format(path))
        return 0
    if argv == ["steps"]:
        try:
            repo = repository(top, given)
        except GitHubError:
            repo = None
        text = steps(repo)
        if text is None:
            print("The README has no '{}' section.".format(STEPS_HEADING), file=sys.stderr)
            return 1
        sys.stdout.write(text)
        return 0
    if argv not in (["landing"], ["environment"], ["lock"], ["check"]):
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: batch.py write | landing | environment | lock --app-id N | check [--app-id N] | steps"
              "  [--root DIR] [--repo OWNER/NAME]", file=sys.stderr)
        return 2
    if argv == ["lock"] and app_id is None:
        print("lock needs --app-id, the number GitHub shows as App ID on the batch App's page.", file=sys.stderr)
        return 2
    try:
        repo = repository(top, given)
        if argv == ["check"]:
            found = check(top, repo, app_id)
            ready = all(p["ok"] for p in found)
            ask, why = offer(top, repo, found)
            print(json.dumps({"repo": repo, "ready": ready, "offer": ask, "why": why, "parts": found}, indent=2))
            return 0 if ready else 1
        if argv == ["lock"]:
            why = lock_refusal(top, repo)
            if why:
                print("Main was not locked. " + why, file=sys.stderr)
                return 1
        print({"landing": lambda: landing(repo), "environment": lambda: environment(repo),
               "lock": lambda: lock(repo, app_id)}[argv[0]]())
        return 0
    except GitHubError as error:
        print("GitHub refused or could not be reached, so this step is not done: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
