#!/usr/bin/env python3
"""Linear issue MAST-12: Linear to GitHub copies each open Linear issue to GitHub.

After the person's yes, and after `migrate.py structure` made the GitHub
project and milestones, `migrate.py copy-to-github` makes one GitHub issue
for each open Linear issue of the project (or each issue named by key), with
the same title, body and labels and every comment, each comment naming its
Linear author and time in Eastern. Each issue lands in its milestone and in
the GitHub project, with the same Status. Needs Human becomes the
needs-decision label. Each copy's body ends with a hidden line naming its
Linear key (Robert, November 4: "yes"). Nothing is written to Linear.

Runs the real migrate.py against a fake `gh` on PATH that keeps what it is
sent, and a fake Linear on 127.0.0.1. Run from anywhere:
python3 hooks/tests/migrate-copy-github-test.py
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
stdin = sys.stdin.read() if "--input" in args else ""
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps({"args": args, "stdin": stdin}) + "\n")
path = os.environ["FAKE_GH_WORLD"]
world = json.load(open(path))
joined = " ".join(args)


def flag(name):
    return args[args.index(name) + 1] if name in args else None


def save():
    json.dump(world, open(path, "w"))


if any(r in joined for r in world.get("refuse", [])):
    sys.exit(1)
if args[:2] == ["project", "list"]:
    mine = [p for p in world["projects"] if p["owner"] == flag("--owner")]
    print(json.dumps({"projects": mine, "totalCount": len(mine)}))
    sys.exit(0)
if args[:2] == ["project", "field-list"]:
    print(json.dumps({"fields": world["fields"].get(args[2], []), "totalCount": 1}))
    sys.exit(0)
if args[:2] == ["api", "graphql"]:
    fields = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("-"))
    if "addProjectV2ItemById" in fields["query"]:
        item = "ITEM_{}".format(len(world["items"]) + 1)
        world["items"].append({"id": item, "project": fields["project"], "content": fields["content"]})
        save()
        print(json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": item}}}}))
        sys.exit(0)
    if "updateProjectV2ItemFieldValue" in fields["query"]:
        world["statuses"].append({k: fields[k] for k in ("project", "item", "field", "option")})
        save()
        print(json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": fields["item"]}}}}))
        sys.exit(0)
    sys.exit(4)
if args[:1] == ["api"] and args[1].startswith("repos/"):
    where = args[1].split("?")[0]
    post = "POST" in args
    sent = json.loads(stdin) if stdin else {}
    if where.endswith("/milestones") and not post:
        page = [{"title": m["title"], "number": n} for n, m in enumerate(world["milestones"], 1)]
        print(json.dumps([page[:1], page[1:]]))
        sys.exit(0)
    if where.endswith("/labels"):
        if post:
            world["labels"].append(sent)
            save()
            print(json.dumps(sent))
        else:
            print(json.dumps([world["labels"]]))
        sys.exit(0)
    if where.endswith("/issues") and post:
        number = 100 + len(world["issues"])
        world["issues"].append(dict(sent, number=number, node_id="I_{}".format(number), comments=[]))
        save()
        print(json.dumps({"number": number, "node_id": "I_{}".format(number)}))
        sys.exit(0)
    if where.endswith("/comments") and post:
        number = int(where.split("/")[-2])
        for issue in world["issues"]:
            if issue["number"] == number:
                issue["comments"].append(sent["body"])
        save()
        print(json.dumps({"id": 1}))
        sys.exit(0)
sys.exit(3)
'''

STATUS = ["Backlog", "Todo", "In Progress", "In Review", "Done"]


def status_field(options=STATUS):
    return [{"id": "FIELD_TITLE", "name": "Title", "type": "ProjectV2Field"},
            {"id": "FIELD_STATUS", "name": "Status", "type": "ProjectV2SingleSelectField",
             "options": [{"id": "OPT_" + o.replace(" ", "_"), "name": o} for o in options]}]


def projects():
    return [{"number": 3, "id": "PVT_web", "title": "Website relaunch", "owner": "acme"},
            {"number": 4, "id": "PVT_flat", "title": "Flat work", "owner": "acme"}]


MILESTONES = [{"title": "Website relaunch: 1. Build"}, {"title": "Website relaunch: 2. Launch"},
              {"title": "Website relaunch: 3. Polish"}]


def fake_gh(milestones=MILESTONES, fields=None, refuse=(), project_list=None):
    tmp = tempfile.mkdtemp(prefix="migrate-copy-github-")
    bindir = os.path.join(tmp, "bin")
    os.mkdir(bindir)
    gh = os.path.join(bindir, "gh")
    with open(gh, "w") as handle:
        handle.write(FAKE_GH)
    os.chmod(gh, 0o755)
    world_file = os.path.join(tmp, "world.json")
    with open(world_file, "w") as handle:
        json.dump({"projects": projects() if project_list is None else project_list,
                   "fields": fields or {"3": status_field(), "4": status_field()},
                   "milestones": list(milestones), "labels": [{"name": "bug", "color": "d73a4a"}],
                   "issues": [], "items": [], "statuses": [], "refuse": list(refuse)}, handle)
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


def writes(env):
    with open(env["FAKE_GH_LOG"]) as handle:
        logged = [json.loads(line)["args"] for line in handle if line.strip()]
    return [a for a in logged if "POST" in a or (a[:2] == ["api", "graphql"] and any("mutation" in x for x in a))]


# ---------------------------------------------------------------- a fake Linear

def ms(name, order):
    return {"name": name, "sortOrder": order, "description": ""}


def issue(identifier, state, kind, milestone, project, title=None, description="", labels=(), comments=()):
    return {"identifier": identifier, "title": title or "Do " + identifier, "description": description,
            "state": {"name": state, "type": kind}, "labels": {"nodes": [{"name": n, "color": c} for n, c in labels]},
            "projectMilestone": {"name": milestone} if milestone else None, "project": project,
            "comments": list(comments)}


def comment(body, when, user=None, bot=None):
    return {"body": body, "createdAt": when, "user": {"name": user} if user else None,
            "botActor": {"name": bot} if bot else None}


WEB_MILESTONES = [ms("Launch", 2.0), ms("Build", 1.0), ms("Retire", 4.0), ms("3. Polish", 3.0)]
WEB_REF = {"name": "Website relaunch", "projectMilestones": {"nodes": WEB_MILESTONES}}
FLAT_REF = {"name": "Flat work", "projectMilestones": {"nodes": []}}

WEB1_BODY = "Make the home page.\n\n<!-- copied from Linear KOR-9 -->"
ISSUES = {i["identifier"]: i for i in [
    issue("WEB-1", "Backlog", "backlog", "Build", WEB_REF, title="Build the home page", description=WEB1_BODY,
          labels=[("Bug", "#eb5757"), ("Feature", "#bb87fc")],
          comments=[comment("Second thought.", "2026-11-03T18:27:00.000Z", user="Robert Sfeir"),
                    comment("First thought.", "2026-11-03T12:10:15.715Z", user="Robert Sfeir"),
                    comment("Linked a pull request.", "2026-11-03T19:00:00.000Z", bot="GitHub")]),
    issue("WEB-2", "Todo", "unstarted", "Launch", WEB_REF),
    issue("WEB-3", "Done", "completed", "Launch", WEB_REF),
    issue("WEB-4", "In Progress", "started", None, WEB_REF),
    issue("WEB-6", "In Review", "started", "3. Polish", WEB_REF),
    issue("WEB-7", "Needs Human", "started", "Build", WEB_REF),
    issue("WEB-8", "Triage", "triage", "Build", WEB_REF),
    issue("FL-1", "Backlog", "backlog", None, FLAT_REF),
    issue("FL-2", "In Progress", "started", None, FLAT_REF),
    issue("NP-1", "Todo", "unstarted", None, None),
    issue("NP-2", "Needs Human", "started", None, None),
]}


def linear_project(name, ref, keys):
    return {"id": "p-" + name, "name": name, "description": "", "content": "", "projectMilestones": ref["projectMilestones"],
            "keys": keys}


class Linear(http.server.BaseHTTPRequestHandler):
    projects = [linear_project("Website relaunch", WEB_REF, ["WEB-1", "WEB-2", "WEB-3", "WEB-4", "WEB-6", "WEB-7", "WEB-8"]),
                linear_project("Flat work", FLAT_REF, ["FL-1", "FL-2"])]
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        Linear.seen.append(body["query"])
        query, v = body["query"], body.get("variables") or {}
        if query.lstrip().startswith("mutation"):
            payload = {"errors": [{"message": "no writes to Linear"}]}
        elif "projects(" in query:
            payload = {"data": {"projects": {"nodes": [
                {k: val for k, val in p.items() if k != "keys"} for p in Linear.projects if p["name"] == v["name"]]}}}
        elif "project(id" in query:
            found = [p for p in Linear.projects if p["id"] == v["id"]][0]
            nodes = [{"identifier": k, "state": ISSUES[k]["state"], "projectMilestone": ISSUES[k]["projectMilestone"]}
                     for k in found["keys"]]
            start = int(v.get("after") or 0)
            more = start + 2 < len(nodes)
            payload = {"data": {"project": {"issues": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                                                       "nodes": nodes[start:start + 2]}}}}
        elif "comments(" in query and "issue(id" in query:
            found = ISSUES.get(v["id"].upper())
            start = int(v.get("after") or 0)
            nodes = found["comments"] if found else []
            more = start + 2 < len(nodes)
            payload = {"data": {"issue": {"comments": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                                                       "nodes": nodes[start:start + 2]}}}}
        elif "issue(id" in query:
            found = ISSUES.get(v["id"].upper())
            payload = {"data": {"issue": {k: val for k, val in found.items() if k != "comments"} if found else None}}
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


def run(env, plan, project="Website relaunch", repo="acme/site", issues=None):
    args = [sys.executable, SCRIPT, "copy-to-github", "--repo", repo, "--key-env", "MY_LINEAR_KEY", "--plan", plan]
    if issues:
        args += ["--issues"] + list(issues)
    else:
        name_file = os.path.join(os.path.dirname(plan), "project-name.txt")
        with open(name_file, "w") as handle:
            handle.write(project + "\n")
        args += ["--project-file", name_file]
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


def by_title(env):
    return {i["title"]: i for i in world(env)["issues"]}


def item_of(env, issue_):
    return [i for i in world(env)["items"] if i["content"] == issue_["node_id"]]


def status_of(env, issue_):
    items = item_of(env, issue_)
    found = [s["option"] for s in world(env)["statuses"] if items and s["item"] == items[0]["id"]]
    return found[0] if found else None


# --- Scenario 1: each open Linear issue becomes one GitHub issue with the same title, description,
# labels and every comment, each comment naming its original author and time in Eastern.

env, tmp = fake_gh()
Linear.seen = []
code, out, err = run(env, save_plan(tmp))
check("copy-to-github runs", code == 0, out + err)
made = by_title(env)
check("each open Linear issue becomes one GitHub issue",
      sorted(made) == sorted(ISSUES[k]["title"] for k in ("WEB-1", "WEB-2", "WEB-4", "WEB-6", "WEB-7", "WEB-8"))
      and len(world(env)["issues"]) == 6, sorted(made))
check("a closed Linear issue is not copied", "Do WEB-3" not in made, sorted(made))
check("a project run names the closed Linear issue it left behind (round 1 fix s1-F1)",
      "Not copied, closed in Linear: WEB-3." in out, out)
web1 = made.get("Build the home page", {})
body = web1.get("body", "")
check("the GitHub issue holds the Linear description", body.startswith("Make the home page."), body)
check("the body ends with a hidden line naming the Linear key (Robert, November 4: \"yes\")",
      (body.splitlines() or [""])[-1] == "<!-- copied from Linear WEB-1 -->", body)
check("a hidden line written into the Linear text is changed so it never counts",
      "<!-- copied from Linear KOR-9" not in body and "<!-- quoted from Linear KOR-9 -->" in body, body)
check("the issue carries the same labels, reusing a GitHub label of the same name whatever its case",
      sorted(web1.get("labels", [])) == ["Feature", "bug"], web1.get("labels"))
check("a label GitHub lacks is made, in its Linear color",
      {"name": "Feature", "color": "bb87fc"} in world(env)["labels"], world(env)["labels"])
check("every comment is copied, oldest first, each naming its Linear author and time in Eastern",
      web1.get("comments") == [
          "Written in Linear by Robert Sfeir, November 3, 2026, 7:10 AM Eastern.\n\nFirst thought.",
          "Written in Linear by Robert Sfeir, November 3, 2026, 1:27 PM Eastern.\n\nSecond thought.",
          "Written in Linear by GitHub, November 3, 2026, 2:00 PM Eastern.\n\nLinked a pull request."],
      web1.get("comments"))
check("copy-to-github writes nothing to Linear",
      Linear.seen and not any(q.lstrip().startswith("mutation") for q in Linear.seen), Linear.seen)
check("copy-to-github keeps the key out of what it prints", KEY not in out + err)
check("copy-to-github names what each Linear issue became", "WEB-1 became #" in out, out)

# --- Scenario 2: an issue in a Linear milestone is in both that milestone and the GitHub project.

check("an issue in a Linear milestone is in its GitHub milestone",
      web1.get("milestone") == 1 and made["Do WEB-2"].get("milestone") == 2 and made["Do WEB-6"].get("milestone") == 3,
      [(t, i.get("milestone")) for t, i in made.items()])
check("every copied issue is in the GitHub project",
      all(len(item_of(env, i)) == 1 and item_of(env, i)[0]["project"] == "PVT_web" for i in made.values()),
      world(env)["items"])

# --- Scenario 3: Backlog, Todo, In Progress and In Review land as the same GitHub Status.

check("Backlog, Todo, In Progress and In Review keep their Status on GitHub",
      [status_of(env, made[t]) for t in ("Build the home page", "Do WEB-2", "Do WEB-4", "Do WEB-6")]
      == ["OPT_Backlog", "OPT_Todo", "OPT_In_Progress", "OPT_In_Review"], world(env)["statuses"])
check("the Status is set on the project's Status field",
      all(s["field"] == "FIELD_STATUS" and s["project"] == "PVT_web" for s in world(env)["statuses"]),
      world(env)["statuses"])
check("an issue with no milestone lands in the project with no milestone", "milestone" not in made["Do WEB-4"],
      made["Do WEB-4"])
check("a Linear status GitHub has no match for leaves the Status empty, and is named",
      status_of(env, made["Do WEB-8"]) is None and "WEB-8 (Triage)" in out, out)

# --- Scenario 5: Needs Human lands with the needs-decision label (and Status Todo, as an answered issue goes back to Todo).

check("a Needs Human issue carries the needs-decision label",
      made["Do WEB-7"].get("labels") == ["needs-decision"], made["Do WEB-7"])
check("the needs-decision label is made when the repository lacks it",
      any(l["name"] == "needs-decision" for l in world(env)["labels"]), world(env)["labels"])
check("a Needs Human issue has Status Todo", status_of(env, made["Do WEB-7"]) == "OPT_Todo", world(env)["statuses"])

# --- Scenario 4: a Linear project with no milestones: its issues join the GitHub project with no milestone.

env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="Flat work"), project="Flat work")
made = by_title(env)
check("a project with no milestones is copied", code == 0 and sorted(made) == ["Do FL-1", "Do FL-2"], out + err)
check("its issues have no milestone", all("milestone" not in i for i in made.values()), made)
check("its issues are in the GitHub project",
      all(item_of(env, i) and item_of(env, i)[0]["project"] == "PVT_flat" for i in made.values()), world(env)["items"])
check("its issues keep their Status", sorted(status_of(env, i) for i in made.values()) == ["OPT_Backlog", "OPT_In_Progress"],
      world(env)["statuses"])

# --- Issues named by key.

env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="WEB-2 WEB-4"), issues=["WEB-2", "web-4"])
check("issues named by key are copied, and only those",
      code == 0 and sorted(by_title(env)) == ["Do WEB-2", "Do WEB-4"], out + err)
env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="NP-1 NP-2"), issues=["NP-1", "NP-2"])
check("an issue in no Linear project is said to have no Status, never one it was not given (round 1 fix s3-F1)",
      code == 0 and "NP-1 became #100: no project, no milestone, Status empty" in out
      and "NP-2 became #101: no project, no milestone, Status empty, needs-decision" in out
      and world(env)["statuses"] == [], out + err)
check("a Needs Human issue in no project still carries the needs-decision label",
      [i.get("labels") for i in world(env)["issues"]] == [None, ["needs-decision"]], world(env)["issues"])
env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="WEB-2"), issues=["WEB-2", "web-2"])
check("a key named twice, in any case, is copied once (round 1 fix s1-F2)",
      code == 0 and len(world(env)["issues"]) == 1, out + err)
env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="WEB-2 WEB-3"), issues=["WEB-2", "WEB-3"])
check("a closed issue named by key is not copied, and is named",
      code == 0 and sorted(by_title(env)) == ["Do WEB-2"] and "WEB-3" in out, out + err)
env, tmp = fake_gh()
code, out, err = run(env, save_plan(tmp, source="WEB-2"), issues=["WEB-2", "WEB-4"])
check("issues the plan does not name are refused, nothing written", code != 0 and writes(env) == [], out + err)
code, out, err = run(env, save_plan(tmp, source="WEB-2; rm"), issues=["WEB-2;", "rm"])
check("something that is not a Linear key is refused, nothing written", code != 0 and writes(env) == [], out + err)

# --- Nothing is written unless GitHub holds everything the issues land in.

env, tmp = fake_gh(fields={"3": status_field(["Todo", "In Progress", "Done"]), "4": status_field()})
code, out, err = run(env, save_plan(tmp))
check("a GitHub project lacking a needed Status stops the copy before any write, naming it",
      code != 0 and writes(env) == [] and "Backlog" in err and "In Review" in err, out + err)
env, tmp = fake_gh(milestones=MILESTONES[:1])
code, out, err = run(env, save_plan(tmp))
check("a missing GitHub milestone stops the copy before any write, saying to run structure",
      code != 0 and writes(env) == [] and "structure" in err, out + err)
env, tmp = fake_gh(project_list=[])
code, out, err = run(env, save_plan(tmp))
check("a missing GitHub project stops the copy before any write, saying to run structure",
      code != 0 and writes(env) == [] and "structure" in err, out + err)
env, tmp = fake_gh(project_list=projects() + [dict(projects()[0], number=9, id="PVT_two")])
code, out, err = run(env, save_plan(tmp))
check("two GitHub projects with the name stop the copy before any write", code != 0 and writes(env) == [], out + err)

# A refusal partway stops and names what this run already made.
env, tmp = fake_gh(refuse=["addProjectV2ItemById"])
code, out, err = run(env, save_plan(tmp))
check("a refusal partway stops the copy and names what it made",
      code != 0 and "WEB-1 as #100" in err and len(world(env)["issues"]) == 1, out + err)
check("a refusal partway says a second run would copy those again", "second time" in err, err)

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
    check("copy-to-github refuses {} and writes nothing".format(name), code != 0 and writes(env) == [], out + err)

# --- The skill says how to run it.

text = open(SKILL).read() if os.path.exists(SKILL) else ""
check("SKILL.md says how to run the copy",
      "migrate.py copy-to-github --repo <owner>/<repo> --project-file <file> --key-env" in text)
check("SKILL.md no longer says copying the issues has not been built",
      "Copying the issues themselves has not been built yet" not in text)

server.shutdown()
print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
