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
  migrate.py finish --repo <owner>/<repo> --project <number> --team <KEY>
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
agreed to GitHub to Linear, from this repository and project, through a key,
for that team. It never runs through the connector. It copies each open
issue of the repository in the project (or the milestone, or the numbers named)
into one Linear project with the GitHub project's name, each GitHub milestone a
milestone inside it, with the same title, body, labels and every comment. Each
comment starts with a line naming its GitHub author and its time in Eastern. An
issue labelled needs-decision or parked lands as Needs Human. Each copy's body
ends with a hidden line naming its GitHub issue. Run it again and nothing is
copied twice: an issue whose copy carries that line is not made again, and a
comment already on it is not posted again. A copy whose line was removed is
not found, and the issue is copied again. Last, the parent and blocked-by
links GitHub holds between two issues that both have a copy are made between
the copies, each once; a link whose other side has no copy is named, not made.

finish runs after copy, under the same saved plan. It counts the chosen open
issues and their comments on GitHub and on their Linear copies, lists every
image in their text, then closes on GitHub, as not planned, each issue whose
copy holds every one of its comments. It posts no comment and deletes nothing,
so nothing on GitHub names the Linear copy. An issue whose copy is missing or
short a comment stays open and is named.

The Linear key is read from the environment variable the person names, at run
time. It is never printed, logged or saved: everything Linear sends back is
shown with the key hidden, and the plan file holds only where the key is kept.
"""
import argparse
import collections
import datetime
import html.parser
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
  repository(owner:$owner,name:$name){ issue(number:$number){ number title body bodyHTML state
    milestone{title} labels(first:100){nodes{name}}
    parent{ number repository{nameWithOwner} }
    subIssues(first:100){ pageInfo{hasNextPage} nodes{ number repository{nameWithOwner} } }
    blockedBy(first:100){ pageInfo{hasNextPage} nodes{ number repository{nameWithOwner} } }
    blocking(first:100){ pageInfo{hasNextPage} nodes{ number repository{nameWithOwner} } }
    comments(first:100, after:$after){ pageInfo{hasNextPage endCursor}
      nodes{ author{login} createdAt body bodyHTML } } } } }"""

# The GitHub links between issues that the copy keeps, and how a refusal names them.
LINK_FIELDS = {"subIssues": "sub-issues", "blockedBy": "issues blocking it", "blocking": "issues it blocks"}

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
    for field, name in LINK_FIELDS.items():
        if ((issue.get(field) or {}).get("pageInfo") or {}).get("hasNextPage"):
            fail("Issue {} of {} has more than 100 {}, more than one read holds, so a link would be lost. "
                 "Nothing was written.".format(number, repo, name), 1)
    issue = dict(issue)
    issue["comments"] = comments
    return issue


def github_links(repo, issues):
    """The parent and blocked-by links GitHub holds for these issues, each end as (repository, number):
    parents as (sub-issue, parent), blocks as (blocker, the issue that waits). Read from both ends,
    so a link is found whichever of its two issues a run copies."""
    def end(node):
        return ((node.get("repository") or {}).get("nameWithOwner") or "").lower(), node.get("number")

    def nodes(issue, field):
        return (issue.get(field) or {}).get("nodes") or []

    parents, blocks = set(), set()
    for issue in issues:
        me = (repo.lower(), issue["number"])
        if issue.get("parent"):
            parents.add((me, end(issue["parent"])))
        parents.update((end(sub), me) for sub in nodes(issue, "subIssues"))
        blocks.update((end(other), me) for other in nodes(issue, "blockedBy"))
        blocks.update((me, end(other)) for other in nodes(issue, "blocking"))
    return parents, blocks


def chosen_numbers(repo, project, milestone, numbers):
    """The open issue numbers of repo in the project, cut to one milestone or to the numbers named."""
    found = read_project(repo, project, numbers=True)
    if found is None:
        fail("gh cannot see project {} of {}. Nothing was written.".format(project, repo.split("/", 1)[0]))
    title, items = found
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
    return title, sorted(items, key=lambda item: item[0])


UNNUMBERED = 1000000.0


def place(name, made):
    """A new milestone's sort order, so it lands in build order among those already made, whatever
    earlier runs chose. A numbered name takes its own number. A name with no number goes after the
    numbered ones, halfway between the made milestones just before and just after it by name.
    `made` maps each milestone already in the project to its sort order."""
    kind, number, _ = build_order(name)
    if kind == 0:
        return float(number)
    before = [order for other, order in made.items() if build_order(other)[0] == 1 and other < name]
    after = [order for other, order in made.items() if build_order(other)[0] == 1 and other > name]
    low = max(before + [UNNUMBERED])
    high = min(after) if after else low + 2.0
    return (low + high) / 2.0


TEAM = """query($key:String!){ teams(filter:{key:{eq:$key}}){ nodes{ id key
  states(first:100){nodes{id name}} labels(first:250){nodes{id name}} } }
  issueLabels(first:250, filter:{team:{null:true}}){nodes{id name}} }"""

PROJECTS = """query($name:String!){ projects(filter:{name:{eq:$name}}){ nodes{ id name
  teams{nodes{id}} projectMilestones{nodes{id name sortOrder}} } } }"""

# Matched whatever the case: the hidden line holds the repository as the person typed it on that run.
COPIES = """query($team:ID!,$mark:String!,$after:String){
  issues(first:100, after:$after, includeArchived:true,
         filter:{team:{id:{eq:$team}}, description:{containsIgnoreCase:$mark}}){
    pageInfo{hasNextPage endCursor} nodes{ id description createdAt project{id} } } }"""

PROJECT_BY_ID = """query($id:String!){ project(id:$id){ id name
  teams{nodes{id}} projectMilestones{nodes{id name sortOrder}} } }"""


MARK = "<!-- copied from GitHub {}#{}"


def with_mark(body, repo, number):
    """An issue's body as its Linear copy holds it: the GitHub text, then a hidden line naming the
    GitHub issue, which Linear does not show and a later run reads to find the copy."""
    mark = MARK.format(repo, number) + " -->"
    # A hidden line written into the GitHub text by its author is turned into one no run reads, so
    # it can never pass for this or another issue's line. Linear shows neither, so the text looks the same.
    body = re.sub(r"<!--(\s*)copied from GitHub", r"<!--\1quoted from GitHub", (body or ""), flags=re.I).rstrip()
    return "{}\n\n{}".format(body, mark) if body else mark


def copied_from(repo, description):
    """The GitHub issue number a copy's hidden line names for repo, or None when the line is gone.
    Only the description's last non-blank line counts, where the copy put it."""
    lines = [line for line in (description or "").splitlines() if line.strip()]
    found = re.fullmatch(r"\s*<!-- copied from GitHub ([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+) -->\s*",
                         lines[-1]) if lines else None
    if not found or found.group(1).lower() != repo.lower():
        return None
    return int(found.group(2))


def same_text(text):
    """Text reduced to its letters and digits, so Linear's own reformatting of a comment still matches."""
    return "".join(ch for ch in (text or "").casefold() if ch.isalnum())

COMMENTS = """query($id:String!,$after:String){ issue(id:$id){
  comments(first:100, after:$after){ pageInfo{hasNextPage endCursor} nodes{ body } } } }"""

PARENT = """query($id:String!){ issue(id:$id){ parent{ id } } }"""

RELATIONS = """query($id:String!,$after:String){ issue(id:$id){
  relations(first:100, after:$after){ pageInfo{hasNextPage endCursor} nodes{ type relatedIssue{ id } } } } }"""

SET_PARENT = """mutation($id:String!,$input:IssueUpdateInput!){
  issueUpdate(id:$id, input:$input){ success issue{ id } } }"""


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


def copies_of(key, team_id, repo):
    """Every copy on the team of another repository's issues, by GitHub number: the copies an earlier
    run of the copy made from that repository, whatever case its name was typed in then. As for this
    repository, the earliest copy wins."""
    if not re.match(r"^[a-z0-9_.-]+/[a-z0-9_.-]+$", repo):
        return {}
    found = {}
    for node in sorted(every_page(key, COPIES, {"team": team_id, "mark": MARK.format(repo, "")},
                                  ("issues",)), key=lambda n: n["createdAt"]):
        number = copied_from(repo, node.get("description"))
        if number is not None:
            found.setdefault(number, node["id"])
    return found


def make_links(key, repo, team_id, parents, blocks, copies):
    """Make each GitHub link between two issues that both have a copy on the team, once: the sub-issue's
    copy gets the parent's copy as its parent, and the blocker's copy blocks the waiting one's. The
    other issue may be in another repository copied to the same team. A copy already under another
    parent in Linear is left there. Returns the lines to print."""
    found = {repo.lower(): copies}

    def copy_of(end):
        if end[0] not in found:
            found[end[0]] = copies_of(key, team_id, end[0])
        return found[end[0]].get(end[1])

    def name(end):
        return "#{}".format(end[1]) if end[0] == repo.lower() else "{}#{}".format(shown(end[0]), end[1])

    new_parents = new_blocks = 0
    missing, kept = [], []
    for child, parent in sorted(parents):
        said = "{} is a sub-issue of {}".format(name(child), name(parent))
        if not (copy_of(child) and copy_of(parent)):
            missing.append(said)
            continue
        now = ((linear(key, PARENT, {"id": copy_of(child)}).get("issue") or {}).get("parent") or {}).get("id")
        if now == copy_of(parent):
            continue
        if now:
            kept.append(said)
            continue
        made(linear(key, SET_PARENT, {"id": copy_of(child), "input": {"parentId": copy_of(parent)}}),
             "issueUpdate", "issue")
        new_parents += 1
    blocked = {}
    for blocker, waits in sorted(blocks):
        if not (copy_of(blocker) and copy_of(waits)):
            missing.append("{} blocks {}".format(name(blocker), name(waits)))
            continue
        if copy_of(blocker) not in blocked:
            blocked[copy_of(blocker)] = {r["relatedIssue"]["id"] for r in every_page(
                key, RELATIONS, {"id": copy_of(blocker)}, ("issue", "relations")) if r.get("type") == "blocks"}
        if copy_of(waits) in blocked[copy_of(blocker)]:
            continue
        create(key, "issueRelationCreate", "issueRelation",
               {"issueId": copy_of(blocker), "relatedIssueId": copy_of(waits), "type": "blocks"})
        blocked[copy_of(blocker)].add(copy_of(waits))
        new_blocks += 1

    lines = ["Links made now: {} parent link{}, {} blocked-by link{}.".format(
        new_parents, "" if new_parents == 1 else "s", new_blocks, "" if new_blocks == 1 else "s")]
    if missing:
        lines.append("Links not made, because one side has no copy on this Linear team (closed, not copied yet, "
                     "or in another repository not copied here): " + "; ".join(missing) + ".")
    if kept:
        lines.append("Left as it is, because the copy already has another parent in Linear: "
                     + "; ".join(kept) + ".")
    return lines


PLAN_SOURCE = re.compile(r"^(?:github:)?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:#|\s+project\s+)(\d+)$", re.I)
PLAN_TARGET = re.compile(r"^(?:linear:)?([A-Za-z0-9]+)$", re.I)


def load_plan(path, args):
    """Stop unless the saved plan is the person's yes to this copy: GitHub to Linear, from this
    repository and project, by a key in this variable, to this team."""
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
        fail("The copy into Linear is made only with a Linear API key, never the connector, and the saved plan "
             "chose the connector. Ask where the key is kept, save the plan again with --access key, and get "
             "the yes again. Nothing was written.")
    if access.get("key_env") != args.key_env:
        fail("The saved plan reads the key from another variable than {}. Nothing was written.".format(args.key_env))
    source = PLAN_SOURCE.match(str(record.get("source", "")).strip())
    if not source:
        fail('The saved plan\'s source "{}" does not name a repository and project as <owner>/<repo>#<project>. '
             "Save the plan again. Nothing was written.".format(shown(record.get("source"))))
    if source.group(1).lower() != args.repo.lower() or int(source.group(2)) != args.project:
        fail("The saved plan is for {} project {}, not {} project {}. Nothing was written.".format(
            source.group(1), source.group(2), args.repo, args.project))
    target = PLAN_TARGET.match(str(record.get("target", "")).strip())
    if not target or target.group(1).upper() != args.team.upper():
        fail('The saved plan copies to "{}", not to the team {}. Nothing was written.'.format(
            shown(record.get("target")), shown(args.team.upper())))


def copy(args):
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", args.repo):
        fail("--repo takes <owner>/<repo>, such as acme/site.")
    load_plan(args.plan, args)
    key = read_key(args.key_env)
    title, items = chosen_numbers(args.repo, args.project, args.milestone, args.issues)
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

    # Copies already made, anywhere on the team, archived ones too, found by their hidden line only:
    # a renamed project or a copy moved to another project is still found, and nothing else can tell
    # which issue a copy came from.
    found, homes = {}, collections.Counter()
    for node in sorted(every_page(key, COPIES, {"team": team["id"], "mark": MARK.format(args.repo, "")},
                                  ("issues",)), key=lambda n: n["createdAt"]):
        number = copied_from(args.repo, node.get("description"))
        if number is not None:
            found.setdefault(number, node["id"])
            if node.get("project"):
                homes[node["project"]["id"]] += 1

    # The project: the one the earlier copies sit in, whatever it is called now; else found by name
    # on this team; else made.
    if homes:
        projects = [linear(key, PROJECT_BY_ID, {"id": homes.most_common(1)[0][0]}).get("project")]
    else:
        projects = [p for p in ((linear(key, PROJECTS, {"name": title}).get("projects") or {}).get("nodes") or [])
                    if any(t["id"] == team["id"] for t in p["teams"]["nodes"])]
    if len(projects) > 1:
        fail('{} Linear projects on the team are named "{}". Nothing was written.'.format(len(projects), shown(title)), 1)
    project = projects[0] if projects and projects[0] else create(key, "projectCreate", "project",
                                                                   {"name": title, "teamIds": [team["id"]]})
    existing = (project.get("projectMilestones") or {}).get("nodes") or []
    milestones = {m["name"]: m["id"] for m in existing}
    made = {m["name"]: float(m.get("sortOrder") or 0) for m in existing}

    new_milestones = 0
    for github_name in sorted({m for _, m in items if m}, key=build_order):
        name = inside(title, github_name)
        if name not in milestones:
            made[name] = place(name, made)
            milestones[name] = create(key, "projectMilestoneCreate", "projectMilestone",
                                      {"projectId": project["id"], "name": name, "sortOrder": made[name]})["id"]
            new_milestones += 1

    new_issues = new_comments = new_labels = 0
    for issue in issues:
        if issue["number"] in found:
            target = {"id": found[issue["number"]]}
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
            fields = {"teamId": team["id"], "title": issue["title"],
                      "description": with_mark(issue.get("body"), args.repo, issue["number"]),
                      "projectId": project["id"]}
            if issue.get("milestone"):
                fields["projectMilestoneId"] = milestones[inside(title, issue["milestone"]["title"])]
            if label_ids:
                fields["labelIds"] = label_ids
            if held:
                fields["stateId"] = needs_human
            target = create(key, "issueCreate", "issue", fields)
            found[issue["number"]] = target["id"]
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

    # Links last, once every chosen issue has its copy; `found` now holds every copy on the team.
    parents, blocks = github_links(args.repo, issues)
    link_lines = make_links(key, args.repo, team["id"], parents, blocks, found)

    lines = ['Linear project "{}" holds the {} chosen from {}.'.format(shown(title), plural(len(issues)), args.repo)]
    lines.append("Made now: {} project, {}, {} milestone{}, {} comment{}, {} label{}.".format(
        0 if projects else 1, plural(new_issues), new_milestones, "" if new_milestones == 1 else "s",
        new_comments, "" if new_comments == 1 else "s", new_labels, "" if new_labels == 1 else "s"))
    if len(issues) > new_issues:
        lines.append("Already in Linear, so not made again: {}.".format(plural(len(issues) - new_issues)))
    lines += link_lines
    lines.append("Nothing was written to GitHub.")
    print(hide("\n".join(lines), key))


# ---------------------------------------------------------------- the finish

class Images(html.parser.HTMLParser):
    """The <img> tags of GitHub's own rendering of a body, so the list is what GitHub shows, however the
    text was written. An image GitHub serves through its proxy is named by its own address, and an emoji
    GitHub draws as an image is left out."""

    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        attrs = dict(attrs)
        if "emoji" in (attrs.get("class") or "").split():
            return
        url = attrs.get("data-canonical-src") or attrs.get("src")
        if url:
            self.found.append(url)


def images_in(rendered):
    """Every image GitHub shows in a body or comment, by its address, in the order shown."""
    reader = Images()
    reader.feed(rendered or "")
    reader.close()
    return reader.found


def close_not_planned(repo, number):
    """Close one GitHub issue as not planned, with no comment: nothing is deleted and nothing names
    its Linear copy. True when gh closed it."""
    result = subprocess.run(["gh", "issue", "close", str(number), "--repo", repo, "--reason", "not planned"],
                            capture_output=True, text=True)
    return result.returncode == 0


def finish(args):
    """Check each chosen GitHub issue against its Linear copy, list every image, then close as not
    planned each issue whose copy holds every one of its comments. One that does not stays open."""
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", args.repo):
        fail("--repo takes <owner>/<repo>, such as acme/site.")
    load_plan(args.plan, args)
    key = read_key(args.key_env)
    _, items = chosen_numbers(args.repo, args.project, args.milestone, args.issues)
    if not items:
        print("No open issue left to finish. Nothing was written.")
        return
    teams = (linear(key, TEAM, {"key": args.team.upper()}).get("teams") or {}).get("nodes") or []
    if not teams:
        fail('No Linear team with the key "{}" that this key can see. Nothing was written.'.format(args.team.upper()), 1)
    issues = [read_issue(args.repo, number) for number, _ in items]
    copies = copies_of(key, teams[0]["id"], args.repo.lower())

    github_comments = linear_comments = 0
    ready, held, images = [], [], []
    for issue in issues:
        number = issue["number"]
        for text in [issue.get("bodyHTML")] + [c.get("bodyHTML") for c in issue["comments"]]:
            images += ["#{}: {}".format(number, shown(url)) for url in images_in(text)]
        github_comments += len(issue["comments"])
        if number not in copies:
            held.append("#{} has no copy on the team".format(number))
            continue
        posted = collections.Counter(same_text(c["body"]) for c in every_page(
            key, COMMENTS, {"id": copies[number]}, ("issue", "comments")))
        matched = 0
        for comment in issue["comments"]:
            if posted[same_text(comment_body(comment))] > 0:
                posted[same_text(comment_body(comment))] -= 1
                matched += 1
        linear_comments += matched
        if matched < len(issue["comments"]):
            held.append("#{} has {} of its {} comments in Linear".format(number, matched, len(issue["comments"])))
        else:
            ready.append(number)

    lines = ["GitHub: {}, {} comment{}.".format(plural(len(issues)), github_comments,
                                                "" if github_comments == 1 else "s"),
             "Linear: {} of them copied, {} of those comments.".format(
                 sum(1 for i in issues if i["number"] in copies), linear_comments)]
    if images:
        lines.append("Images in the GitHub text ({}); check each shows in Linear:".format(len(images)))
        lines += ["   " + line for line in images]
    else:
        lines.append("No image in the GitHub text.")
    if held:
        lines.append("Left open, because the copy does not match yet: " + "; ".join(held)
                     + ". Run the copy again, then finish again.")
    closed, refused = [], []
    for number in ready:
        (closed if close_not_planned(args.repo, number) else refused).append("#{}".format(number))
    if closed:
        lines.append("Closed on GitHub as not planned: {}.".format(", ".join(closed)))
    if refused:
        lines.append("GitHub refused to close: {}. Check `gh auth status` can write issues, then finish "
                     "again.".format(", ".join(refused)))
    lines.append("Nothing on GitHub was deleted, and nothing on GitHub names its Linear copy.")
    print(hide("\n".join(lines), key))
    if held or refused:
        sys.exit(1)


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
    done = sub.add_parser("finish")
    done.add_argument("--repo", required=True)
    done.add_argument("--project", required=True, type=int)
    done.add_argument("--team", required=True)
    done.add_argument("--key-env", required=True)
    cut = done.add_mutually_exclusive_group()
    cut.add_argument("--milestone")
    cut.add_argument("--issues", nargs="+", type=int)
    done.add_argument("--plan")
    args = parser.parse_args()
    {"read-github": read_github, "check-linear": check_linear, "read-linear": read_linear,
     "plan": plan, "copy": copy, "finish": finish}[args.command](args)


if __name__ == "__main__":
    main()
