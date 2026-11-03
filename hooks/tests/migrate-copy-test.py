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
if args[:2] == ["issue", "close"]:
    world = json.load(open(os.environ["FAKE_GH_WORLD"]))
    if args[2] in world.get("close_refused", []):
        sys.exit(1)
    for node in world["project"]["items"]["nodes"]:
        if node["content"].get("number") == int(args[2]):
            node["content"]["state"] = "CLOSED"
    world["issues"][args[2]]["state"] = "CLOSED"
    json.dump(world, open(os.environ["FAKE_GH_WORLD"], "w"))
    sys.exit(0)
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


def link(item):
    """Another GitHub issue as a link names it: a number in acme/site, or (repository, number)."""
    repo, number = item if isinstance(item, tuple) else ("acme/site", item)
    return {"number": number, "repository": {"nameWithOwner": repo}}


def links(items, more=False):
    return {"pageInfo": {"hasNextPage": more}, "nodes": [link(i) for i in items]}


def gh_issue(number, title, milestone, labels=(), comments=(), state="OPEN", repo="acme/site", body=None,
             parent=None, subs=(), blocked_by=(), blocking=(), more_links=False):
    return {"number": number, "title": title, "body": body if body is not None else "Body of {}.".format(number),
            "state": state, "repository": repo, "milestone": {"title": milestone} if milestone else None,
            "labels": {"nodes": [{"name": n} for n in labels]}, "all_comments": list(comments),
            "parent": link(parent) if parent else None, "subIssues": links(subs, more_links),
            "blockedBy": links(blocked_by), "blocking": links(blocking)}


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
                          "title": i["title"], "body": i["body"],
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
        self.relations = []
        self.writes = []

    def next(self, prefix):
        self.n += 1
        return "{}-{}".format(prefix, self.n)


def answer(store, body):
    query, v = body["query"], body.get("variables") or {}
    if query.lstrip().startswith("mutation"):
        store.writes.append(query.split("{", 2)[1].split("(")[0].strip())
        data = v["input"]
        if "issueUpdate" in query:
            found = [i for i in store.issues if i["id"] == v["id"]]
            found[0].update(data)
            return {"issueUpdate": {"success": True, "issue": {"id": v["id"]}}}
        if "issueRelationCreate" in query:
            r = dict(data, id=store.next("rel"))
            store.relations.append(r)
            return {"issueRelationCreate": {"success": True, "issueRelation": {"id": r["id"]}}}
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
             "projectMilestones": {"nodes": [{"id": m["id"], "name": m["name"], "sortOrder": m["sortOrder"]}
                                             for m in store.milestones
                                             if m["projectId"] == p["id"]]}}
            for p in store.projects if p["name"] == v["name"]]}}
    if "description:{contains:$mark}" in query or "description:{containsIgnoreCase:$mark}" in query:
        fold = (lambda s: s.lower()) if "IgnoreCase" in query else (lambda s: s)
        nodes = [{"id": i["id"], "description": i["description"], "createdAt": i["createdAt"],
                  "project": {"id": i["projectId"]} if i.get("projectId") else None}
                 for i in store.issues if i["teamId"] == v["team"] and fold(v["mark"]) in fold(i["description"])]
        start = int(v.get("after") or 0)
        more = start + 2 < len(nodes)
        return {"issues": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                           "nodes": nodes[start:start + 2]}}
    if "project(id:$id){ id name" in query:
        found = [p for p in store.projects if p["id"] == v["id"]]
        return {"project": {"id": found[0]["id"], "name": found[0]["name"],
                            "teams": {"nodes": [{"id": t} for t in found[0]["teamIds"]]},
                            "projectMilestones": {"nodes": [
                                {"id": m["id"], "name": m["name"], "sortOrder": m["sortOrder"]}
                                for m in store.milestones if m["projectId"] == found[0]["id"]]}} if found else None}
    if "project(" in query:
        nodes = [{"id": i["id"], "title": i["title"], "description": i["description"], "createdAt": i["createdAt"],
                  "projectMilestone": {"id": i["projectMilestoneId"]} if i.get("projectMilestoneId") else None}
                 for i in store.issues if i["projectId"] == v["id"]]
        start = int(v.get("after") or 0)
        more = start + 2 < len(nodes)
        return {"project": {"issues": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                                       "nodes": nodes[start:start + 2]}}}
    if "issue(" in query and "title description" in query:
        found = [i for i in store.issues if i["id"] == v["id"]]
        return {"issue": {"title": found[0]["title"], "description": found[0]["description"]} if found else None}
    if "issue(" in query and "parent{" in query:
        found = [i for i in store.issues if i["id"] == v["id"]]
        parent = found[0].get("parentId") if found else None
        return {"issue": {"parent": {"id": parent} if parent else None}}
    if "issue(" in query and "relations(" in query:
        nodes = [{"type": r["type"], "relatedIssue": {"id": r["relatedIssueId"]}}
                 for r in store.relations if r["issueId"] == v["id"]]
        start = int(v.get("after") or 0)
        more = start + 2 < len(nodes)
        return {"issue": {"relations": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
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


def body(issue):
    """A copy's body without the hidden line naming its GitHub issue."""
    return issue["description"].split("\n\n<!-- copied from GitHub")[0]


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

check("the title and body are the same", body(launch) == "Body of 1.", launch)
check("an existing team label is used, not made again", launch.get("labelIds") == ["lb-feature"], launch)
header = by_title(store, "Build the header")[0]
check("a workspace label matches whatever its case", "lb-bug" in header.get("labelIds", []), header)
footers = by_title(store, "Fix footer")
check("two issues with the same title are both copied, each with its own body",
      sorted(body(f) for f in footers) == ["A second issue with the same title.", "Body of 5."], footers)
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

# Two issues with one title, copied one milestone at a time: each gets its own copy in its own milestone.
SAME_TITLE = [
    gh_issue(11, "Add tests", "Website relaunch: 1. Build", labels=["Feature"], body="Tests for the build."),
    gh_issue(12, "Add tests", "Website relaunch: 2. Launch", labels=["bug"], body="Tests for the launch.",
             comments=[comment("octocat", "2026-11-03T18:27:00Z", "Launch tests note.")]),
    gh_issue(13, "Add tests", None, body="Tests with no milestone."),
]
Linear.store = store = Store()
env4, _ = fake_gh(world_for(SAME_TITLE))
run(env4, "--milestone", "Website relaunch: 1. Build", plan=plan)
code, out, err = run(env4, "--milestone", "Website relaunch: 2. Launch", plan=plan)
milestone_id = {m["name"]: m["id"] for m in store.milestones}
launch_copy = [i for i in store.issues if body(i) == "Tests for the launch."]
check("a same-titled issue in another milestone, copied in a later run, gets its own copy",
      code == 0 and len(launch_copy) == 1, out + err + str([i["description"] for i in store.issues]))
check("that copy is in its own milestone, with its own labels and comment",
      launch_copy and launch_copy[0].get("projectMilestoneId") == milestone_id.get("2. Launch")
      and launch_copy[0].get("labelIds") == ["lb-bug"]
      and [c.endswith("Launch tests note.") for c in comments_on(store, launch_copy[0])] == [True], launch_copy)
build_copy = [i for i in store.issues if body(i) == "Tests for the build."]
check("the earlier copy gets no comment of the later issue",
      build_copy and comments_on(store, build_copy[0]) == [], [comments_on(store, b) for b in build_copy])
code, out, err = run(env4, "--issues", "13", plan=plan)
loose_copy = [i for i in store.issues if body(i) == "Tests with no milestone."]
check("a same-titled issue with no milestone, copied in a later run, lands with no milestone",
      code == 0 and len(loose_copy) == 1 and "projectMilestoneId" not in loose_copy[0], out + err)

# An issue with a title already copied is reopened between two runs: each GitHub issue still has exactly one copy.
FOOTERS = [gh_issue(3, "Fix footer", None, body="Footer three.", state="CLOSED",
                    comments=[comment("octocat", "2026-11-03T18:00:00Z", "Three's note.")]),
           gh_issue(5, "Fix footer", None, body="Footer five.",
                    comments=[comment("octocat", "2026-11-03T18:05:00Z", "Five's note.")]),
           gh_issue(6, "Fix footer", None, body="Footer six.",
                    comments=[comment("octocat", "2026-11-03T18:06:00Z", "Six's note.")])]
Linear.store = store = Store()
env5, _ = fake_gh(world_for(FOOTERS))
run(env5, plan=plan)
reopened = [dict(i, state="OPEN") if i["number"] == 3 else i for i in FOOTERS]
env6, _ = fake_gh(world_for(reopened))
code, out, err = run(env6, plan=plan)
bodies = sorted(body(i) for i in store.issues)
check("after a reopen, each same-titled issue has exactly one copy",
      code == 0 and bodies == ["Footer five.", "Footer six.", "Footer three."], out + err + str(bodies))
check("after a reopen, each copy holds only its own issue's comment",
      all([c.split("\n\n", 1)[1] for c in comments_on(store, i)] ==
          ["{}'s note.".format(body(i).split()[1].rstrip(".").capitalize())] for i in store.issues),
      [(i["description"], comments_on(store, i)) for i in store.issues])

# Two comments by one person, with the same text, in the same minute: both are copied, once each, run after run.
DOUBLE = [gh_issue(21, "Vote", None, comments=[comment("carol", "2026-11-03T15:00:05Z", "+1"),
                                               comment("carol", "2026-11-03T15:00:40Z", "+1")])]
Linear.store = store = Store()
env7, _ = fake_gh(world_for(DOUBLE))
code, out, err = run(env7, plan=plan)
vote = by_title(store, "Vote")
check("two same-minute comments with the same text are both copied",
      code == 0 and vote and len(comments_on(store, vote[0])) == 2, out + err + str(store.comments))
run(env7, plan=plan)
check("and a second run adds neither again", vote and len(comments_on(store, vote[0])) == 2, store.comments)

# A cut run makes a later milestone first; the full run after it still leaves the milestones in build order.
STAGES = [gh_issue(31, "Build it", "Website relaunch: 1. Build"), gh_issue(32, "Test it", "Website relaunch: 2. Test"),
          gh_issue(33, "Deploy it", "Website relaunch: 3. Deploy")]
Linear.store = store = Store()
env8, _ = fake_gh(world_for(STAGES))
run(env8, "--milestone", "Website relaunch: 3. Deploy", plan=plan)
code, out, err = run(env8, plan=plan)
order = [m["name"] for m in sorted(store.milestones, key=lambda m: m["sortOrder"])]
check("milestones made across a cut run and a full run stay in build order",
      code == 0 and order == ["1. Build", "2. Test", "3. Deploy"], [(m["name"], m["sortOrder"]) for m in store.milestones])

# Milestones with no number, made across runs while others empty out, still sort by name.
NAMED = [gh_issue(41, "a", "Alpha"), gh_issue(42, "b", "Ant"), gh_issue(43, "c", "Beta"), gh_issue(44, "d", "Gamma")]
Linear.store = store = Store()
env9, _ = fake_gh(world_for(NAMED))
run(env9, "--milestone", "Beta", plan=plan)
emptied = [dict(i, state="CLOSED") if i["number"] in (41, 42) else i for i in NAMED]
env10, _ = fake_gh(world_for(emptied))
code, out, err = run(env10, plan=plan)
orders = {m["name"]: m["sortOrder"] for m in store.milestones}
check("unnumbered milestones made across runs, as others empty, sort by name with no tie",
      code == 0 and orders.get("Beta", 0) < orders.get("Gamma", 0), (out + err, orders))
emptied = [dict(i, state="CLOSED") if i["number"] == 41 else i for i in NAMED]
Linear.store = store = Store()
env11, _ = fake_gh(world_for([i for i in NAMED if i["number"] != 43]))
run(env11, "--milestone", "Gamma", plan=plan)
env12, _ = fake_gh(world_for(emptied))
run(env12, plan=plan)
orders = [m["name"] for m in sorted(store.milestones, key=lambda m: m["sortOrder"])]
check("and a milestone made later between two others lands between them",
      orders == ["Ant", "Beta", "Gamma"] and len({m["sortOrder"] for m in store.milestones}) == 3,
      [(m["name"], m["sortOrder"]) for m in store.milestones])

# A GitHub body edited between two runs: the rerun still finds the copy and makes nothing twice.
LOGIN = [gh_issue(51, "Fix login", "Website relaunch: 1. Build", body="Login fails.",
                  comments=[comment("octocat", "2026-11-03T18:00:00Z", "Seen it.")])]
Linear.store = store = Store()
env13, _ = fake_gh(world_for(LOGIN))
run(env13, plan=plan)
env14, _ = fake_gh(world_for([dict(LOGIN[0], body="Login fails on Safari.")]))
code, out, err = run(env14, plan=plan)
check("a rerun after the GitHub body was edited makes no second copy",
      code == 0 and len(by_title(store, "Fix login")) == 1 and len(store.comments) == 1, out + err)

# Same, among same-titled issues: the edited one finds its own copy, never another issue's.
PAIR = [gh_issue(5, "Fix footer", None, body="Footer five.",
                 comments=[comment("octocat", "2026-11-03T18:05:00Z", "Five's note.")]),
        gh_issue(6, "Fix footer", None, body="Footer six.",
                 comments=[comment("octocat", "2026-11-03T18:06:00Z", "Six's note.")])]
Linear.store = store = Store()
env15, _ = fake_gh(world_for(PAIR))
run(env15, plan=plan)
env16, _ = fake_gh(world_for([PAIR[0], dict(PAIR[1], body="Footer six, edited.")]))
code, out, err = run(env16, "--issues", "6", plan=plan)
check("an edited same-titled issue finds its own copy and posts nothing on the other's",
      code == 0 and len(store.issues) == 2 and len(store.comments) == 2,
      out + err + str([(i["description"], comments_on(store, i)) for i in store.issues]))

# Each copy carries its GitHub issue number in a hidden line, and a rerun finds copies only by it
# (Robert, November 3: "yeah I think putting the issue number is really simple, that's fine").
Linear.store = store = Store()
env17, _ = fake_gh(world_for(LOGIN))
run(env17, plan=plan)
login = by_title(store, "Fix login")
check("a copy's body ends with a hidden line naming its GitHub issue",
      login and login[0]["description"] == "Login fails.\n\n<!-- copied from GitHub acme/site#51 -->",
      login and login[0]["description"])

# The round-2 cases: same-titled issues edited or closed between runs keep their own copies and comments.
Linear.store = store = Store()
env18, _ = fake_gh(world_for(PAIR))
run(env18, "--issues", "5", plan=plan)
env19, _ = fake_gh(world_for([dict(PAIR[0], body="Footer five, edited."), PAIR[1]]))
code, out, err = run(env19, "--issues", "6", plan=plan)
six = [i for i in store.issues if "acme/site#6 " in i["description"]]
five = [i for i in store.issues if "acme/site#5 " in i["description"]]
check("an issue copied after its same-titled neighbor was edited gets its own copy",
      code == 0 and len(six) == 1 and len(five) == 1, out + err + str([i["description"] for i in store.issues]))
check("and its comment is on its own copy only",
      five and six and [c.split("\n\n", 1)[1] for c in comments_on(store, five[0])] == ["Five's note."]
      and [c.split("\n\n", 1)[1] for c in comments_on(store, six[0])] == ["Six's note."],
      [(i["description"], comments_on(store, i)) for i in store.issues])
Linear.store = store = Store()
env20, _ = fake_gh(world_for(PAIR))
run(env20, plan=plan)
env21, _ = fake_gh(world_for([dict(PAIR[0], state="CLOSED"), dict(PAIR[1], body="Footer six, edited.")]))
code, out, err = run(env21, plan=plan)
check("closing one same-titled issue and editing the other leaves each copy and comment where it was",
      code == 0 and len(store.issues) == 2 and len(store.comments) == 2
      and all(len(comments_on(store, i)) == 1 for i in store.issues),
      [(i["description"], comments_on(store, i)) for i in store.issues])

# A copy whose hidden line is gone is not matched: the issue is imported a second time
# (Robert, November 3: "if the issue number is not there just import a second time").
Linear.store = store = Store()
env22, _ = fake_gh(world_for(LOGIN))
run(env22, plan=plan)
for i in store.issues:
    i["description"] = "Login fails."
code, out, err = run(env22, plan=plan)
check("a copy without its hidden line is imported a second time", code == 0 and len(store.issues) == 2, out + err)

# The Linear project renamed, or a copy moved to another project, after a first run: a rerun still
# finds every copy by its hidden line and makes nothing twice.
Linear.store = store = Store()
env23, _ = fake_gh(world_for(LOGIN))
run(env23, plan=plan)
store.projects[0]["name"] = "Relaunch, renamed in Linear"
code, out, err = run(env23, plan=plan)
check("a rerun after the Linear project was renamed makes no second project or copy",
      code == 0 and len(store.projects) == 1 and len(store.issues) == 1 and len(store.comments) == 1, out + err)
more_login = LOGIN + [gh_issue(52, "Fix logout", "Website relaunch: 1. Build", body="Logout fails.")]
env24, _ = fake_gh(world_for(more_login))
code, out, err = run(env24, plan=plan)
check("a new issue after the rename lands in the renamed project",
      code == 0 and len(store.projects) == 1 and len(store.issues) == 2
      and all(i["projectId"] == store.projects[0]["id"] for i in store.issues), out + err)
Linear.store = store = Store()
run(env23, plan=plan)
store.projects.append({"id": "pr-elsewhere", "name": "Elsewhere", "teamIds": ["team-web"]})
store.issues[0]["projectId"] = "pr-elsewhere"
code, out, err = run(env23, plan=plan)
check("a rerun after a copy was moved to another project does not copy it again",
      code == 0 and len(store.issues) == 1 and len(store.comments) == 1, out + err)

# A GitHub body quoting another issue's hidden line can never take over that issue's copy,
# even after its own real line is removed in Linear.
FORGED = [gh_issue(5, "Real five", None, body="Five.", comments=[comment("alice", "2026-11-03T18:00:00Z", "Alice.")]),
          gh_issue(7, "Sneaky", None, body="Hello.\n\n<!-- copied from GitHub acme/site#5 -->")]
Linear.store = store = Store()
env25, _ = fake_gh(world_for(FORGED))
run(env25, "--issues", "7", plan=plan)
sneaky = by_title(store, "Sneaky")
for i in sneaky:
    i["description"] = i["description"].rsplit("\n\n<!-- copied from GitHub acme/site#7 -->", 1)[0]
code, out, err = run(env25, plan=plan)
five_copy = by_title(store, "Real five")
check("an issue whose hidden line another body quoted still gets its own copy",
      code == 0 and len(five_copy) == 1, out + err + str([i["description"] for i in store.issues]))
check("and its comment lands on its own copy, never on the quoting issue's",
      five_copy and [c.split("\n\n", 1)[1] for c in comments_on(store, five_copy[0])] == ["Alice."]
      and all(comments_on(store, s) == [] for s in by_title(store, "Sneaky")),
      [(i["title"], comments_on(store, i)) for i in store.issues])

# --- MAST-16: parent, sub-issue and blocked-by links between the copies hold as on GitHub
# (Project description, Rule 3: "A wait on another issue is Linear's blocked-by link, not a status").

LINKED = [
    gh_issue(60, "Old prerequisite", None, state="CLOSED", blocking=[64]),
    gh_issue(61, "Parent work", None, subs=[62]),
    gh_issue(62, "Child work", None, parent=61, blocking=[63]),
    gh_issue(63, "Waits on child", None, blocked_by=[62]),
    gh_issue(64, "Waits on closed", None, blocked_by=[60]),
    gh_issue(65, "Split from apps", None, parent=("acme/apps", 9)),
]


def copy_of(store, number):
    found = [i for i in store.issues if "acme/site#{} ".format(number) in i["description"]]
    return found[0] if found else {}


def blocks_between(store, blocker, blocked):
    return sum(1 for r in store.relations if r["type"] == "blocks"
               and r["issueId"] == copy_of(store, blocker).get("id")
               and r["relatedIssueId"] == copy_of(store, blocked).get("id"))


Linear.store = store = Store()
env_links, _ = fake_gh(world_for(LINKED))
code, out, err = run(env_links, plan=plan)
check("a copy of linked issues runs", code == 0, out + err)
check("a sub-issue's copy has its parent's copy as its parent",
      copy_of(store, 62).get("parentId") == copy_of(store, 61).get("id") is not None,
      [(i["title"], i.get("parentId")) for i in store.issues])
check("a blocked-by link holds between the copies, the blocker blocking the one that waits",
      blocks_between(store, 62, 63) == 1, store.relations)
check("only that one blocked-by link is made, never the other way round",
      len(store.relations) == 1 and blocks_between(store, 63, 62) == 0, store.relations)
check("a copy with no GitHub parent gets none",
      all("parentId" not in copy_of(store, n) for n in (61, 63, 64, 65)), [(i["title"], i.get("parentId")) for i in store.issues])
check("a link to a closed issue that was not copied is named in what copy prints", "#60 blocks #64" in out, out)
check("a link to another repository's issue is named in what copy prints",
      "#65 is a sub-issue of acme/apps#9" in out, out)
check("copy counts the links it made", "Links made now: 1 parent link, 1 blocked-by link." in out, out)
writes = len(store.writes)
code, out, err = run(env_links, plan=plan)
check("a second run makes no link twice",
      code == 0 and store.writes[writes:] == [] and len(store.relations) == 1
      and "Links made now: 0 parent links, 0 blocked-by links." in out, out + err + str(store.writes[writes:]))

# Copied one part at a time: the link is made by the run that copies its second side, from either side.
Linear.store = store = Store()
code, out, err = run(env_links, "--issues", "62", "63", plan=plan)
check("a link whose other side has no copy yet is named, not made",
      code == 0 and "parentId" not in copy_of(store, 62) and "#62 is a sub-issue of #61" in out, out + err)
code, out, err = run(env_links, "--issues", "61", plan=plan)
check("the later run that copies the parent makes the sub-issue link from the parent's side",
      code == 0 and copy_of(store, 62).get("parentId") == copy_of(store, 61).get("id"), out + err)
Linear.store = store = Store()
run(env_links, "--issues", "63", plan=plan)
code, out, err = run(env_links, "--issues", "62", plan=plan)
check("the later run that copies the blocker makes the blocked-by link from the blocker's side",
      code == 0 and blocks_between(store, 62, 63) == 1 and len(store.relations) == 1, out + err + str(store.relations))

# A copy given another parent in Linear after the move is left as it is, and copy says so.
Linear.store = store = Store()
run(env_links, plan=plan)
copy_of(store, 62)["parentId"] = "is-elsewhere"
code, out, err = run(env_links, plan=plan)
check("a copy already under another parent in Linear is left there, and copy says so",
      code == 0 and copy_of(store, 62)["parentId"] == "is-elsewhere" and "already has another parent in Linear" in out,
      out + err)

# Two repositories copied to one team: a link between their issues holds too, made by whichever run
# copies its second side (review finding F1).
TWO_REPOS = [gh_issue(9, "Apps parent", None, repo="acme/apps", subs=[("acme/site", 65)]),
             gh_issue(8, "Apps blocker", None, repo="acme/apps", blocking=[("acme/site", 66)]),
             gh_issue(65, "Split from apps", None, parent=("acme/apps", 9)),
             gh_issue(66, "Waits on apps", None, blocked_by=[("Acme/Apps", 8)])]


def copy_in(store, repo, number):
    found = [i for i in store.issues if "{}#{} ".format(repo, number).lower() in i["description"].lower()]
    return found[0] if found else {}


def run_repo(env, repo, *extra):
    args = [sys.executable, SCRIPT, "copy", "--repo", repo, "--project", "7", "--team", "WEB",
            "--key-env", "MY_LINEAR_KEY", "--plan", save_plan(tmp, source="{} project 7".format(repo))] + list(extra)
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


env_two, _ = fake_gh(world_for(TWO_REPOS))
# The second order types the other repository as Acme/Apps, so its copies' hidden lines differ in case
# from the name GitHub's links give.
for first, second in (("acme/site", "acme/apps"), ("Acme/Apps", "acme/site")):
    Linear.store = store = Store()
    run_repo(env_two, first)
    code, out, err = run_repo(env_two, second)
    sub, parent = copy_in(store, "acme/site", 65), copy_in(store, "acme/apps", 9)
    blocker, waits = copy_in(store, "acme/apps", 8), copy_in(store, "acme/site", 66)
    check("copied {} then {}, a sub-issue's copy has its parent's copy from the other repository".format(first, second),
          code == 0 and parent.get("id") and sub.get("parentId") == parent.get("id"), out + err)
    check("copied {} then {}, a blocked-by link across the two repositories holds".format(first, second),
          code == 0 and any(r["issueId"] == blocker.get("id") and r["relatedIssueId"] == waits.get("id")
                            and r["type"] == "blocks" for r in store.relations) and len(store.relations) == 1,
          out + err + str(store.relations))
    check("copied {} then {}, no link across the repositories is named as not made".format(first, second),
          "Links not made" not in out, out)

# A repository typed in another case on a later run still finds its own copies: nothing is copied or
# linked twice, and no copy is taken for another parent (review finding R1).
writes = len(store.writes)
code, out, err = run_repo(env_two, "acme/apps")
check("a rerun typing the repository in another case copies and links nothing twice",
      code == 0 and store.writes[writes:] == [] and len(store.issues) == 4 and len(store.relations) == 1
      and "Left as it is" not in out, out + err + str(store.writes[writes:]))
CASED = [gh_issue(81, "Blocker", None, repo="acme/apps", blocking=[("acme/apps", 82)]),
         gh_issue(82, "Waits", None, repo="acme/apps", blocked_by=[("acme/apps", 81)])]
Linear.store = store = Store()
env_cased, _ = fake_gh(world_for(CASED))
run_repo(env_cased, "Acme/Apps", "--issues", "81")
code, out, err = run_repo(env_cased, "acme/apps", "--issues", "82")
check("a link inside one repository is made when its two sides were copied with the name typed in two cases",
      code == 0 and len(store.issues) == 2 and len(store.relations) == 1 and "Links not made" not in out,
      out + err + str(store.relations))

# More links than one page holds: the copy stops before writing, never drops a link without a word.
Linear.store = store = Store()
env_crowded, _ = fake_gh(world_for([gh_issue(70, "Big parent", None, subs=[71], more_links=True),
                                    gh_issue(71, "One child", None, parent=70)]))
code, out, err = run(env_crowded, plan=plan)
check("an issue with more links than one read holds stops the copy before any write",
      code != 0 and not store.writes, out + err)

# The copy refuses a repository or project other than the one in the plan (Robert, November 3: "yes").
Linear.store = store = Store()
for name, extra in (("another repository", ["--repo", "acme/apps"]), ("another project", ["--project", "8"])):
    args = [sys.executable, SCRIPT, "copy", "--repo", "acme/site", "--project", "7", "--team", "WEB",
            "--key-env", "MY_LINEAR_KEY", "--plan", save_plan(tmp)]
    where = args.index(extra[0])
    args[where + 1] = extra[1]
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    check("copy refuses {} than the plan names, before any read or write".format(name),
          result.returncode != 0 and not store.writes and "plan" in result.stderr, result.stdout + result.stderr)
code, out, err = run(env, plan=save_plan(tmp, source="acme/site"))
check("copy refuses a plan whose source names no project", code != 0 and not store.writes, out + err)
code, out, err = run(env, plan=save_plan(tmp, source="github:acme/site#7", target="linear:WEB"))
check("copy reads a plan written as github:<owner>/<repo>#<project> and linear:<TEAM>", code == 0, out + err)

# The copy needs a key: a plan through the connector is refused and says so (Robert, November 3:
# "don't use a connector for this, require a key").
code, out, err = run(env, plan=save_plan(tmp, access={"kind": "connector"}))
check("a connector plan is refused for the copy, saying a key is needed",
      code != 0 and "API key" in err, out + err)
plan = save_plan(tmp)

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

# --- MAST-17: when the migration finishes, each migrated GitHub issue is closed as not planned, nothing is
# deleted, and nothing ties it to its Linear copy; the check counts issues and comments on both sides and
# lists every image.

def finish(env, *extra, plan=None):
    args = [sys.executable, SCRIPT, "finish", "--repo", "acme/site", "--project", "7", "--team", "WEB",
            "--key-env", "MY_LINEAR_KEY", "--plan", plan] + list(extra)
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


def gh_log(env):
    return [json.loads(line) for line in open(env["FAKE_GH_LOG"])] if os.path.exists(env["FAKE_GH_LOG"]) else []


def closes(env):
    return [c for c in gh_log(env) if c[:2] != ["api", "graphql"]]


def closed_numbers(env):
    return sorted(int(c[2]) for c in closes(env))


WITH_IMAGES = [dict(i) for i in ISSUES]
WITH_IMAGES[4] = gh_issue(5, "Fix footer", "Website relaunch: 1. Build",
                          body="See ![the footer](https://github.com/user-attachments/assets/foot.png) here.",
                          comments=[comment("octocat", "2026-11-03T18:27:00Z",
                                            'Also <img width="200" src="https://example.com/after.png">.')])
# GitHub's own rendering of that text, which is what finish reads the images from.
WITH_IMAGES[4]["bodyHTML"] = ('<p>See <a href="https://github.com/user-attachments/assets/foot.png"><img '
                              'src="https://github.com/user-attachments/assets/foot.png" alt="the footer"></a> here.</p>')
WITH_IMAGES[4]["all_comments"][0]["bodyHTML"] = (
    '<p>Also <img width="200" src="https://camo.githubusercontent.com/abc" '
    'data-canonical-src="https://example.com/after.png">.</p>')

# Images written every way GitHub shows them: an address with parentheses, brackets in the alt text, a lazy
# data-src beside the real src, a ">" inside a quoted alt, a reference-style image. GitHub renders each as
# an <img>; an emoji GitHub draws as an image is not an image of the issue.
TRICKY = gh_issue(7, "Pictures", None, body=(
    "![chart](https://upload.wikimedia.org/w/Graph_(2020).png)\n"
    "![shot [1]](https://ex.test/nested.png)\n"
    '<img data-src="https://cdn.ex.test/lazy.png" src="https://cdn.ex.test/real.png">\n'
    '<img alt="a > b" src="https://ex.test/gt.png">\n'
    "![ref][1] :shipit:\n\n[1]: https://ex.test/ref.png"))
TRICKY["bodyHTML"] = (
    '<p><img src="https://camo.githubusercontent.com/1" data-canonical-src="https://upload.wikimedia.org/w/Graph_(2020).png" alt="chart">\n'
    '<img src="https://camo.githubusercontent.com/2" data-canonical-src="https://ex.test/nested.png" alt="shot [1]">\n'
    '<img data-src="https://cdn.ex.test/lazy.png" src="https://camo.githubusercontent.com/3" data-canonical-src="https://cdn.ex.test/real.png">\n'
    '<img alt="a &gt; b" src="https://camo.githubusercontent.com/4" data-canonical-src="https://ex.test/gt.png">\n'
    '<img src="https://camo.githubusercontent.com/5" data-canonical-src="https://ex.test/ref.png" alt="ref"> '
    '<img class="emoji" title=":shipit:" alt=":shipit:" src="https://github.githubassets.com/images/icons/emoji/shipit.png">\n'
    # An upload, as GitHub renders it: a private address signed for five minutes, not the address written.
    '<a href="https://private-user-images.githubusercontent.com/181685648/604055368-25addea2-357a-42c0-a1c8-fba0163382cc.png'
    '?jwt=eyJSIGNED.TOKEN"><img alt="Image" src="https://private-user-images.githubusercontent.com/181685648/'
    '604055368-25addea2-357a-42c0-a1c8-fba0163382cc.png?jwt=eyJSIGNED.TOKEN"></a></p>')

Linear.store = store = Store()
envf, tmpf = fake_gh(world_for(WITH_IMAGES))
planf = save_plan(tmpf)
code, out, err = run(envf, plan=planf)
check("the copy runs before the finish", code == 0, out + err)
open(envf["FAKE_GH_LOG"], "w").close()
writes_before = list(store.writes)
code, out, err = finish(envf, plan=planf)
check("finish runs", code == 0, out + err)
check("each migrated open issue is closed on GitHub", closed_numbers(envf) == [1, 2, 3, 5, 6], closes(envf))
check("each is closed as not planned, with nothing else said",
      all(c == ["issue", "close", c[2], "--repo", "acme/site", "--reason", "not planned"] for c in closes(envf)),
      closes(envf))
check("the closed issue and the other repository's issue are not touched",
      not any(c[2] in ("4", "9") for c in closes(envf)), closes(envf))
everything = json.dumps(gh_log(envf)).lower()
check("nothing on GitHub is deleted", "delete" not in everything and "transfer" not in everything, gh_log(envf))
check("no comment is posted on GitHub", "--comment" not in everything and "addcomment" not in everything
      and not any(a.startswith("query=mutation") for c in gh_log(envf) for a in c), gh_log(envf))
check("no Linear link or key reaches GitHub", "linear" not in everything and "web-" not in everything, gh_log(envf))
check("finish writes nothing to Linear", store.writes == writes_before, store.writes)
check("the issue counts match on both sides", "GitHub: 5 issues, 4 comments." in out
      and "Linear: 5 of them copied, 4 of those comments." in out, out)
check("an image in a body is listed", "#5: https://github.com/user-attachments/assets/foot.png" in out, out)
check("an image in a comment is listed", "#5: https://example.com/after.png" in out, out)
check("finish says nothing was deleted", "Nothing on GitHub was deleted" in out, out)
check("the key never appears in what finish prints", KEY not in out and KEY not in err)

Linear.store = store = Store()
envt, _ = fake_gh(world_for([TRICKY]))
run(envt, plan=planf)
code, out, err = finish(envt, plan=planf)
pictures = [line.strip() for line in out.splitlines() if line.strip().startswith("#7: ")]
check("every image GitHub shows is listed once, by the address it shows",
      sorted(pictures) == sorted("#7: " + url for url in (
          "https://upload.wikimedia.org/w/Graph_(2020).png", "https://ex.test/nested.png",
          "https://cdn.ex.test/real.png", "https://ex.test/gt.png", "https://ex.test/ref.png",
          "https://github.com/user-attachments/assets/25addea2-357a-42c0-a1c8-fba0163382cc")), out)
check("an upload's short-lived signed address is never printed", "jwt" not in out and "SIGNED" not in out, out)
check("an emoji is not listed as an image", "shipit" not in out, out)

code, out, err = finish(envf, plan=planf)
check("a second finish finds nothing left open and closes nothing",
      code == 0 and "No open issue left" in out and not closes(envf)[5:], out + err)

# A copy short a comment, or with no copy at all, stays open and is named.
Linear.store = store = Store()
envf, tmpf = fake_gh(world_for(WITH_IMAGES))
code, out, err = run(envf, "--issues", "1", "5", plan=planf)
store.comments = [c for c in store.comments if not c["body"].endswith("Summer note.")]
open(envf["FAKE_GH_LOG"], "w").close()
code, out, err = finish(envf, plan=planf)
check("finish fails when a copy does not match", code != 0, out + err)
check("only the issue whose copy matches is closed", closed_numbers(envf) == [5], closes(envf))
check("the copy short a comment is named", "#1 has 2 of its 3 comments in Linear" in out, out)
check("an issue with no copy is named", "#2 has no copy on the team" in out, out)
check("the counts show the gap", "GitHub: 5 issues, 4 comments." in out
      and "Linear: 2 of them copied, 3 of those comments." in out, out)

# Closed only when the copy holds the same title and body too, so closing never loses text (Robert,
# November 3, on MAST-17: "yes this is good enough"). Issue 3 has no comments, so only its text can tell.
Linear.store = store = Store()
envx, _ = fake_gh(world_for(WITH_IMAGES))
run(envx, plan=planf)
copy_of = {int(i["description"].rsplit("#", 1)[1].split()[0]): i for i in store.issues}
copy_of[2]["title"] = "Build the header, renamed in Linear"
copy_of[3]["description"] = "Not the GitHub text.\n\n<!-- copied from GitHub acme/site#3 -->"
open(envx["FAKE_GH_LOG"], "w").close()
code, out, err = finish(envx, plan=planf)
check("a copy whose title or body differs keeps its GitHub issue open",
      code != 0 and closed_numbers(envx) == [1, 5, 6], out + err + str(closes(envx)))
check("a copy whose title differs is named", "#2 has another title in Linear" in out, out)
check("a copy whose body differs is named", "#3 has other text in Linear" in out, out)

# A change in symbols alone is a change: "x > 5" and "x < 5" are not the same text. Spacing is not, and
# neither is Linear wrapping a link's address in <>. The way out of a text difference is a hand edit,
# since the copy never rewrites a copy it finds.
SYMBOLS = [gh_issue(21, "Limit is x > 5", None, body="Ship if x > 5. Docs: [here](https://ex.test/a-b)."),
           gh_issue(22, "Second", None, body="Plain.", comments=[comment("octocat", "2026-11-03T18:27:00Z", "Use -5.")]),
           gh_issue(23, "Third", None, body="Plain  text.\n\nSee [docs](https://ex.test/d).")]
Linear.store = store = Store()
envs, _ = fake_gh(world_for(SYMBOLS))
run(envs, plan=planf)
copy_of = {int(i["description"].rsplit("#", 1)[1].split()[0]): i for i in store.issues}
copy_of[21]["description"] = copy_of[21]["description"].replace("x > 5", "x < 5")
for c in store.comments:
    c["body"] = c["body"].replace("Use -5.", "Use 5.")
copy_of[23]["description"] = copy_of[23]["description"].replace("Plain  text.", "Plain text.").replace(
    "(https://ex.test/d)", "(<https://ex.test/d>)")
open(envs["FAKE_GH_LOG"], "w").close()
code, out, err = finish(envs, plan=planf)
check("a body that differs only in symbols keeps its GitHub issue open", "#21 has other text in Linear" in out, out)
check("a comment that differs only in symbols keeps its GitHub issue open",
      "#22 has 0 of its 1 comments in Linear" in out, out)
check("spacing and Linear's <> around a link address are not a difference", closed_numbers(envs) == [23],
      out + str(closes(envs)))
check("a text difference is fixed by hand, not by running the copy again",
      "make the Linear copy match GitHub by hand" in out, out)
store.issues[0]["title"] = "Limit is x < 5"
copy_of[21]["description"] = copy_of[21]["description"].replace("x < 5", "x > 5")
code, out, err = finish(envs, "--issues", "21", plan=planf)
check("a title that differs only in symbols keeps its GitHub issue open", "#21 has another title in Linear" in out, out)

# GitHub refusing to close one is named, and the run fails.
broken = world_for(WITH_IMAGES)
broken["close_refused"] = ["5"]
envr, _ = fake_gh(broken)
Linear.store = store = Store()
run(envr, "--issues", "5", plan=planf)
code, out, err = finish(envr, "--issues", "5", plan=planf)
check("a close GitHub refuses is named and fails the run",
      code != 0 and "GitHub refused to close: #5" in out, out + err)

# Nothing closes without the person's yes to this migration.
for name, plan_path in (
        ("no saved plan", os.path.join(tmpf, "missing.json")),
        ("a plan for another team", save_plan(tmpf, target="OPS")),
        ("a plan for another project", save_plan(tmpf, source="acme/site#8"))):
    open(envf["FAKE_GH_LOG"], "w").close()
    code, out, err = finish(envf, plan=plan_path)
    check("finish refuses {} and closes nothing".format(name), code != 0 and not closes(envf), out + err)

# --- The skill says how to run the copy, by key and by connector.

text = open(SKILL).read() if os.path.exists(SKILL) else ""


def says(phrase):
    check("SKILL.md says: " + phrase, phrase in text)


says("migrate.py copy --repo <owner>/<repo> --project <number> --team <KEY> --key-env")
says("Written on GitHub by")
says("Needs Human")
says("never through the\nLinear connector")
says("<!-- copied from GitHub acme/site#5 -->")
says("`<owner>/<repo>#<project>`")
check("SKILL.md holds no connector copy steps", "save_issue" not in text and "save_comment" not in text)
says("nothing is copied twice")
check("SKILL.md no longer says the copy is not built", "is not built yet" not in text)
check("SKILL.md no longer says the links are not built", "Links between the copies" not in text)
says("parent and blocked-by links")
says("another repository copied to the same team")
says("migrate.py finish --repo <owner>/<repo> --project <number> --team <KEY> --key-env")
says("as not planned")
check("SKILL.md no longer says closing the originals is not built", "Closing the GitHub originals, and" not in text)

for path in sorted(os.listdir(SKILL_DIR)):
    body = open(os.path.join(SKILL_DIR, path)).read()
    for word in ("initiative", "layout"):
        check("{} holds no layout choice ({})".format(path, word), word not in body.lower())

server.shutdown()
print("{} passed, {} failed".format(passed, failed))
sys.exit(1 if failed else 0)
