#!/usr/bin/env python3
"""Linear issue MAST-11: Linear to GitHub makes the GitHub project and milestones for a Linear project.

After the person's yes, `migrate.py structure` makes, on GitHub, one project
with the Linear project's name and its brief as the README, linked to the
repository, and each Linear milestone that holds an open issue a repository
milestone named `<project>: <n>. <name>`. A Linear project with no milestones
gets the project and no milestone, so its issues land in the project. A
second run makes nothing twice. Nothing is written to Linear.

Runs the real migrate.py against a fake `gh` on PATH that keeps what it is
sent, and a fake Linear on 127.0.0.1. Run from anywhere:
python3 hooks/tests/migrate-structure-test.py
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SKILL_DIR = os.path.join(ROOT, "skills", "migrate-issues")
SCRIPT = os.path.join(SKILL_DIR, "migrate.py")
SKILL = os.path.join(SKILL_DIR, "SKILL.md")

KEY = "lin_api_TESTKEY0123456789abcdefSECRET"

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL {}{}".format(name, (": " + str(detail)[:1500]) if detail else ""))


# ---------------------------------------------------------------- a fake gh that keeps what it is sent

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
path = os.environ["FAKE_GH_WORLD"]
world = json.load(open(path))


def flag(name):
    return args[args.index(name) + 1] if name in args else None


def save():
    json.dump(world, open(path, "w"))


if " ".join(args[:2]) in world.get("refuse", []):
    sys.exit(1)
if args[:2] == ["project", "list"]:
    mine = [p for p in world["projects"] if p["owner"] == flag("--owner")]
    print(json.dumps({"projects": mine, "totalCount": len(mine)}))
    sys.exit(0)
if args[:2] == ["project", "create"]:
    number = max([p["number"] for p in world["projects"]] + [0]) + 1
    project = {"number": number, "title": flag("--title"), "owner": flag("--owner"), "readme": "",
               "shortDescription": "", "closed": False}
    world["projects"].append(project)
    save()
    print(json.dumps(project))
    sys.exit(0)
if args[:2] == ["project", "edit"]:
    for p in world["projects"]:
        if p["number"] == int(args[2]) and p["owner"] == flag("--owner"):
            if "--readme" in args:
                p["readme"] = flag("--readme")
            if "--description" in args:
                p["shortDescription"] = flag("--description")
    save()
    sys.exit(0)
if args[:2] == ["project", "link"]:
    world["links"].append([flag("--owner"), int(args[2]), flag("--repo")])
    save()
    sys.exit(0)
if args[:1] == ["api"] and args[1] == "graphql":
    fields = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("-"))
    repo = "{}/{}".format(fields["owner"], fields["name"]).lower()
    nodes = [{"number": n} for o, n, r in world["links"] if r.lower() == repo]
    print(json.dumps({"data": {"repository": {"projectsV2": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}))
    sys.exit(0)
if args[:1] == ["api"] and args[1].startswith("repos/") and "/milestones" in args[1]:
    if "POST" in args:
        fields = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "-f")
        world["milestones"].append(fields)
        save()
        print(json.dumps(dict(fields, number=len(world["milestones"]))))
        sys.exit(0)
    page = [{"title": m["title"], "number": n} for n, m in enumerate(world["milestones"], 1)]
    print(json.dumps([page[:1], page[1:]]))
    sys.exit(0)
sys.exit(3)
'''

WRITES = (["project", "create"], ["project", "edit"], ["project", "link"])


def fake_gh(projects=(), milestones=(), links=(), refuse=()):
    tmp = tempfile.mkdtemp(prefix="migrate-structure-gh-")
    bindir = os.path.join(tmp, "bin")
    os.mkdir(bindir)
    gh = os.path.join(bindir, "gh")
    with open(gh, "w") as handle:
        handle.write(FAKE_GH)
    os.chmod(gh, 0o755)
    world_file = os.path.join(tmp, "world.json")
    with open(world_file, "w") as handle:
        json.dump({"projects": list(projects), "milestones": list(milestones), "links": list(links),
                   "refuse": list(refuse)}, handle)
    env = dict(os.environ)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    env["FAKE_GH_LOG"] = os.path.join(tmp, "log")
    env["FAKE_GH_WORLD"] = world_file
    env["MASTHEAD_LINEAR_URL"] = LINEAR_URL
    env["MY_LINEAR_KEY"] = KEY
    open(env["FAKE_GH_LOG"], "w").close()
    return env, tmp


def world(env):
    return json.load(open(env["FAKE_GH_WORLD"]))


def calls(env):
    with open(env["FAKE_GH_LOG"]) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def writes(env):
    return [c for c in calls(env) if c[:2] in WRITES or (c[:1] == ["api"] and "POST" in c)]


# ---------------------------------------------------------------- a fake Linear

BRIEF = "## Why\n\nThe site is old.\n\n## Rules\n\n1. Ship it."


def linear_project(name, milestones, issues, summary="Relaunch the website.", brief=BRIEF):
    return {"id": "p-" + name, "name": name, "description": summary, "content": brief,
            "projectMilestones": {"nodes": milestones}, "issues": issues}


def ms(name, order, description=""):
    return {"name": name, "sortOrder": order, "description": description}


def li(identifier, state, milestone):
    return {"identifier": identifier, "state": {"type": state},
            "projectMilestone": {"name": milestone} if milestone else None}


WEBSITE = linear_project("Website relaunch", [ms("Launch", 2.0, "Go live."), ms("Build", 1.0, "Make it."),
                                              ms("Retire", 4.0), ms("3. Polish", 3.0)],
                         [li("WEB-1", "backlog", "Build"), li("WEB-2", "unstarted", "Launch"),
                          li("WEB-3", "completed", "Launch"), li("WEB-4", "started", None),
                          li("WEB-5", "canceled", "Retire"), li("WEB-6", "started", "3. Polish")])
FLAT = linear_project("Flat work", [], [li("FL-1", "backlog", None), li("FL-2", "started", None)],
                      summary="", brief="Just a list.")


class Linear(http.server.BaseHTTPRequestHandler):
    projects = [WEBSITE, FLAT]
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        Linear.seen.append(body["query"])
        query, v = body["query"], body.get("variables") or {}
        if query.lstrip().startswith("mutation"):
            payload = {"errors": [{"message": "no writes to Linear"}]}
        elif "projects(" in query:
            payload = {"data": {"projects": {"nodes": [
                {k: val for k, val in p.items() if k != "issues"} for p in Linear.projects if p["name"] == v["name"]]}}}
        elif "project(id" in query:
            found = [p for p in Linear.projects if p["id"] == v["id"]][0]
            start = int(v.get("after") or 0)
            more = start + 2 < len(found["issues"])
            payload = {"data": {"project": {"issues": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                                                       "nodes": found["issues"][start:start + 2]}}}}
        else:
            payload = {"errors": [{"message": "unexpected query"}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Linear)
threading.Thread(target=server.serve_forever, daemon=True).start()
LINEAR_URL = "http://127.0.0.1:{}/graphql".format(server.server_address[1])


def save_plan(tmp, **change):
    record = {"direction": "linear-to-github", "source": "Website relaunch", "target": "acme/site",
              "access": {"kind": "key", "key_env": "MY_LINEAR_KEY", "kept": "op://Private/Linear/credential"}}
    record.update(change)
    path = os.path.join(tmp, "plan.json")
    with open(path, "w") as handle:
        json.dump(record, handle)
    return path


def run(env, plan, project="Website relaunch", repo="acme/site"):
    args = [sys.executable, SCRIPT, "structure", "--project", project, "--repo", repo,
            "--key-env", "MY_LINEAR_KEY", "--plan", plan]
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


def no_key(out, err):
    return KEY not in out and KEY not in err


# --- Scenario 1: the Linear project becomes a GitHub project with the same name and its brief as the README.

env, tmp = fake_gh()
plan = save_plan(tmp)
Linear.seen = []
code, out, err = run(env, plan)
check("structure runs", code == 0, out + err)
made = [p for p in world(env)["projects"] if p["title"] == "Website relaunch"]
check("one GitHub project with the Linear project's name, owned by the repository's owner",
      len(made) == 1 and made[0]["owner"] == "acme", world(env))
check("its README is the Linear project's brief", made and made[0]["readme"] == BRIEF, made)
check("its short description is the Linear project's summary",
      made and made[0]["shortDescription"] == "Relaunch the website.", made)
check("the project is linked to the repository",
      made and world(env)["links"] == [["acme", made[0]["number"], "acme/site"]], world(env)["links"])
check("structure says it made the project", 'GitHub project "Website relaunch"' in out and "made now" in out, out)
check("structure writes nothing to Linear",
      Linear.seen and not any(q.lstrip().startswith("mutation") for q in Linear.seen), Linear.seen)
check("structure keeps the key out of what it prints", no_key(out, err))

# --- Scenario 2: each Linear milestone becomes a repository milestone named <project>: <n>. <name>.

titles = [m["title"] for m in world(env)["milestones"]]
check("milestones are named <project>: <n>. <name> in Linear's order",
      titles == ["Website relaunch: 1. Build", "Website relaunch: 2. Launch", "Website relaunch: 3. Polish"], titles)
check("a milestone's Linear description carries over",
      [m.get("description") for m in world(env)["milestones"]][:2] == ["Make it.", "Go live."], world(env)["milestones"])
check("a Linear milestone with no open issue is not made", not any("Retire" in t for t in titles), titles)
check("structure names each milestone it made", 'milestone "Website relaunch: 1. Build"' in out, out)
check("structure says issues with no milestone land in the project",
      "no milestone (1 issue)" in out and "in the project itself" in out, out)

# A second run makes nothing twice.
open(env["FAKE_GH_LOG"], "w").close()
code, out, err = run(env, plan)
check("a second run succeeds", code == 0, out + err)
check("a second run writes nothing to GitHub", writes(env) == [], writes(env))
check("a second run says the project and milestones were already there",
      "already there" in out and "Milestones made now: none" in out, out)

# A milestone already on GitHub under its name is kept; only the missing ones are made.
env, tmp = fake_gh(milestones=[{"title": "Website relaunch: 2. Launch"}])
code, out, err = run(env, save_plan(tmp))
titles = [m["title"] for m in world(env)["milestones"]]
check("only the missing milestones are made",
      code == 0 and sorted(titles) == ["Website relaunch: 1. Build", "Website relaunch: 2. Launch",
                                       "Website relaunch: 3. Polish"], titles)

# A Linear name that starts with a version number, not a place number, still gets its place (round 1 fix S2-1).
Linear.projects.append(linear_project("Shop", [ms("Alpha", 1.0), ms("2.0 Launch", 2.0), ms("1.5 Beta", 3.0)],
                                      [li("SH-1", "backlog", "Alpha"), li("SH-2", "backlog", "2.0 Launch"),
                                       li("SH-3", "backlog", "1.5 Beta")]))
env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="Shop"), project="Shop")
titles = [m["title"] for m in world(env)["milestones"]]
check("a Linear milestone named like a version keeps its place number",
      code == 0 and titles == ["Shop: 1. Alpha", "Shop: 2. 2.0 Launch", "Shop: 3. 1.5 Beta"], out + err + str(titles))
Linear.projects.pop()

# --- Scenario 3: a Linear project with no milestones gets the project and no milestone.

env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="Flat work"), project="Flat work")
check("a project with no milestones is made", code == 0 and [p["title"] for p in world(env)["projects"]] == ["Flat work"],
      out + err)
check("a project with no milestones gets no milestone", world(env)["milestones"] == [], world(env)["milestones"])
check("its issues land in the project with no milestone",
      "no milestone (2 issues)" in out and "in the project itself" in out, out)
check("an empty Linear summary leaves the short description alone",
      [p["shortDescription"] for p in world(env)["projects"]] == [""], world(env)["projects"])

# --- A GitHub project that already exists is used, and what a person wrote on it is kept.

existing = {"number": 7, "title": "Website relaunch", "owner": "acme", "readme": "Written on GitHub.",
            "shortDescription": "", "closed": False}
env, tmp = fake_gh(projects=[existing, dict(existing, number=8, title="Other", readme="")])
code, out, err = run(env, save_plan(tmp))
mine = [p for p in world(env)["projects"] if p["title"] == "Website relaunch"]
check("an existing GitHub project of that name is used, not a second one", code == 0 and len(mine) == 1, world(env))
check("a README already on GitHub is left as it is", mine[0]["readme"] == "Written on GitHub.", mine)
check("structure says the README was left", "left as it is" in out, out)
check("the empty short description is filled from Linear", mine[0]["shortDescription"] == "Relaunch the website.", mine)
check("the existing project is linked", world(env)["links"] == [["acme", 7, "acme/site"]], world(env)["links"])
check("structure says the empty description was set from the Linear summary",
      "Short description: set from the Linear project's summary." in out, out)

# A short description already on GitHub is kept, and named (round 1 fix S1-1).
env, tmp = fake_gh(projects=[dict(existing, shortDescription="GitHub summary")])
code, out, err = run(env, save_plan(tmp))
mine = [p for p in world(env)["projects"] if p["title"] == "Website relaunch"]
check("a short description already on GitHub is kept", code == 0 and mine[0]["shortDescription"] == "GitHub summary",
      out + err + str(mine))
check("structure names the kept short description",
      "Short description: GitHub already holds one, so it was left as it is." in out, out)

# Two GitHub projects with the name: refuse, write nothing.
env, tmp = fake_gh(projects=[existing, dict(existing, number=9)])
code, out, err = run(env, save_plan(tmp))
check("two GitHub projects with the name are refused, nothing written",
      code != 0 and writes(env) == [] and "2 GitHub projects" in err, out + err)

# A run that stops partway is finished by the next one.
env, tmp = fake_gh(refuse=["project edit"])
code, out, err = run(env, save_plan(tmp))
check("a refused README write stops the run", code != 0 and "run it again" in err.lower(), out + err)
world_now = world(env)
world_now["refuse"] = []
json.dump(world_now, open(env["FAKE_GH_WORLD"], "w"))
code, out, err = run(env, save_plan(tmp))
made = world(env)["projects"]
check("the next run sets the README on the project the first run made, without a second project",
      code == 0 and len(made) == 1 and made[0]["readme"] == BRIEF, out + err + str(made))

# --- Nothing is written without the person's yes to this move.

env, tmp = fake_gh()
for name, plan_path in (
        ("no saved plan", os.path.join(tmp, "missing.json")),
        ("a plan for GitHub to Linear", save_plan(tmp, direction="github-to-linear")),
        ("a plan for another Linear project", save_plan(tmp, source="Other work")),
        ("a plan for another repository", save_plan(tmp, target="acme/other")),
        ("a plan through the connector", save_plan(tmp, access={"kind": "connector"})),
        ("a plan reading the key from another variable",
         save_plan(tmp, access={"kind": "key", "key_env": "OTHER", "kept": "op://x/y/z"}))):
    open(env["FAKE_GH_LOG"], "w").close()
    code, out, err = run(env, plan_path)
    check("structure refuses {} and writes nothing".format(name), code != 0 and writes(env) == [], out + err)
code, out, err = run(env, save_plan(tmp, access={"kind": "connector"}))
check("a connector plan is refused, saying a key is needed", "API key" in err, err)
code, out, err = run(env, save_plan(tmp, source="linear:Website relaunch", target="github:ACME/site"))
check("a plan written as linear:<project> and github:<owner>/<repo> is accepted", code == 0, out + err)

env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="Nope"), project="Nope")
check("a Linear project that does not exist is refused, nothing written",
      code != 0 and writes(env) == [] and 'No Linear project named "Nope"' in err, out + err)

# --- Names are data: a line break in one prints escaped and is passed to gh as one value.

FORGED = "Nothing was written to Linear."
Linear.projects = [linear_project("Evil\n" + FORGED, [ms("Build\nfake", 1.0)], [li("EV-1", "backlog", "Build\nfake")])]
env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="Evil\n" + FORGED), project="Evil\n" + FORGED)
check("a Linear name cannot forge a line of structure's output",
      code == 0 and out.splitlines().count(FORGED) == 1 and "\\n" in out, out + err)
check("the GitHub project gets the Linear name as it is",
      [p["title"] for p in world(env)["projects"]] == ["Evil\n" + FORGED], world(env)["projects"])

# --- The skill says how to run it.

text = open(SKILL).read() if os.path.exists(SKILL) else ""


def says(phrase):
    check("SKILL.md says: " + phrase, phrase in text)


says("migrate.py structure --project '<project name>' --repo <owner>/<repo> --key-env")
check("SKILL.md no longer says Linear to GitHub is not built at all",
      "**Linear to GitHub** has not been built yet" not in text)

server.shutdown()
print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
