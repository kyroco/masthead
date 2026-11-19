#!/usr/bin/env python3
"""Linear issue INFRA-272: setup puts the batch run into a repository and locks main to it.

skills/setup/batch.py writes the starter file, makes the landing branch and the
masthead-batch environment, and locks main with a ruleset whose only bypass is
the batch App. Its GitHub calls go through `gh api`, which these tests replace
with hooks/tests/fake_gh.py, a stand-in keeping a pretend repository on GitHub.
That GitHub really refuses a push and runs the starter is proven on a scratch
repository, not here (the INFRA-272 record says which runs).

Scenario 1: after a yes, setup writes the small starter file.
Scenario 2: main is locked: only the batch App may update, force-push or delete it.
Scenario 3: the starter calls the batch workflows kept in kyroco/masthead.
Scenario 4: setup and the README give the click-by-click App steps.
Scenario 5: the App key lives in an environment only the move job names and
only `landing` may use, so no other workflow can read it.

Run from anywhere: python3 hooks/tests/batch-setup-test.py
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
BATCH = os.path.join(PLUGIN, "skills", "setup", "batch.py")
GATE_PY = os.path.join(PLUGIN, "skills", "setup", "gate.py")
MOVE = os.path.join(PLUGIN, ".github", "workflows", "batch-move.yml")
SKILL = os.path.join(PLUGIN, "skills", "setup", "SKILL.md")
README = os.path.join(PLUGIN, "README.md")
GATE = ".github/workflows/gate.yml"
STARTER_PATH = ".github/workflows/masthead-batch.yml"
REPO = "acme/site"
MAIN_SHA = "a" * 40
RULESET = "Masthead batch: only the batch run moves main"

passed = 0
failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL " + label + ("\n     " + str(detail) if detail else ""))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class GitHub:
    """A temp folder with a fake `gh` first on PATH and the pretend repository it keeps."""

    def __init__(self, top, **state):
        self.dir = os.path.join(top, "gh")
        os.makedirs(self.dir)
        self.state_path = os.path.join(self.dir, "state.json")
        self.log_path = os.path.join(self.dir, "log.jsonl")
        base = {"repo": REPO, "refs": {"main": MAIN_SHA}, "environments": {}, "rulesets": [],
                "repo_secrets": [], "org_secrets": []}
        base.update(state)
        self.save(base)
        open(self.log_path, "w").close()
        shim = os.path.join(self.dir, "gh")
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexec '{}' '{}' \"$@\"\n".format(sys.executable, os.path.join(HERE, "fake_gh.py")))
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC)

    def save(self, state):
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)

    def state(self):
        return json.loads(read(self.state_path))

    def calls(self):
        return [json.loads(l) for l in read(self.log_path).splitlines() if l.strip()]

    def writes(self):
        return [c for c in self.calls() if c.get("method") not in (None, "GET")]

    def env(self):
        env = dict(os.environ, PATH=self.dir + os.pathsep + os.environ.get("PATH", ""),
                   FAKE_GH_STATE=self.state_path, FAKE_GH_LOG=self.log_path)
        env.pop("CLAUDE_PROJECT_DIR", None)
        return env


def batch(gh, top, *args):
    return subprocess.run([sys.executable, BATCH, *args, "--root", top], capture_output=True, text=True, env=gh.env())


def repo_with_gate(top, gate_text="name: Gate\non: [pull_request, workflow_call]\njobs:\n  t:\n    runs-on: x\n    steps: []\n"):
    work = os.path.join(top, "work")
    os.makedirs(os.path.join(work, ".github", "workflows"))
    with open(os.path.join(work, GATE), "w", encoding="utf-8") as handle:
        handle.write(gate_text)
    os.makedirs(os.path.join(work, ".claude"))
    with open(os.path.join(work, ".claude", "gate.json"), "w", encoding="utf-8") as handle:
        json.dump({"workflow": GATE, "starts": ["workflow_call"]}, handle)
    return work


def starter_text(work):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([sys.executable, GATE_PY, "starter", "--root", work], capture_output=True, text=True, env=env).stdout


def parts(run):
    try:
        return {p["part"]: p for p in json.loads(run.stdout)["parts"]}
    except (ValueError, KeyError) as error:
        return {"error": {"ok": False, "say": "{}: {}".format(error, run.stdout + run.stderr)}}


# ---- Scenario 1: setup writes the small starter file -------------------------
with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    run = batch(gh, work, "write")
    path = os.path.join(work, STARTER_PATH)
    check("S1 write puts the starter file in .github/workflows", run.returncode == 0 and os.path.isfile(path),
          run.stdout + run.stderr)
    check("S1 the written starter is exactly what gate.py starter prints for the stored Gate",
          os.path.isfile(path) and read(path) == starter_text(work) and starter_text(work) != "")
    check("S1 write makes no GitHub call", gh.calls() == [], gh.calls())
    run = batch(gh, work, "write")
    check("S1 writing again leaves the same file", run.returncode == 0 and read(path) == starter_text(work))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("old\n")
    batch(gh, work, "write")
    check("S1 writing again replaces an old starter with the current one", read(path) == starter_text(work))

with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = os.path.join(top, "work")
    os.makedirs(work)
    run = batch(gh, work, "write")
    check("S1 with no Gate stored nothing is written, and setup is told why",
          run.returncode == 1 and not os.path.exists(os.path.join(work, ".github")) and "No Gate is stored" in run.stderr,
          run.stdout + run.stderr)

with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    elsewhere = os.path.join(top, "elsewhere.yml")
    with open(elsewhere, "w", encoding="utf-8") as handle:
        handle.write("theirs\n")
    os.symlink(elsewhere, os.path.join(work, STARTER_PATH))
    run = batch(gh, work, "write")
    check("S1 a starter path that is a link is refused and nothing is written through it",
          run.returncode == 1 and read(elsewhere) == "theirs\n", run.stdout + run.stderr)

# ---- Scenario 2: main is locked to the batch App ------------------------------
with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    run = batch(gh, work, "lock", "--app-id", "5832645")
    rulesets = gh.state()["rulesets"]
    mine = [r for r in rulesets if r["name"] == RULESET]
    check("S2 lock makes one ruleset", run.returncode == 0 and len(mine) == 1, run.stdout + run.stderr)
    if mine:
        r = mine[0]
        check("S2 the ruleset is active and guards main", r["enforcement"] == "active" and r["target"] == "branch"
              and r["conditions"]["ref_name"]["include"] == ["refs/heads/main"], r)
        check("S2 the ruleset refuses an update, a force push and a delete of main",
              sorted(rule["type"] for rule in r["rules"]) == ["deletion", "non_fast_forward", "update"], r["rules"])
        check("S2 its only bypass is the batch App, always",
              r["bypass_actors"] == [{"actor_id": 5832645, "actor_type": "Integration", "bypass_mode": "always"}],
              r["bypass_actors"])
    batch(gh, work, "lock", "--app-id", "5832645")
    check("S2 locking again updates the same ruleset, never adds a second",
          len([r for r in gh.state()["rulesets"] if r["name"] == RULESET]) == 1
          and gh.writes()[-1]["method"] == "PUT", gh.writes())
    for bad in ("", "12ab", "-1", "1; rm -rf /"):
        before = len(gh.calls())
        run = batch(gh, work, "lock", "--app-id", bad)
        check("S2 an App id that is not a number is refused before any GitHub call ({!r})".format(bad),
              run.returncode != 0 and len(gh.calls()) == before, run.stdout + run.stderr)
    run = batch(gh, work, "lock")
    check("S2 lock with no App id is refused", run.returncode != 0, run.stdout + run.stderr)

with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top, fail_all=True)
    work = repo_with_gate(top)
    run = batch(gh, work, "lock", "--app-id", "5832645")
    check("S2 when GitHub refuses, lock fails and says what GitHub said",
          run.returncode == 1 and "403" in run.stderr, run.stdout + run.stderr)

# Another ruleset or a classic protection on main would refuse the App's push too.
OTHER = {"id": 7, "name": "Merge queue", "target": "branch", "source_type": "Organization", "enforcement": "active",
         "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
         "rules": [{"type": "merge_queue"}], "bypass_actors": []}
with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top, rulesets=[OTHER], classic_protection=True)
    work = repo_with_gate(top)
    batch(gh, work, "lock", "--app-id", "5832645")
    p = parts(batch(gh, work, "check", "--app-id", "5832645"))
    check("S2 check says the lock is in place", p.get("lock", {}).get("ok") is True, p)
    check("S2 check names another active ruleset on main that does not let the App through",
          p.get("other rules on main", {}).get("ok") is False and "Merge queue" in p["other rules on main"]["say"], p)
    check("S2 check names classic branch protection on main",
          "branch protection" in p.get("other rules on main", {}).get("say", ""), p)
    state = gh.state()
    state["rulesets"][0]["bypass_actors"] = [{"actor_id": 5832645, "actor_type": "Integration", "bypass_mode": "always"}]
    state["rulesets"][0]["enforcement"] = "evaluate"
    state["classic_protection"] = False
    gh.save(state)
    p = parts(batch(gh, work, "check", "--app-id", "5832645"))
    check("S2 a ruleset that lets the App through is no obstacle", p.get("other rules on main", {}).get("ok") is True, p)

with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    state = gh.state()
    state["rulesets"] = [{"id": 9, "name": RULESET, "target": "branch", "source_type": "Repository",
                          "enforcement": "active", "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
                          "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "update"}],
                          "bypass_actors": [{"actor_id": 1, "actor_type": "RepositoryRole", "bypass_mode": "always"},
                                            {"actor_id": 5832645, "actor_type": "Integration", "bypass_mode": "always"}]}]
    gh.save(state)
    p = parts(batch(gh, work, "check", "--app-id", "5832645"))
    check("S2 check refuses a lock that lets anyone but the App through",
          p.get("lock", {}).get("ok") is False, p)
    p = parts(batch(gh, work, "check", "--app-id", "999"))
    check("S2 check refuses a lock whose bypass is another App", p.get("lock", {}).get("ok") is False, p)

# ---- Scenario 3: the starter calls the workflows kept in kyroco/masthead -----
with tempfile.TemporaryDirectory() as top:
    work = repo_with_gate(top)
    text = starter_text(work)
    check("S3 the starter runs on a push to landing", re.search(r"(?m)^on:\n  push:\n    branches: \[landing\]$", text), text)
    check("S3 the starter calls the batch plan kept in kyroco/masthead",
          "    uses: kyroco/masthead/.github/workflows/batch-plan.yml@main\n" in text, text)
    check("S3 the starter calls the batch move kept in kyroco/masthead",
          "    uses: kyroco/masthead/.github/workflows/batch-move.yml@main\n" in text, text)

# The landing branch the starter runs on: made from main when missing, left alone when there.
with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    run = batch(gh, work, "landing")
    check("S3 landing is made from main's commit when missing",
          run.returncode == 0 and gh.state()["refs"].get("landing") == MAIN_SHA, run.stdout + run.stderr)
    state = gh.state()
    state["refs"]["landing"] = "b" * 40
    gh.save(state)
    before = len(gh.writes())
    run = batch(gh, work, "landing")
    check("S3 an existing landing branch is left where it is",
          run.returncode == 0 and gh.state()["refs"]["landing"] == "b" * 40 and len(gh.writes()) == before,
          run.stdout + run.stderr)

# ---- Scenario 4: click-by-click App steps in setup and the README ------------
with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    run = batch(gh, work, "steps")
    steps = run.stdout
    check("S4 steps prints the README's App walkthrough", run.returncode == 0 and steps.strip() != ""
          and steps.replace(REPO, "OWNER/REPO").strip() in read(README), run.stdout + run.stderr)
    # Each button and field as GitHub's own docs name it (docs.github.com, read November 19, 2026).
    for word in ("Your organizations", "Settings", "Developer settings", "GitHub Apps", "New GitHub App",
                 "GitHub App name", "Homepage URL", "Active", "Contents", "Workflows", "Read and write",
                 "Only on this account", "Create GitHub App", "App ID", "Edit", "Credentials", "Key pairs",
                 "New key", ".pem", "Install App", "Install", "All repositories", "Only select repositories",
                 "Select repositories", "masthead-batch"):
        check("S4 the steps name {!r}".format(word), word in steps)
    check("S4 the steps give the exact command for the App id, with this repository filled in",
          "gh secret set BATCH_APP_ID --env masthead-batch --repo acme/site --body " in steps, steps)
    check("S4 the steps give the exact command for the key, with this repository filled in",
          "gh secret set BATCH_APP_PRIVATE_KEY --env masthead-batch --repo acme/site < " in steps, steps)
    check("S4 the steps say the key file downloads once, when it is made, and install does not ask for it",
          re.search(r"downloads? (once|only once)", steps) and "install" in steps.lower() and "not ask" in steps, steps)
    check("S4 the README itself shows the steps with a placeholder for the repository",
          "--repo OWNER/REPO" in read(README))
    check("S4 setup shows the steps from batch.py", "batch.py steps" in read(SKILL))
    check("S4 setup asks for the yes before writing anything for the batch run",
          re.search(r"batch run.*\?\"", read(SKILL)) is not None)

# ---- Scenario 5: the App key is kept from every workflow but the move ---------
with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    state = gh.state()
    state["environments"] = {"masthead-batch": {"custom": True, "protected": False, "secrets": [],
                                                "policies": [{"id": 1, "name": "*", "type": "branch"},
                                                             {"id": 2, "name": "landing", "type": "branch"},
                                                             {"id": 3, "name": "landing", "type": "tag"}]}}
    gh.save(state)
    run = batch(gh, work, "environment")
    env = gh.state()["environments"].get("masthead-batch", {})
    check("S5 environment makes masthead-batch open to chosen branches only",
          run.returncode == 0 and env.get("custom") is True and env.get("protected") is False, run.stdout + run.stderr)
    check("S5 the only branch that may use it is landing, and any wider rule is removed",
          [(p["name"], p["type"]) for p in env.get("policies", [])] == [("landing", "branch")], env)

with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    batch(gh, work, "environment")
    env = gh.state()["environments"].get("masthead-batch", {})
    check("S5 a new environment gets exactly the landing rule",
          [(p["name"], p["type"]) for p in env.get("policies", [])] == [("landing", "branch")], env)
    batch(gh, work, "environment")
    check("S5 running it again adds nothing",
          len(gh.state()["environments"].get("masthead-batch", {}).get("policies", [])) == 1, gh.state())

move = read(MOVE)
move_job = move.split("\n  move:\n", 1)[-1]
check("S5 the move job names the masthead-batch environment, so it alone receives the environment's secrets",
      re.search(r"(?m)^    environment: masthead-batch$", move_job) is not None, move_job[:400])
with tempfile.TemporaryDirectory() as top:
    text = starter_text(repo_with_gate(top))
    gate_part = text.split("\n  gate:\n", 1)[-1].split("\n  move:\n", 1)[0]
    move_part = text.split("\n  move:\n", 1)[-1]
    check("S5 the starter's Gate job does not name the environment", "environment" not in gate_part, gate_part)
    check("S5 the starter still passes both secrets to the move by name, as GitHub needs for an environment secret",
          "BATCH_APP_ID: ${{ secrets.BATCH_APP_ID }}" in move_part
          and "BATCH_APP_PRIVATE_KEY: ${{ secrets.BATCH_APP_PRIVATE_KEY }}" in move_part, move_part)

# check: the key in the environment and nowhere else.
READY = {"masthead-batch": {"custom": True, "protected": False, "secrets": ["BATCH_APP_ID", "BATCH_APP_PRIVATE_KEY"],
                            "policies": [{"id": 1, "name": "landing", "type": "branch"}]}}
with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top, environments=READY, refs={"main": MAIN_SHA, "landing": MAIN_SHA})
    work = repo_with_gate(top)
    batch(gh, work, "write")
    batch(gh, work, "lock", "--app-id", "5832645")
    before = len(gh.writes())
    run = batch(gh, work, "check", "--app-id", "5832645")
    p = parts(run)
    check("S5 check passes when every part is in place", run.returncode == 0 and all(x["ok"] for x in p.values()), p)
    check("S5 check changes nothing on GitHub", len(gh.writes()) == before, gh.writes())
    for part in ("starter file", "landing branch", "environment", "key in the environment", "key nowhere else", "lock"):
        check("S5 check reports {!r}".format(part), part in p, sorted(p))

    state = gh.state()
    state["org_secrets"] = ["BATCH_APP_PRIVATE_KEY"]
    gh.save(state)
    run = batch(gh, work, "check", "--app-id", "5832645")
    p = parts(run)
    check("S5 check fails when the key is an organization secret this repository can read",
          run.returncode == 1 and p.get("key nowhere else", {}).get("ok") is False
          and "organization" in p["key nowhere else"]["say"], p)
    state["org_secrets"] = []
    state["repo_secrets"] = ["BATCH_APP_PRIVATE_KEY"]
    gh.save(state)
    p = parts(batch(gh, work, "check", "--app-id", "5832645"))
    check("S5 check fails when the key is a repository secret",
          p.get("key nowhere else", {}).get("ok") is False and "repository secret" in p["key nowhere else"]["say"], p)
    state["repo_secrets"] = []
    state["environments"]["masthead-batch"]["policies"].append({"id": 2, "name": "*", "type": "branch"})
    state["environments"]["masthead-batch"]["secrets"] = ["BATCH_APP_ID"]
    gh.save(state)
    p = parts(batch(gh, work, "check", "--app-id", "5832645"))
    check("S5 check fails when another branch may use the environment", p.get("environment", {}).get("ok") is False, p)
    check("S5 check fails when the key is missing from the environment",
          p.get("key in the environment", {}).get("ok") is False and "BATCH_APP_PRIVATE_KEY" in p["key in the environment"]["say"], p)
    with open(os.path.join(work, STARTER_PATH), "a", encoding="utf-8") as handle:
        handle.write("# changed\n")
    p = parts(batch(gh, work, "check", "--app-id", "5832645"))
    check("S5 check fails when the starter differs from what setup would write", p.get("starter file", {}).get("ok") is False, p)

with tempfile.TemporaryDirectory() as top:
    gh = GitHub(top)
    work = repo_with_gate(top)
    run = batch(gh, work, "check")
    p = parts(run)
    check("S5 check on a repository with nothing set up fails and names each missing part",
          run.returncode == 1 and all(p[k]["ok"] is False for k in
                                      ("starter file", "landing branch", "environment", "key in the environment", "lock")), p)

print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
