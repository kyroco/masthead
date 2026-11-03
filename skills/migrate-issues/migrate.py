#!/usr/bin/env python3
"""/masthead:migrate-issues: look, ask, save the plan, then copy GitHub issues into Linear.

usage:
  migrate.py read-github --repo <owner>/<repo> --project <number>
  migrate.py check-linear --key-env <NAME> [--team <KEY>]
  migrate.py read-linear --key-env <NAME> (--project <name> | --issues <KEY>...)
  migrate.py plan --direction github-to-linear|linear-to-github
                  --source <what> --target <where>
                  --access key|connector [--key-env <NAME> --kept <where>]
                  [--out <file>]
  migrate.py copy --repo <owner>/<repo> --project <number> --team <KEY>
                  --key-env <NAME> [--milestone <title> | --issues <n>...]
                  [--plan <file>]

read-github reads one repository's open issues in one of its GitHub projects
through `gh`, and prints what they become in Linear: one Linear project with
the GitHub project's name, each milestone a milestone inside it. Issues the
project holds from other repositories are left out. check-linear asks Linear
who the key belongs to, and whether a team exists. read-linear reads a Linear
project, or issues named by key, and prints what each becomes on GitHub. plan
saves what the person agreed to. None of those writes to GitHub or Linear.

copy writes, and only to Linear, and only when the saved plan says the person
agreed to GitHub to Linear through a key for that team. It copies each open
issue of the repository in the project (or the milestone, or the numbers named)
into one Linear project with the GitHub project's name, each GitHub milestone a
milestone inside it, with the same title, body, labels and every comment. Each
comment starts with a line naming its GitHub author and its time in Eastern. An
issue labelled needs-decision or parked lands as Needs Human. Run it again and
nothing is copied twice: an issue already in the Linear project under the same
title is not made again, and a comment already on it is not posted again.

The Linear key is read from the environment variable the person names, at run
time. It is never printed, logged or saved: everything Linear sends back is
shown with the key hidden, and the plan file holds only where the key is kept.
"""
import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

LINEAR_URL = "https://api.linear.app/graphql"
HIDDEN = "[key hidden]"
LINEAR_KEY_SHAPE = re.compile(r"lin_(?:api|oauth)_[A-Za-z0-9]{8,}")


def fail(message, code=2):
    print(message, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- GitHub

PROJECT_QUERY = """query($login:String!,$number:Int!,$after:String){
  %s(login:$login){ projectV2(number:$number){ title
    items(first:100, after:$after){ pageInfo{hasNextPage endCursor}
      nodes{ content{ __typename ... on Issue{ number state
        repository{nameWithOwner} milestone{title} } } } } } } }"""


def gh_project_page(kind, login, number, after):
    args = ["gh", "api", "graphql", "-f", "query=" + PROJECT_QUERY % kind,
            "-f", "login=" + login, "-F", "number=" + str(number)]
    if after:
        args += ["-f", "after=" + after]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        owner = json.loads(result.stdout)["data"][kind]
    except (ValueError, KeyError, TypeError):
        return None
    return (owner or {}).get("projectV2")


def read_project(repo, number, numbers=False):
    """The project's title and the milestones of its open issues in repo, or None when gh cannot see it.

    With numbers, each item is (issue number, milestone) in place of the milestone alone."""
    login = repo.split("/", 1)[0]
    for kind in ("organization", "user"):
        page = gh_project_page(kind, login, number, None)
        if page is None:
            continue
        title, milestones = page["title"], []
        while True:
            for node in page["items"]["nodes"]:
                content = node.get("content") or {}
                if content.get("__typename") != "Issue" or content.get("state") != "OPEN":
                    continue
                if (content.get("repository") or {}).get("nameWithOwner", "").lower() != repo.lower():
                    continue
                milestone = (content.get("milestone") or {}).get("title")
                milestones.append((content.get("number"), milestone) if numbers else milestone)
            info = page["items"]["pageInfo"]
            if not info["hasNextPage"]:
                return title, milestones
            page = gh_project_page(kind, login, number, info["endCursor"])
            if page is None:
                fail("GitHub stopped answering partway through the project; nothing was written.")
    return None


def build_order(title):
    """Sort `<project>: <n>. <name>` milestones by their number, the rest by name."""
    match = re.search(r"(?:^|:\s*)(\d+)\.", title)
    return (0, int(match.group(1)), title) if match else (1, 0, title)


def inside(project, milestone):
    """A milestone's name inside its own project: the `<project>: ` prefix is dropped.

    GitHub milestones are named `<project>: <n>. <name>`, and the project part is
    often shorter than the GitHub project's title, so any prefix before a
    numbered name goes. A name with no number keeps everything but the full title.
    """
    numbered = re.match(r"^[^:]+:\s*(\d+\..*)$", milestone)
    if numbered:
        return numbered.group(1).strip()
    prefix = project + ":"
    return milestone[len(prefix):].strip() if milestone.startswith(prefix) else milestone


def plural(n):
    return "{} issue{}".format(n, "" if n == 1 else "s")


ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def shown(name):
    """A name from GitHub or Linear, ready to print: a line break or other hidden character is
    written out (`\\n`, `\\x07`), so a name can never print a line of its own."""
    return "".join(ch if ch.isprintable() else ESCAPES.get(ch, "\\x{:02x}".format(ord(ch)) if ord(ch) < 256
                                                            else "\\u{:04x}".format(ord(ch)))
                   for ch in str(name))


def read_github(args):
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", args.repo):
        fail("--repo takes <owner>/<repo>, such as acme/site.")
    found = read_project(args.repo, args.project)
    if found is None:
        fail("gh cannot see project {} of {}. Check the repository and number, and that `gh auth status` "
             "has the project scope.".format(args.project, args.repo.split("/", 1)[0]))
    title, milestones = found
    counts = {}
    for name in milestones:
        counts[name] = counts.get(name, 0) + 1
    named = sorted((m for m in counts if m), key=build_order)
    loose = counts.get(None, 0)

    lines = ['GitHub project "{}", issues in {}: {} milestone{}, {} open issue{}.'.format(
        shown(title), args.repo, len(named), "" if len(named) == 1 else "s", len(milestones),
        "" if len(milestones) == 1 else "s"), ""]
    lines.append("In Linear it becomes one project with the same name, each milestone a milestone inside it:")
    lines.append('   Linear project "{}"'.format(shown(title)))
    for name in named:
        lines.append('     milestone "{}" ({})'.format(shown(inside(title, name)), plural(counts[name])))
    if loose:
        lines.append("     no milestone ({})".format(plural(loose)))
    lines.append("")
    lines.append("Nothing has been written to GitHub or Linear.")
    print("\n".join(lines))


# ---------------------------------------------------------------- Linear

def linear_url():
    """Linear's address. A test may point it at this machine, and nowhere else."""
    url = os.environ.get("MASTHEAD_LINEAR_URL")
    if not url:
        return LINEAR_URL
    if urllib.parse.urlparse(url).hostname not in ("127.0.0.1", "localhost", "::1"):
        fail("MASTHEAD_LINEAR_URL may only name this machine; the key is sent to Linear and nowhere else.")
    return url


def hide(text, key):
    text = text.replace(key, HIDDEN)
    return LINEAR_KEY_SHAPE.sub(HIDDEN, text)


def read_key(name):
    """The key in the variable, trimmed. Refused, never printed, when it is empty or not one plain word."""
    key = os.environ.get(name, "").strip()
    if not key:
        fail("{} is not set, so there is no key to read. Nothing was sent.".format(name))
    if key.startswith("op://"):
        fail("{} holds a 1Password reference, not the key. Run this under `op run --` so 1Password puts "
             "the key in its place. Nothing was sent.".format(name))
    if any(ch.isspace() or not ch.isprintable() for ch in key):
        fail("{} holds a space, a line break or another hidden character, so it is not one Linear key. "
             "Check the field it comes from. Nothing was sent.".format(name))
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect. urllib would follow one and copy the key's header to the new address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# No proxy: a proxy set in the environment would get the key, in plain text over http.
SEND = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


def linear(key, query, variables=None):
    """Send one request to Linear. Returns its data, or stops with its error, the key hidden."""
    request = urllib.request.Request(
        linear_url(), data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": key, "Content-Type": "application/json"}, method="POST")
    try:
        with SEND.open(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            fail("Linear answered with a redirect ({}). It was not followed, so the key went nowhere else; "
                 "nothing was written.".format(error.code), 1)
        body = error.read().decode("utf-8", "replace")
        fail("Linear refused the request ({}): {}".format(error.code, hide(body, key)[:600]), 1)
    except (urllib.error.URLError, OSError) as error:
        fail("Linear could not be reached: {}".format(hide(str(error), key)), 1)
    except Exception as error:  # anything else could carry the key in its text; never let it print raw
        fail("The request to Linear failed: {}".format(hide("{}: {}".format(type(error).__name__, error), key)), 1)
    try:
        answer = json.loads(body)
    except ValueError:
        fail("Linear answered with something other than JSON: {}".format(hide(body, key)[:600]), 1)
    if answer.get("errors"):
        fail("Linear refused the request: {}".format(hide(json.dumps(answer["errors"]), key)[:600]), 1)
    return answer.get("data") or {}


def check_linear(args):
    key = read_key(args.key_env)
    if args.team:
        data = linear(key, "query($key:String!){ viewer{name} organization{name urlKey} "
                           "teams(filter:{key:{eq:$key}}){nodes{name key}} }", {"key": args.team.upper()})
    else:
        data = linear(key, "{ viewer{name} organization{name urlKey} }")
    viewer = (data.get("viewer") or {}).get("name", "-")
    org = data.get("organization") or {}
    print(hide('Linear answers: the key belongs to {} in the workspace "{}".'.format(
        shown(viewer), shown(org.get("name", "-"))), key))
    if args.team:
        teams = (data.get("teams") or {}).get("nodes") or []
        if not teams:
            fail('No Linear team with the key "{}" in that workspace.'.format(args.team.upper()), 1)
        print(hide('It can see the team "{}" ({}).'.format(shown(teams[0]["name"]), shown(teams[0]["key"])), key))


OPEN = ("backlog", "unstarted", "started", "triage")

PROJECT_BY_NAME = """query($name:String!){ projects(filter:{name:{eq:$name}}){ nodes{ id name
  projectMilestones{ nodes{ name sortOrder } } } } }"""

PROJECT_ISSUES = """query($id:String!,$after:String){ project(id:$id){
  issues(first:100, after:$after){ pageInfo{hasNextPage endCursor}
    nodes{ identifier state{type} projectMilestone{name} } } } }"""

ONE_ISSUE = """query($id:String!){ issue(id:$id){ identifier state{type}
  project{ name projectMilestones{ nodes{ name sortOrder } } } projectMilestone{name} } }"""


def github_milestone(project, milestone, number):
    """A Linear milestone's name on GitHub: `<project>: <n>. <name>`."""
    if re.match(r"\s*\d+\.", milestone):
        return "{}: {}".format(project, milestone.strip())
    return "{}: {}. {}".format(project, number, milestone)


def read_linear(args):
    key = read_key(args.key_env)
    lines = []
    if args.project:
        found = (linear(key, PROJECT_BY_NAME, {"name": args.project}).get("projects") or {}).get("nodes") or []
        if not found:
            fail('No Linear project named "{}" that this key can see.'.format(args.project), 1)
        if len(found) > 1:
            fail('{} Linear projects are named "{}"; name the issues by key instead.'.format(len(found), args.project), 1)
        project = found[0]
        order = sorted(project["projectMilestones"]["nodes"], key=lambda m: m["sortOrder"])
        numbers = {m["name"]: n for n, m in enumerate(order, 1)}
        counts, after, total = {}, None, 0
        while True:
            page = (linear(key, PROJECT_ISSUES, {"id": project["id"], "after": after}).get("project") or {}).get("issues")
            if not page:
                fail("Linear stopped answering partway through the project; nothing was written.", 1)
            for node in page["nodes"]:
                if (node.get("state") or {}).get("type") not in OPEN:
                    continue
                total += 1
                name = (node.get("projectMilestone") or {}).get("name")
                counts[name] = counts.get(name, 0) + 1
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        lines.append('Linear project "{}": {} milestone{}, {} open issue{}.'.format(
            shown(project["name"]), len(order), "" if len(order) == 1 else "s", total, "" if total == 1 else "s"))
        lines.append("")
        lines.append("On GitHub the structure stays as it is:")
        lines.append('   GitHub project "{}", with its brief as the project README'.format(shown(project["name"])))
        for m in order:
            if counts.get(m["name"]):
                lines.append('     milestone "{}" ({})'.format(
                    shown(github_milestone(project["name"], m["name"], numbers[m["name"]])), plural(counts[m["name"]])))
        if counts.get(None):
            lines.append("     no milestone ({})".format(plural(counts[None])))
    else:
        lines.append("Linear issues named by key, and where each lands on GitHub:")
        for wanted in args.issues:
            node = linear(key, ONE_ISSUE, {"id": wanted.upper()}).get("issue")
            if not node:
                fail("No Linear issue {} that this key can see.".format(wanted.upper()), 1)
            project = (node.get("project") or {}).get("name")
            milestone = (node.get("projectMilestone") or {}).get("name")
            place = 'GitHub project "{}"'.format(shown(project)) if project else "no project"
            if project and milestone:
                order = sorted(((node.get("project") or {}).get("projectMilestones") or {}).get("nodes") or [],
                               key=lambda m: m["sortOrder"])
                numbers = {m["name"]: n for n, m in enumerate(order, 1)}
                place += ', milestone "{}"'.format(shown(github_milestone(project, milestone, numbers.get(milestone, 0))))
            if (node.get("state") or {}).get("type") not in OPEN:
                place += " (closed in Linear)"
            lines.append("   {}: {}".format(shown(node["identifier"]), place))
    lines.append("")
    lines.append("Nothing has been written to GitHub or Linear.")
    print(hide("\n".join(lines), key))


# ---------------------------------------------------------------- the plan

def default_plan_path():
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    root = top.stdout.strip() if top.returncode == 0 else os.getcwd()
    return os.path.join(root, ".claude", "state", "migration-plan.json")


def plan(args):
    access = {"kind": args.access}
    if args.access == "connector":
        if args.key_env or args.kept:
            fail("The Linear connector takes no key; leave out --key-env and --kept.")
    else:
        if not (args.key_env and args.kept):
            fail("A key needs --key-env, the variable it is read from, and --kept, where the person keeps it.")
        value = os.environ.get(args.key_env, "").strip()
        if LINEAR_KEY_SHAPE.search(args.kept) or (len(value) >= 8 and value in args.kept):
            fail("--kept holds a key, not the place it is kept. Nothing was saved. Ask where the key lives, "
                 "such as a 1Password reference, and never for the key itself.")
        access.update({"key_env": args.key_env, "kept": args.kept})
    record = {"direction": args.direction, "source": args.source, "target": args.target, "access": access}
    path = args.out or default_plan_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # Never through a link: a repository could ship one that points at another of the person's files.
    if os.path.islink(path):
        fail("{} is a link, so the plan was not saved: it would overwrite the file the link points to.".format(path))
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        fail("The plan could not be saved to {}: {}".format(path, error.strerror))
    os.fchmod(handle, 0o600)
    with os.fdopen(handle, "w") as out:
        json.dump(record, out, indent=2)
        out.write("\n")
    print("Saved the plan to {}. Nothing has been written to GitHub or Linear.".format(path))


# ---------------------------------------------------------------- the copy

ISSUE_QUERY = """query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){ issue(number:$number){ number title body state
    milestone{title} labels(first:100){nodes{name}}
    comments(first:100, after:$after){ pageInfo{hasNextPage endCursor}
      nodes{ author{login} createdAt body } } } } }"""

# On Linear these two labels are a status, Needs Human, not a label.
NEEDS_HUMAN_LABELS = ("needs-decision", "parked")
NEEDS_HUMAN = "Needs Human"

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")


def eastern(stamp):
    """A GitHub time, such as 2026-11-03T18:27:00Z, as `November 3, 2026, 1:27 PM Eastern`."""
    from zoneinfo import ZoneInfo
    when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    local = when.astimezone(ZoneInfo("America/New_York"))
    hour = local.hour % 12 or 12
    return "{} {}, {}, {}:{:02d} {} Eastern".format(MONTHS[local.month - 1], local.day, local.year, hour,
                                                    local.minute, "AM" if local.hour < 12 else "PM")


def comment_body(comment):
    """A GitHub comment as it lands in Linear: a first line naming who wrote it on GitHub, and when."""
    login = (comment.get("author") or {}).get("login") or "a deleted GitHub account"
    return "Written on GitHub by {}, {}.\n\n{}".format(login, eastern(comment["createdAt"]), comment.get("body") or "")


def gh_graphql(query, **fields):
    args = ["gh", "api", "graphql", "-f", "query=" + query]
    for name, value in fields.items():
        if value is None:
            continue
        args += ["-F" if isinstance(value, int) else "-f", "{}={}".format(name, value)]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)["data"]
    except (ValueError, KeyError, TypeError):
        return None


def read_issue(repo, number):
    """One GitHub issue with every comment, or stop: a half-read issue is never copied."""
    owner, name = repo.split("/", 1)
    issue, comments, after = None, [], None
    while True:
        data = gh_graphql(ISSUE_QUERY, owner=owner, name=name, number=number, after=after)
        page = ((data or {}).get("repository") or {}).get("issue")
        if not page:
            fail("GitHub did not answer for issue {} of {}. Nothing was written.".format(number, repo), 1)
        issue = issue or page
        comments += page["comments"]["nodes"]
        if not page["comments"]["pageInfo"]["hasNextPage"]:
            break
        after = page["comments"]["pageInfo"]["endCursor"]
    issue = dict(issue)
    issue["comments"] = comments
    return issue


def chosen_numbers(repo, project, milestone, numbers):
    """The open issue numbers of repo in the project, cut to one milestone or to the numbers named."""
    found = read_project(repo, project, numbers=True)
    if found is None:
        fail("gh cannot see project {} of {}. Nothing was written.".format(project, repo.split("/", 1)[0]))
    title, items = found
    every_milestone = {m for _, m in items if m}
    if milestone is not None:
        items = [(n, m) for n, m in items if m == milestone]
        if not items:
            fail('No open issue of {} in the project has the milestone "{}". Nothing was written.'.format(
                repo, shown(milestone)))
    if numbers:
        held = {n for n, _ in items}
        missing = [n for n in numbers if n not in held]
        if missing:
            fail("Not open issues of {} in the project: {}. Nothing was written.".format(
                repo, ", ".join(str(n) for n in missing)))
        items = [(n, m) for n, m in items if n in set(numbers)]
    return title, sorted(items, key=lambda item: item[0]), every_milestone


def place(milestone, every_milestone):
    """A milestone's sort order, the same in every run however the copy is cut: its own number
    for `<project>: <n>. <name>`, and after those, its place by name among the project's others."""
    kind, number, _ = build_order(milestone)
    if kind == 0:
        return float(number)
    others = sorted(m for m in every_milestone if build_order(m)[0] == 1)
    return 1000000.0 + others.index(milestone)


TEAM = """query($key:String!){ teams(filter:{key:{eq:$key}}){ nodes{ id key
  states(first:100){nodes{id name}} labels(first:250){nodes{id name}} } }
  issueLabels(first:250, filter:{team:{null:true}}){nodes{id name}} }"""

PROJECTS = """query($name:String!){ projects(filter:{name:{eq:$name}}){ nodes{ id name
  teams{nodes{id}} projectMilestones{nodes{id name}} } } }"""

COPIES = """query($id:String!,$after:String){ project(id:$id){
  issues(first:100, after:$after){ pageInfo{hasNextPage endCursor} nodes{ id title description createdAt } } } }"""


def same_text(text):
    """Text reduced to its letters and digits, so Linear's own reformatting of a body still matches."""
    return "".join(ch for ch in (text or "").casefold() if ch.isalnum())

COMMENTS = """query($id:String!,$after:String){ issue(id:$id){
  comments(first:100, after:$after){ pageInfo{hasNextPage endCursor} nodes{ body } } } }"""


def made(answer, field, inner):
    """What a create call made, or stop when Linear says it did not."""
    result = answer.get(field) or {}
    if not result.get("success") or not result.get(inner):
        fail("Linear did not make the {}. Stopped here; run the copy again and nothing is copied twice.".format(
            inner), 1)
    return result[inner]


def create(key, mutation, kind, fields):
    """Make one thing in Linear through its `<mutation>(input:)` call and return what it made."""
    query = "mutation($input:{}Input!){{ {}(input:$input){{ success {}{{ id }} }} }}".format(
        mutation[0].upper() + mutation[1:], mutation, kind)
    return made(linear(key, query, {"input": fields}), mutation, kind)


def every_page(key, query, variables, path):
    """Every node of a paged Linear list, `path` naming the steps down to the list."""
    nodes, after = [], None
    while True:
        page = linear(key, query, dict(variables, after=after))
        for step in path:
            page = (page or {}).get(step)
        if not page:
            fail("Linear stopped answering partway through a list. Run the copy again; nothing is copied twice.", 1)
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return nodes
        after = page["pageInfo"]["endCursor"]


def load_plan(path, args):
    """Stop unless the saved plan is the person's yes to this copy: GitHub to Linear, by this key, to this team."""
    path = path or default_plan_path()
    try:
        with open(path) as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        fail("There is no saved plan at {}. Show the plan and get a yes first. Nothing was written.".format(path))
    access = record.get("access") or {}
    if record.get("direction") != "github-to-linear":
        fail("The saved plan is not for GitHub to Linear. Nothing was written.")
    if access.get("kind") != "key":
        fail("The saved plan reaches Linear through the connector, so the copy is made through the connector, "
             "not this script. Nothing was written.")
    if access.get("key_env") != args.key_env:
        fail("The saved plan reads the key from another variable than {}. Nothing was written.".format(args.key_env))
    if str(record.get("target", "")).strip().upper() != args.team.upper():
        fail('The saved plan copies to "{}", not to the team {}. Nothing was written.'.format(
            shown(record.get("target")), args.team.upper()))


def copy(args):
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", args.repo):
        fail("--repo takes <owner>/<repo>, such as acme/site.")
    load_plan(args.plan, args)
    key = read_key(args.key_env)
    title, items, every_milestone = chosen_numbers(args.repo, args.project, args.milestone, args.issues)
    if not items:
        print("No open issue to copy. Nothing was written.")
        return

    found = linear(key, TEAM, {"key": args.team.upper()})
    teams = (found.get("teams") or {}).get("nodes") or []
    if not teams:
        fail('No Linear team with the key "{}" that this key can see. Nothing was written.'.format(args.team.upper()), 1)
    team = teams[0]
    needs_human = {s["name"].lower(): s["id"] for s in team["states"]["nodes"]}.get(NEEDS_HUMAN.lower())
    labels = {}
    for label in ((found.get("issueLabels") or {}).get("nodes") or []) + team["labels"]["nodes"]:
        labels[label["name"].lower()] = label["id"]

    # Read every chosen issue before writing anything, so a GitHub failure writes nothing.
    issues = [read_issue(args.repo, number) for number, _ in items]
    held_back = [i["number"] for i in issues
                 if any(l["name"].lower() in NEEDS_HUMAN_LABELS for l in i["labels"]["nodes"])]
    if held_back and not needs_human:
        fail('Issues {} need the status "{}", and the team {} has none. Add it in Linear, then run the copy '
             'again. Nothing was written.'.format(", ".join(map(str, held_back)), NEEDS_HUMAN, shown(team["key"])), 1)

    # The project: found by name on this team, or made.
    projects = [p for p in ((linear(key, PROJECTS, {"name": title}).get("projects") or {}).get("nodes") or [])
                if any(t["id"] == team["id"] for t in p["teams"]["nodes"])]
    if len(projects) > 1:
        fail('{} Linear projects on the team are named "{}". Nothing was written.'.format(len(projects), shown(title)), 1)
    project = projects[0] if projects else create(key, "projectCreate", "project",
                                                   {"name": title, "teamIds": [team["id"]]})
    milestones = {m["name"]: m["id"] for m in ((project.get("projectMilestones") or {}).get("nodes") or [])}

    new_milestones = 0
    for github_name in sorted({m for _, m in items if m}, key=build_order):
        name = inside(title, github_name)
        if name not in milestones:
            milestones[name] = create(key, "projectMilestoneCreate", "projectMilestone",
                                      {"projectId": project["id"], "name": name,
                                       "sortOrder": place(github_name, every_milestone)})["id"]
            new_milestones += 1

    # Copies already in the project, oldest first, by title and body together: a GitHub issue pairs
    # only with a Linear issue holding its own words, so a same-titled issue copied in another run,
    # or reopened since, is never taken for this one. No link or number ties the two.
    copies = {}
    for node in sorted(every_page(key, COPIES, {"id": project["id"]}, ("project", "issues")),
                       key=lambda n: n["createdAt"]):
        copies.setdefault((node["title"], same_text(node.get("description"))), []).append(node)

    new_issues = new_comments = new_labels = 0
    for issue in issues:
        existing = copies.get((issue["title"], same_text(issue.get("body")))) or []
        if existing:
            target = existing.pop(0)
            posted = collections.Counter(same_text(c["body"]) for c in every_page(
                key, COMMENTS, {"id": target["id"]}, ("issue", "comments")))
        else:
            label_ids, held = [], False
            for label in issue["labels"]["nodes"]:
                name = label["name"]
                if name.lower() in NEEDS_HUMAN_LABELS:
                    held = True
                    continue
                if name.lower() not in labels:
                    labels[name.lower()] = create(key, "issueLabelCreate", "issueLabel",
                                                  {"name": name, "teamId": team["id"]})["id"]
                    new_labels += 1
                label_ids.append(labels[name.lower()])
            fields = {"teamId": team["id"], "title": issue["title"], "description": issue.get("body") or "",
                      "projectId": project["id"]}
            if issue.get("milestone"):
                fields["projectMilestoneId"] = milestones[inside(title, issue["milestone"]["title"])]
            if label_ids:
                fields["labelIds"] = label_ids
            if held:
                fields["stateId"] = needs_human
            target = create(key, "issueCreate", "issue", fields)
            new_issues += 1
            posted = collections.Counter()
        # Counted, not just looked up: two comments with the same words are two comments, and each
        # one already on the copy stands for one of them.
        for comment in issue["comments"]:
            body = comment_body(comment)
            if posted[same_text(body)] > 0:
                posted[same_text(body)] -= 1
                continue
            create(key, "commentCreate", "comment", {"issueId": target["id"], "body": body})
            new_comments += 1

    lines = ['Linear project "{}" holds the {} chosen from {}.'.format(shown(title), plural(len(issues)), args.repo)]
    lines.append("Made now: {} project, {}, {} milestone{}, {} comment{}, {} label{}.".format(
        0 if projects else 1, plural(new_issues), new_milestones, "" if new_milestones == 1 else "s",
        new_comments, "" if new_comments == 1 else "s", new_labels, "" if new_labels == 1 else "s"))
    if len(issues) > new_issues:
        lines.append("Already in Linear, so not made again: {}.".format(plural(len(issues) - new_issues)))
    lines.append("Nothing was written to GitHub.")
    print(hide("\n".join(lines), key))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    github = sub.add_parser("read-github")
    github.add_argument("--repo", required=True)
    github.add_argument("--project", required=True, type=int)
    check = sub.add_parser("check-linear")
    check.add_argument("--key-env", required=True)
    check.add_argument("--team")
    source = sub.add_parser("read-linear")
    source.add_argument("--key-env", required=True)
    which = source.add_mutually_exclusive_group(required=True)
    which.add_argument("--project")
    which.add_argument("--issues", nargs="+")
    saved = sub.add_parser("plan")
    saved.add_argument("--direction", required=True, choices=["github-to-linear", "linear-to-github"])
    saved.add_argument("--source", required=True)
    saved.add_argument("--target", required=True)
    saved.add_argument("--access", required=True, choices=["key", "connector"])
    saved.add_argument("--key-env")
    saved.add_argument("--kept")
    saved.add_argument("--out")
    copied = sub.add_parser("copy")
    copied.add_argument("--repo", required=True)
    copied.add_argument("--project", required=True, type=int)
    copied.add_argument("--team", required=True)
    copied.add_argument("--key-env", required=True)
    chosen = copied.add_mutually_exclusive_group()
    chosen.add_argument("--milestone")
    chosen.add_argument("--issues", nargs="+", type=int)
    copied.add_argument("--plan")
    args = parser.parse_args()
    {"read-github": read_github, "check-linear": check_linear, "read-linear": read_linear,
     "plan": plan, "copy": copy}[args.command](args)


if __name__ == "__main__":
    main()
