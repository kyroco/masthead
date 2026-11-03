#!/usr/bin/env python3
"""Linear issue MAST-15: the migration skill copies open GitHub issues into Linear.

After the person's yes, `migrate.py copy` makes one Linear project with the
GitHub project's name, each GitHub milestone a milestone inside it, and each
chosen open issue a Linear issue with the same title, body, labels and every
comment; each comment starts with a line naming its GitHub author and its time
in Eastern. needs-decision or parked lands as Needs Human. A second run copies
nothing twice.

Runs the real migrate.py against a fake `gh` on PATH and a fake Linear on
127.0.0.1 that keeps what it is sent. Run from anywhere:
python3 hooks/tests/migrate-copy-test.py
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


# ---------------------------------------------------------------- a fake gh

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] != ["api", "graphql"]:
    sys.exit(3)
fields = {}
for a in args:
    if "=" in a and not a.startswith("-"):
        k, v = a.split("=", 1)
        fields[k] = v
query = fields["query"]
if query.lstrip().startswith("mutation"):
    sys.exit(4)
world = json.load(open(os.environ["FAKE_GH_WORLD"]))
if "projectV2" in query:
    owner = "organization" if "organization(" in query else "user"
    print(json.dumps({"data": {owner: {"projectV2": world["project"]}}}))
    sys.exit(0)
number = fields["number"]
if number in world.get("broken", []):
    sys.exit(1)
issue = dict(world["issues"][number])
comments = issue.pop("all_comments")
size = 2
start = int(fields.get("after") or 0)
page = comments[start:start + size]
more = start + size < len(comments)
issue["comments"] = {"pageInfo": {"hasNextPage": more, "endCursor": str(start + size) if more else None},
                     "nodes": page}
print(json.dumps({"data": {"repository": {"issue": issue}}}))
'''


def gh_issue(number, title, milestone, labels=(), comments=(), state="OPEN", repo="acme/site", body=None):
    return {"number": number, "title": title, "body": body if body is not None else "Body of {}.".format(number),
            "state": state, "repository": repo, "milestone": {"title": milestone} if milestone else None,
            "labels": {"nodes": [{"name": n} for n in labels]}, "all_comments": list(comments)}


def comment(login, when, body):
    return {"author": {"login": login} if login else None, "createdAt": when, "body": body}


ISSUES = [
    gh_issue(1, "Ship the launch page", "Website relaunch: 2. Launch", labels=["Feature"],
             comments=[comment("octocat", "2026-11-03T18:27:00Z", "First thought."),
                       comment("hubot", "2026-07-04T03:05:00Z", "Summer note."),
                       comment(None, "2026-01-15T12:00:00Z", "From someone gone.")]),
    gh_issue(2, "Build the header", "Website relaunch: 1. Build", labels=["bug", "needs-decision"]),
    gh_issue(3, "Write the copy", None, labels=["parked"]),
    gh_issue(4, "Old cleanup", "Website relaunch: 3. Retire", state="CLOSED"),
    gh_issue(5, "Fix footer", "Website relaunch: 1. Build"),
    gh_issue(6, "Fix footer", "Website relaunch: 1. Build", body="A second issue with the same title."),
    gh_issue(9, "Store page", "Apps: 1. Store", repo="acme/apps"),
]


def world_for(issues):
    nodes = [{"content": {"__typename": "Issue", "number": i["number"], "state": i["state"],
                          "repository": {"nameWithOwner": i["repository"]}, "milestone": i["milestone"]}}
             for i in issues]
    nodes.append({"content": {"__typename": "DraftIssue"}})
    return {"project": {"title": "Website relaunch",
                        "items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}},
            "issues": {str(i["number"]): {k: v for k, v in i.items() if k != "repository"} for i in issues}}


def fake_gh(world):
    tmp = tempfile.mkdtemp(prefix="migrate-copy-gh-")
    bindir = os.path.join(tmp, "bin")
    os.mkdir(bindir)
    gh = os.path.join(bindir, "gh")
    with open(gh, "w") as handle:
        handle.write(FAKE_GH)
    os.chmod(gh, 0o755)
    world_file = os.path.join(tmp, "world.json")
    with open(world_file, "w") as handle:
        json.dump(world, handle)
    env = dict(os.environ)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    env["FAKE_GH_LOG"] = os.path.join(tmp, "log")
    env["FAKE_GH_WORLD"] = world_file
    env["MASTHEAD_LINEAR_URL"] = LINEAR_URL
    env["MY_LINEAR_KEY"] = KEY
    return env, tmp


# ---------------------------------------------------------------- a fake Linear that keeps what it is sent

class Store:
    def __init__(self, needs_human=True):
        self.n = 0
        self.states = [{"id": "st-backlog", "name": "Backlog"}, {"id": "st-todo", "name": "Todo"}]
        if needs_human:
            self.states.append({"id": "st-human", "name": "Needs Human"})
        self.team_labels = [{"id": "lb-feature", "name": "Feature"}]
        self.workspace_labels = [{"id": "lb-bug", "name": "Bug"}]
        self.projects = []
        self.milestones = []
        self.issues = []
        self.comments = []
        self.writes = []

    def next(self, prefix):
        self.n += 1
        return "{}-{}".format(prefix, self.n)


def answer(store, body):
    query, v = body["query"], body.get("variables") or {}
    if query.lstrip().startswith("mutation"):
        store.writes.append(query.split("{", 2)[1].split("(")[0].strip())
        data = v["input"]
        if "projectCreate" in query:
            p = {"id": store.next("pr"), "name": data["name"], "teamIds": data["teamIds"]}
            store.projects.append(p)
            return {"projectCreate": {"success": True, "project": {"id": p["id"]}}}
        if "projectMilestoneCreate" in query:
            m = dict(data, id=store.next("ms"))
            store.milestones.append(m)
            return {"projectMilestoneCreate": {"success": True, "projectMilestone": {"id": m["id"]}}}
        if "issueLabelCreate" in query:
            label = {"id": store.next("lb"), "name": data["name"]}
            store.team_labels.append(label)
            return {"issueLabelCreate": {"success": True, "issueLabel": {"id": label["id"]}}}
        if "issueCreate" in query:
            issue = dict(data, id=store.next("is"), createdAt="2026-11-03T15:00:{:02d}Z".format(store.n))
            store.issues.append(issue)
            return {"issueCreate": {"success": True, "issue": {"id": issue["id"]}}}
        if "commentCreate" in query:
            c = dict(data, id=store.next("cm"))
            store.comments.append(c)
            return {"commentCreate": {"success": True, "comment": {"id": c["id"]}}}
        raise AssertionError("unknown mutation " + query)
    if "teams(" in query:
        nodes = [{"id": "team-web", "key": "WEB", "states": {"nodes": store.states},
                  "labels": {"nodes": store.team_labels}}] if v.get("key") == "WEB" else []
        return {"teams": {"nodes": nodes}, "issueLabels": {"nodes": store.workspace_labels}}
    if "projects(" in query:
        return {"projects": {"nodes": [
            {"id": p["id"], "name": p["name"], "teams": {"nodes": [{"id": t} for t in p["teamIds"]]},
             "projectMilestones": {"nodes": [{"id": m["id"], "name": m["name"]} for m in store.milestones
                                             if m["projectId"] == p["id"]]}}
            for p in store.projects if p["name"] == v["name"]]}}
    if "project(" in query:
        nodes = [{"id": i["id"], "title": i["title"], "createdAt": i["createdAt"]}
                 for i in store.issues if i["projectId"] == v["id"]]
        start = int(v.get("after") or 0)
        more = start + 2 < len(nodes)
        return {"project": {"issues": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                                       "nodes": nodes[start:start + 2]}}}
    if "issue(" in query:
        nodes = [{"body": c["body"]} for c in store.comments if c["issueId"] == v["id"]]
        start = int(v.get("after") or 0)
        more = start + 2 < len(nodes)
        return {"issue": {"comments": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                                       "nodes": nodes[start:start + 2]}}}
    raise AssertionError("unknown query " + query)


class Linear(http.server.BaseHTTPRequestHandler):
    store = None
    auths = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        Linear.auths.append(self.headers.get("Authorization"))
        try:
            payload = {"data": answer(Linear.store, body)}
        except AssertionError as error:
            payload = {"errors": [{"message": str(error)}]}
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
    record = {"direction": "github-to-linear", "source": "acme/site project 7", "target": "WEB",
              "access": {"kind": "key", "key_env": "MY_LINEAR_KEY", "kept": "op://Private/Linear/credential"}}
    record.update(change)
    path = os.path.join(tmp, "plan.json")
    with open(path, "w") as handle:
        json.dump(record, handle)
    return path


def run(env, *extra, plan=None):
    args = [sys.executable, SCRIPT, "copy", "--repo", "acme/site", "--project", "7", "--team", "WEB",
            "--key-env", "MY_LINEAR_KEY", "--plan", plan] + list(extra)
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


def by_title(store, title):
    return [i for i in store.issues if i["title"] == title]


def comments_on(store, issue):
    return [c["body"] for c in store.comments if c["issueId"] == issue["id"]]


# --- Scenario 1: the GitHub project becomes one Linear project with the same name, each milestone inside it.

Linear.store = store = Store()
env, tmp = fake_gh(world_for(ISSUES))
plan = save_plan(tmp)
code, out, err = run(env, plan=plan)
check("copy runs", code == 0, out + err)
check("one Linear project is made", len(store.projects) == 1, store.projects)
check("the project has the GitHub project's name", store.projects and store.projects[0]["name"] == "Website relaunch",
      store.projects)
check("the project is on the team", store.projects and store.projects[0]["teamIds"] == ["team-web"], store.projects)
names = [m["name"] for m in sorted(store.milestones, key=lambda m: m["sortOrder"])]
check("each GitHub milestone with open issues becomes a milestone inside it, in build order",
      names == ["1. Build", "2. Launch"], names)
check("every milestone is inside the project",
      all(m["projectId"] == store.projects[0]["id"] for m in store.milestones), store.milestones)
check("a closed issue's milestone is not made", "3. Retire" not in names, names)
check("no initiative is made", not any("nitiative" in w for w in store.writes), store.writes)

# --- Scenario 2: each issue in the project, and in its milestone where it has one.

milestone_id = {m["name"]: m["id"] for m in store.milestones}
check("five open issues of the repository are copied, the closed one and the other repository's are not",
      sorted(i["title"] for i in store.issues) == sorted(
          ["Ship the launch page", "Build the header", "Write the copy", "Fix footer", "Fix footer"]),
      [i["title"] for i in store.issues])
check("every copy is in the project", all(i["projectId"] == store.projects[0]["id"] for i in store.issues))
launch = by_title(store, "Ship the launch page")[0]
check("an issue lands in the milestone its GitHub milestone maps to",
      launch.get("projectMilestoneId") == milestone_id.get("2. Launch"), launch)
check("so does an issue in another milestone",
      by_title(store, "Build the header")[0].get("projectMilestoneId") == milestone_id.get("1. Build"))
loose = by_title(store, "Write the copy")[0]
check("an issue with no milestone is in the project with no milestone", "projectMilestoneId" not in loose, loose)

# --- Scenario 3: same title, body, labels and every comment; each comment names its GitHub author and time in Eastern.

check("the title and body are the same", launch["description"] == "Body of 1.", launch)
check("an existing team label is used, not made again", launch.get("labelIds") == ["lb-feature"], launch)
header = by_title(store, "Build the header")[0]
check("a workspace label matches whatever its case", "lb-bug" in header.get("labelIds", []), header)
footers = by_title(store, "Fix footer")
check("two issues with the same title are both copied, each with its own body",
      sorted(f["description"] for f in footers) == ["A second issue with the same title.", "Body of 5."], footers)
said = comments_on(store, launch)
check("every comment is copied, across pages", len(said) == 3, said)
check("a comment starts with its GitHub author and its time in Eastern (EST)",
      said and said[0] == "Written on GitHub by octocat, November 3, 2026, 1:27 PM Eastern.\n\nFirst thought.", said)
check("a summer time is in Eastern daylight time",
      len(said) > 1 and said[1].startswith("Written on GitHub by hubot, July 3, 2026, 11:05 PM Eastern."), said)
check("a comment by a deleted account still says it came from GitHub",
      len(said) > 2 and said[2].startswith("Written on GitHub by a deleted GitHub account, January 15, 2026, 7:00 AM"),
      said)
check("the original text follows the first line", said and said[0].endswith("\n\nFirst thought."), said)

# --- Scenario 4: needs-decision or parked lands as Needs Human.

check("an issue labelled needs-decision is Needs Human", header.get("stateId") == "st-human", header)
check("an issue labelled parked is Needs Human", loose.get("stateId") == "st-human", loose)
check("an issue with neither keeps the team's own first status", "stateId" not in launch, launch)
check("needs-decision and parked become the status, not a label",
      not any(l["name"].lower() in ("needs-decision", "parked") for l in store.team_labels), store.team_labels)

# The key is never shown, and goes only to Linear in its header.
check("the key never appears in what copy prints", KEY not in out and KEY not in err)
check("the key went to Linear on every request", Linear.auths and all(a == KEY for a in Linear.auths))
gh_calls = [json.loads(line) for line in open(env["FAKE_GH_LOG"])]
check("copy only reads GitHub", all(c[:2] == ["api", "graphql"] for c in gh_calls)
      and not any(a.startswith("query=mutation") for c in gh_calls for a in c), gh_calls)
check("copy says it wrote nothing to GitHub", "Nothing was written to GitHub" in out, out)

# --- Scenario 5: run twice, nothing is copied twice.

before = (len(store.projects), len(store.milestones), len(store.issues), len(store.comments), len(store.team_labels))
code, out, err = run(env, plan=plan)
after = (len(store.projects), len(store.milestones), len(store.issues), len(store.comments), len(store.team_labels))
check("a second run succeeds", code == 0, out + err)
check("a second run copies nothing twice", before == after, (before, after))
check("a second run says the issues were already there", "Already in Linear, so not made again: 5 issues" in out, out)

# A run cut short: the issue landed, one comment did not. The next run adds only that comment.
store.comments = [c for c in store.comments if not c["body"].endswith("Summer note.")]
code, out, err = run(env, plan=plan)
said = comments_on(store, launch)
check("a run after a cut-short one posts only the missing comment",
      code == 0 and len(said) == 3 and sum(1 for s in said if s.endswith("Summer note.")) == 1, said)
check("and makes no issue again", len(store.issues) == 5, len(store.issues))

# A new GitHub issue with a title already copied lands as a second copy, the rest stay as they are.
more = ISSUES + [gh_issue(10, "Fix footer", None, body="A third footer.")]
env2, _ = fake_gh(world_for(more))
code, out, err = run(env2, plan=plan)
check("a new issue whose title is already used is still copied once",
      code == 0 and len(by_title(store, "Fix footer")) == 3 and len(store.issues) == 6, [i["title"] for i in store.issues])

# --- What is copied can be cut to one milestone or to issue numbers.

Linear.store = store = Store()
code, out, err = run(env, "--milestone", "Website relaunch: 1. Build", plan=plan)
check("--milestone copies only that milestone's issues",
      code == 0 and sorted(i["title"] for i in store.issues) == ["Build the header", "Fix footer", "Fix footer"],
      out + err + str([i["title"] for i in store.issues]))
check("--milestone makes only that milestone", [m["name"] for m in store.milestones] == ["1. Build"], store.milestones)
Linear.store = store = Store()
code, out, err = run(env, "--issues", "3", "1", plan=plan)
check("--issues copies only the issues named",
      code == 0 and sorted(i["title"] for i in store.issues) == ["Ship the launch page", "Write the copy"],
      out + err)
Linear.store = store = Store()
code, out, err = run(env, "--issues", "4", plan=plan)
check("--issues refuses a closed issue and writes nothing", code != 0 and not store.writes, out + err)
code, out, err = run(env, "--issues", "9", plan=plan)
check("--issues refuses another repository's issue and writes nothing", code != 0 and not store.writes, out + err)

# --- Nothing is written without the person's yes to this copy.

Linear.store = store = Store()
for name, plan_path in (
        ("no saved plan", os.path.join(tmp, "missing.json")),
        ("a plan for Linear to GitHub", save_plan(tmp, direction="linear-to-github")),
        ("a plan for another team", save_plan(tmp, target="OPS")),
        ("a plan through the connector", save_plan(tmp, access={"kind": "connector"})),
        ("a plan reading another variable", save_plan(tmp, access={"kind": "key", "key_env": "OTHER", "kept": "x"}))):
    code, out, err = run(env, plan=plan_path)
    check("copy refuses {} and writes nothing".format(name), code != 0 and not store.writes, out + err)
check("no refused run reached Linear's write calls", not store.writes, store.writes)

# A GitHub issue that cannot be read stops the copy before anything is written.
broken = world_for(ISSUES)
broken["broken"] = ["5"]
env3, tmp3 = fake_gh(broken)
code, out, err = run(env3, plan=save_plan(tmp3))
check("an unreadable GitHub issue stops the copy before any write", code != 0 and not store.writes, out + err)

# A team with no Needs Human status stops the copy before anything is written.
Linear.store = store = Store(needs_human=False)
code, out, err = run(env, plan=save_plan(tmp))
check("a team with no Needs Human status is refused before any write",
      code != 0 and not store.writes and "Needs Human" in err, out + err)

# --- The skill says how to run the copy, by key and by connector.

text = open(SKILL).read() if os.path.exists(SKILL) else ""


def says(phrase):
    check("SKILL.md says: " + phrase, phrase in text)


says("migrate.py copy --repo <owner>/<repo> --project <number> --team <KEY> --key-env")
says("Written on GitHub by")
says("Needs Human")
says("save_issue")
says("save_comment")
says("nothing is copied twice")
check("SKILL.md no longer says the copy is not built", "is not built yet" not in text)

for path in sorted(os.listdir(SKILL_DIR)):
    body = open(os.path.join(SKILL_DIR, path)).read()
    for word in ("initiative", "layout"):
        check("{} holds no layout choice ({})".format(path, word), word not in body.lower())

server.shutdown()
print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
