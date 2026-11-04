#!/usr/bin/env python3
"""/masthead:migrate-issues: look, ask, save the plan, then copy GitHub issues into Linear.

usage:
  migrate.py read-github --repo <owner>/<repo> --project <number>
  migrate.py check-linear --key-env <NAME> [--team <KEY>]
  migrate.py read-linear --key-env <NAME> (--project-file <file> | --project <name> | --issues <KEY>...)
  migrate.py plan --direction github-to-linear|linear-to-github
                  (--source <what> | --source-file <file>) --target <where>
                  --access key|connector [--key-env <NAME> --kept <where>]
                  [--out <file>]
  migrate.py copy --repo <owner>/<repo> --project <number> --team <KEY>
                  --key-env <NAME> [--milestone <title> | --issues <n>...]
                  [--plan <file>]
  migrate.py finish --repo <owner>/<repo> --project <number> --team <KEY>
                    --key-env <NAME> [--milestone <title> | --issues <n>...]
                    [--plan <file>]
  migrate.py structure (--project-file <file> | --project <name>) --repo <owner>/<repo> --key-env <NAME>
                       [--plan <file>]
  migrate.py copy-to-github (--project-file <file> | --project <name> | --issues <KEY>...)
                            --repo <owner>/<repo> --key-env <NAME> [--plan <file>]
  migrate.py finish-to-github (--project-file <file> | --project <name> | --issues <KEY>...)
                              --repo <owner>/<repo> --key-env <NAME> [--plan <file>]

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
copy holds the same title, body and every one of its comments. It posts no
comment and deletes nothing, so nothing on GitHub names the Linear copy. An
issue whose copy is missing, short a comment, or holds another title or body
stays open and is named.

structure is the first write of Linear to GitHub, under a saved plan for Linear
to GitHub, from this Linear project, by a key, to this repository. It writes
only to GitHub: one GitHub project with the Linear project's name, owned by the
repository's owner and linked to the repository, with the Linear brief as its
README and the Linear summary as its short description, and each Linear
milestone that holds an open issue a repository milestone named
`<project>: <n>. <name>`. A README or description already on GitHub is kept.
Run it again and nothing is made twice: the project is found by its name and a
milestone by its title.

copy-to-github runs after structure, under the same kind of plan (for issue keys,
the plan's source is the keys). It writes only to GitHub: one issue for each open
Linear issue, with the same title, body and labels (a missing label is made) and
every comment, oldest first, each starting with a line naming its Linear author
and its time in Eastern. Each lands in its `<project>: <n>. <name>` milestone and
in the GitHub project, with the same Status; Needs Human becomes the
needs-decision label and Status Todo. Each copy's body ends with a hidden line
naming its Linear key. It reads everything first and writes nothing when a
GitHub project, milestone or Status option is missing. Run it again and nothing
is copied twice: an issue whose copy carries that line is not made again, only
the comments the copy lacks are posted, and a Status already set is kept. Last,
the parent and blocked-by links Linear holds between two issues that both have
a copy are made between the copies, each once; a link whose other side has no
copy is named, not made.

finish-to-github runs after copy-to-github, under the same plan. It counts the
chosen open Linear issues and their comments and their GitHub copies, then
cancels in Linear each issue whose copy holds the same title, body and every
comment. It posts no comment, deletes nothing and writes nothing to GitHub, so
nothing in Linear names the GitHub copy. An issue whose copy is missing or does
not match stays open and is named.

A Linear project's name is written by whoever can edit the project, so the
skill passes it in a file (--project-file, --source-file), never typed into a
shell command where a quote or semicolon in it would run.

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

# description is the project's short summary in Linear, content its brief.
PROJECT_BY_NAME = """query($name:String!){ projects(filter:{name:{eq:$name}}){ nodes{ id name description content
  projectMilestones{ nodes{ name description sortOrder } } } } }"""

PROJECT_ISSUES = """query($id:String!,$after:String){ project(id:$id){
  issues(first:100, after:$after){ pageInfo{hasNextPage endCursor}
    nodes{ identifier state{type} projectMilestone{name} } } } }"""

ONE_ISSUE = """query($id:String!){ issue(id:$id){ identifier state{type}
  project{ name projectMilestones{ nodes{ name sortOrder } } } projectMilestone{name} } }"""


def github_milestone(project, milestone, number):
    """A Linear milestone's name on GitHub: `<project>: <n>. <name>`. A name that already starts with
    its number, `3. Polish`, keeps it; a version such as `2.0 Launch` is a name, not a number."""
    if re.match(r"\s*\d+\.(?:\s|$)", milestone):
        return "{}: {}".format(project, milestone.strip())
    return "{}: {}. {}".format(project, number, milestone)


def linear_project(key, name):
    """The one Linear project with this name, its milestones in Linear's order, its open issues counted
    by milestone name (None for no milestone), and their total. The project's "open" holds the keys of
    those open issues, and its "closed" the keys of the rest. Stops when there is not exactly one."""
    found = (linear(key, PROJECT_BY_NAME, {"name": name}).get("projects") or {}).get("nodes") or []
    if not found:
        fail('No Linear project named "{}" that this key can see. Nothing was written.'.format(shown(name)), 1)
    if len(found) > 1:
        fail('{} Linear projects are named "{}"; name the issues by key instead. Nothing was written.'.format(
            len(found), shown(name)), 1)
    project = dict(found[0], open=[], closed=[])
    order = sorted(project["projectMilestones"]["nodes"], key=lambda m: m["sortOrder"])
    counts, after, total = {}, None, 0
    while True:
        page = (linear(key, PROJECT_ISSUES, {"id": project["id"], "after": after}).get("project") or {}).get("issues")
        if not page:
            fail("Linear stopped answering partway through the project; nothing was written.", 1)
        for node in page["nodes"]:
            if (node.get("state") or {}).get("type") not in OPEN:
                project["closed"].append(node["identifier"])
                continue
            total += 1
            project["open"].append(node["identifier"])
            milestone = (node.get("projectMilestone") or {}).get("name")
            counts[milestone] = counts.get(milestone, 0) + 1
        if not page["pageInfo"]["hasNextPage"]:
            return project, order, counts, total
        after = page["pageInfo"]["endCursor"]


def name_from(path):
    """A Linear project's name, from the file the session wrote it to with its file tool. The name is
    written by whoever can edit the Linear project, so it is never typed into a shell command, where a
    quote or a semicolon in it would run as a command. Only the line end the file ends with is dropped.
    Never through a link: a repository could ship one at the name file's path that points at another of
    the person's files, whose text would then go to Linear and into the plan."""
    if os.path.islink(path):
        fail("The name file {} is a link, so it was not read. Remove it, write the Linear project's name "
             "there with your file tool, and run this again. Nothing was written.".format(path))
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as handle:
            name = handle.read(4096)
    except (OSError, UnicodeDecodeError) as error:
        fail("The name file {} could not be read ({}). Nothing was written.".format(
            path, getattr(error, "strerror", None) or error))
    name = name.rstrip("\r\n")
    if not name.strip():
        fail("The name file {} is empty. Write the Linear project's name into it. Nothing was written.".format(path))
    return name


def project_name(args):
    """The Linear project's name, from --project-file when given, else --project."""
    if getattr(args, "project_file", None):
        args.project = name_from(args.project_file)
    return args.project


def read_linear(args):
    key = read_key(args.key_env)
    lines = []
    if project_name(args):
        project, order, counts, total = linear_project(key, args.project)
        numbers = {m["name"]: n for n, m in enumerate(order, 1)}
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
    source = name_from(args.source_file) if args.source_file else args.source
    record = {"direction": args.direction, "source": source, "target": args.target, "access": access}
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
    """A GitHub or Linear time, such as 2026-11-03T18:27:00Z or 2026-11-03T18:27:00.715Z, as
    `November 3, 2026, 1:27 PM Eastern`."""
    from zoneinfo import ZoneInfo
    when = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
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


DIRECTIONS = {"github-to-linear": "GitHub to Linear", "linear-to-github": "Linear to GitHub"}


def saved_plan(path, direction, args):
    """The saved plan, or stop unless it is for this direction, by a key in this variable."""
    path = path or default_plan_path()
    try:
        with open(path) as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        fail("There is no saved plan at {}. Show the plan and get a yes first. Nothing was written.".format(path))
    access = record.get("access") or {}
    if record.get("direction") != direction:
        fail("The saved plan is not for {}. Nothing was written.".format(DIRECTIONS[direction]))
    if access.get("kind") != "key":
        fail("This step runs only with a Linear API key, never the connector, and the saved plan chose the "
             "connector. Ask where the key is kept, save the plan again with --access key, and get the yes "
             "again. Nothing was written.")
    if access.get("key_env") != args.key_env:
        fail("The saved plan reads the key from another variable than {}. Nothing was written.".format(args.key_env))
    return record


def load_plan(path, args):
    """Stop unless the saved plan is the person's yes to this copy: GitHub to Linear, from this
    repository and project, by a key in this variable, to this team."""
    record = saved_plan(path, "github-to-linear", args)
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
            self.found.append(lasting(url))


UPLOAD = re.compile(r"^https://private-user-images\.githubusercontent\.com/\d+/\d+-"
                    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.", re.I)


def lasting(url):
    """An uploaded image by the address written in the issue, github.com/user-attachments/assets/<id>.
    GitHub renders an upload at a private address signed for a few minutes, which is never printed."""
    upload = UPLOAD.match(url)
    if upload:
        return "https://github.com/user-attachments/assets/" + upload.group(1)
    if urllib.parse.urlparse(url).hostname == "private-user-images.githubusercontent.com":
        return "a GitHub upload whose address could not be read"
    return url


def images_in(rendered):
    """Every image GitHub shows in a body or comment, by its address, in the order shown."""
    reader = Images()
    reader.feed(rendered or "")
    reader.close()
    return reader.found


COPY_TEXT = """query($id:String!){ issue(id:$id){ title description } }"""


def without_mark(description):
    """A copy's body without its last non-blank line, the hidden line naming its GitHub issue."""
    lines = (description or "").rstrip().splitlines()
    return "\n".join(lines[:-1])


def as_written(text):
    """Text as finish compares it: every letter, digit and symbol kept, so "x > 5" and "x < 5" differ.
    Only spacing is let go, and Linear's habit of writing a link's address as `(<address>)`."""
    text = re.sub(r"\]\(<([^<>\s]+)>\)", r"](\1)", text or "")
    return " ".join(text.split())


def close_not_planned(repo, number):
    """Close one GitHub issue as not planned, with no comment: nothing is deleted and nothing names
    its Linear copy. True when gh closed it."""
    result = subprocess.run(["gh", "issue", "close", str(number), "--repo", repo, "--reason", "not planned"],
                            capture_output=True, text=True)
    return result.returncode == 0


def finish(args):
    """Check each chosen GitHub issue against its Linear copy, list every image, then close as not
    planned each issue whose copy holds the same title, body and every comment. One that does not
    stays open."""
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
        bodies = [c["body"] for c in every_page(key, COMMENTS, {"id": copies[number]}, ("issue", "comments"))]
        wanted = [comment_body(c) for c in issue["comments"]]

        def found(rule):
            """How many GitHub comments are on the copy, each Linear comment standing for one, by rule."""
            posted, count = collections.Counter(rule(b) for b in bodies), 0
            for body in wanted:
                if posted[rule(body)] > 0:
                    posted[rule(body)] -= 1
                    count += 1
            return count

        matched = found(as_written)
        linear_comments += matched
        text = linear(key, COPY_TEXT, {"id": copies[number]}).get("issue") or {}
        if matched < len(wanted) and found(same_text) == len(wanted):
            # Every comment is there by the copy's own rule, so running the copy again posts nothing:
            # the text differs, and only a hand edit mends it.
            held.append("#{} has a comment whose text differs in Linear".format(number))
        elif matched < len(wanted):
            held.append("#{} has {} of its {} comments in Linear".format(number, matched, len(wanted)))
        elif as_written(text.get("title")) != as_written(issue["title"]):
            held.append("#{} has another title in Linear".format(number))
        elif as_written(without_mark(text.get("description"))) != as_written(
                without_mark(with_mark(issue.get("body"), args.repo, number))):
            held.append("#{} has other text in Linear".format(number))
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
                     + ". Run the copy again for a missing copy or comment; where the text differs, make the "
                     "Linear copy match GitHub by hand, since the copy never rewrites one it finds. Then finish "
                     "again.")
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


# ---------------------------------------------------------------- Linear to GitHub: the structure

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PLAN_REPO = re.compile(r"^(?:github:)?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$", re.I)

REPO_PROJECTS = """query($owner:String!,$name:String!,$after:String){ repository(owner:$owner,name:$name){
  projectsV2(first:100, after:$after){ pageInfo{hasNextPage endCursor} nodes{ number } } } }"""


def load_linear_plan(path, args):
    """Stop unless the saved plan is the person's yes to this move: Linear to GitHub, from this
    Linear project (or these issue keys), by a key in this variable, to this repository."""
    record = saved_plan(path, "linear-to-github", args)
    source = str(record.get("source", ""))
    if source[:7].lower() == "linear:":
        source = source[7:]
    keys = getattr(args, "issues", None)
    if keys:
        named = {k for k in re.split(r"[\s,]+", source.strip().upper()) if k}
        if named != {k.upper() for k in keys}:
            fail('The saved plan moves "{}", not the issues {}. Nothing was written.'.format(
                shown(source.strip()), " ".join(shown(k.upper()) for k in keys)))
    elif source.strip() != args.project.strip():
        fail('The saved plan moves the Linear project "{}", not "{}". Nothing was written.'.format(
            shown(source.strip()), shown(args.project)))
    target = PLAN_REPO.match(str(record.get("target", "")).strip())
    if not target or target.group(1).lower() != args.repo.lower():
        fail('The saved plan moves to "{}", not to {}. Nothing was written.'.format(
            shown(record.get("target")), args.repo))


def gh_json(*args):
    """What a gh command prints, read as JSON, or None when gh fails."""
    result = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "null")
    except ValueError:
        return None


def gh_write(what, *args):
    """Run one gh command that writes to GitHub, or stop and say so."""
    if subprocess.run(["gh"] + list(args), capture_output=True, text=True).returncode != 0:
        fail("GitHub refused to {}. Check `gh auth status` has the project and repo scopes, then run it again; "
             "nothing is made twice.".format(what), 1)


def linked_projects(repo):
    """The numbers of the GitHub projects linked to repo, or stop."""
    owner, name = repo.split("/", 1)
    numbers, after = set(), None
    while True:
        page = ((gh_graphql(REPO_PROJECTS, owner=owner, name=name, after=after) or {}).get("repository")
                or {}).get("projectsV2")
        if not page:
            fail("gh cannot read the projects linked to {}. Nothing more was written.".format(repo), 1)
        numbers.update(node["number"] for node in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return numbers
        after = page["pageInfo"]["endCursor"]


def structure(args):
    """Make, on GitHub, the project and milestones a Linear project becomes. Writes nothing to Linear."""
    if not REPO.match(args.repo):
        fail("--repo takes <owner>/<repo>, such as acme/site.")
    project_name(args)
    load_linear_plan(args.plan, args)
    key = read_key(args.key_env)
    project, order, counts, total = linear_project(key, args.project)
    title = project["name"]
    owner = args.repo.split("/", 1)[0]
    # Each Linear milestone holding an open issue, numbered by its place among all of them, as read-linear shows.
    wanted = [(github_milestone(title, m["name"], n), m.get("description") or "", counts[m["name"]])
              for n, m in enumerate(order, 1) if counts.get(m["name"])]

    # Read GitHub before writing anything, so a refusal there writes nothing.
    listed = gh_json("project", "list", "--owner", owner, "--format", "json", "--limit", "1000")
    if listed is None:
        fail("gh cannot list the projects of {}. Check `gh auth status` has the project scope. "
             "Nothing was written.".format(owner), 1)
    same = [p for p in listed.get("projects") or [] if p.get("title") == title]
    if len(same) > 1:
        fail('{} GitHub projects of {} are named "{}". Nothing was written.'.format(len(same), owner, shown(title)), 1)
    pages = gh_json("api", "repos/{}/milestones?state=all&per_page=100".format(args.repo), "--paginate", "--slurp")
    if pages is None:
        fail("gh cannot read the milestones of {}. Nothing was written.".format(args.repo), 1)
    have = {m.get("title") for page in pages for m in page}

    if same:
        github, made_project = same[0], False
    else:
        github = gh_json("project", "create", "--owner", owner, "--title", title, "--format", "json")
        if not github or not github.get("number"):
            fail("GitHub refused to make the project. Check `gh auth status` has the project scope, then run it "
                 "again; nothing is made twice.", 1)
        made_project = True
    number = str(github["number"])

    brief, summary = project.get("content") or "", project.get("description") or ""
    edit = []
    if brief and not github.get("readme"):
        edit += ["--readme", brief]
    if summary and not github.get("shortDescription"):
        edit += ["--description", summary]
    if edit:
        gh_write("set the project's README and description", "project", "edit", number, "--owner", owner, *edit)
    linked = int(number) in linked_projects(args.repo)
    if not linked:
        gh_write("link the project to {}".format(args.repo), "project", "link", number, "--owner", owner,
                 "--repo", args.repo)

    new, kept = [], []
    for name, description, _ in wanted:
        if name in have:
            kept.append(name)
            continue
        fields = ["-f", "title=" + name] + (["-f", "description=" + description] if description else [])
        gh_write('make the milestone "{}"'.format(shown(name)), "api", "repos/{}/milestones".format(args.repo),
                 "-X", "POST", *fields)
        new.append(name)

    lines = ['GitHub project "{}" of {} (number {}): {}.'.format(
        shown(title), owner, number, "made now" if made_project else "already there"),
        "Linked to {}: {}.".format(args.repo, "already" if linked else "now")]
    if "--readme" in edit:
        lines.append("README: set from the Linear project's brief.")
    elif not brief:
        lines.append("README: the Linear project has no brief, so none was set.")
    elif github.get("readme") == brief:
        lines.append("README: already the Linear project's brief.")
    else:
        lines.append("README: GitHub already holds one, so it was left as it is.")
    if "--description" in edit:
        lines.append("Short description: set from the Linear project's summary.")
    elif not summary:
        lines.append("Short description: the Linear project has no summary, so none was set.")
    elif github.get("shortDescription") == summary:
        lines.append("Short description: already the Linear project's summary.")
    else:
        lines.append("Short description: GitHub already holds one, so it was left as it is.")
    lines.append("Milestones made now: {}.".format(
        "none" if not new else ", ".join('"{}"'.format(shown(n)) for n in new)))
    for name, _, count in wanted:
        lines.append('   milestone "{}" ({}){}'.format(shown(name), plural(count),
                                                      ", already there" if name in kept else ""))
    if not order:
        lines.append("The Linear project has no milestones, so none was made.")
    if counts.get(None):
        lines.append("   no milestone ({}): these land in the project itself, with no milestone.".format(
            plural(counts[None])))
    lines.append("Not copied yet: the {} open in Linear.".format(plural(total)))
    lines.append("Nothing was written to Linear.")
    print(hide("\n".join(lines), key))


# ---------------------------------------------------------------- Linear to GitHub: the issues

ISSUE_FULL = """query($id:String!){ issue(id:$id){ id identifier title description state{name type} team{id}
  labels(first:100){nodes{name color}} projectMilestone{name}
  project{ name projectMilestones{ nodes{ name sortOrder } } }
  parent{ identifier }
  children(first:100){ pageInfo{hasNextPage} nodes{ identifier } }
  relations(first:100){ pageInfo{hasNextPage} nodes{ type relatedIssue{ identifier } } }
  inverseRelations(first:100){ pageInfo{hasNextPage} nodes{ type issue{ identifier } } } } }"""

LINEAR_LINK_FIELDS = {"children": "sub-issues", "relations": "links from it", "inverseRelations": "links to it"}

ISSUE_COMMENTS = """query($id:String!,$after:String){ issue(id:$id){
  comments(first:100, after:$after){ pageInfo{hasNextPage endCursor}
    nodes{ body createdAt user{name} botActor{name} } } } }"""

# GitHub hands back the item already there when the issue is in the project, with its Status, so a
# second run adds nothing and leaves a Status the person changed as it is.
ADD_ITEM = """mutation($project:ID!,$content:ID!){
  addProjectV2ItemById(input:{projectId:$project, contentId:$content}){ item{ id
    fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue{ name } } } } }"""

SET_STATUS = """mutation($project:ID!,$item:ID!,$field:ID!,$option:String!){
  updateProjectV2ItemFieldValue(input:{projectId:$project, itemId:$item, fieldId:$field,
    value:{singleSelectOptionId:$option}}){ projectV2Item{ id } } }"""

# A Linear status that lands as the GitHub project Status of the same name. Needs Human lands as the
# needs-decision label with Status Todo, since an answered issue goes back to Todo.
GITHUB_STATUSES = ("Backlog", "Todo", "In Progress", "In Review")
NEEDS_DECISION = "needs-decision"
LINEAR_ISSUE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")
LINEAR_MARK = "<!-- copied from Linear {} -->"


def with_linear_mark(body, key):
    """A Linear issue's body as its GitHub copy holds it: the Linear text, then a hidden line naming the
    Linear issue, which GitHub does not show. A line like it written into the Linear text is turned into
    one no run reads, so it can never pass for this or another issue's line."""
    body = re.sub(r"<!--(\s*)copied from Linear", r"<!--\1quoted from Linear", body or "", flags=re.I).rstrip()
    mark = LINEAR_MARK.format(key)
    return "{}\n\n{}".format(body, mark) if body else mark


def linear_comment_body(comment):
    """A Linear comment as it lands on GitHub: a first line naming who wrote it in Linear, and when."""
    who = ((comment.get("user") or {}).get("name") or (comment.get("botActor") or {}).get("name")
           or "someone no longer in Linear")
    return "Written in Linear by {}, {}.\n\n{}".format(who, eastern(comment["createdAt"]), comment.get("body") or "")


def read_linear_issue(key, wanted):
    """One Linear issue with every comment, oldest first, or stop: a half-read issue is never copied."""
    node = linear(key, ISSUE_FULL, {"id": wanted}).get("issue")
    if not node:
        fail("No Linear issue {} that this key can see. Nothing was written.".format(shown(wanted)), 1)
    for field, name in LINEAR_LINK_FIELDS.items():
        if ((node.get(field) or {}).get("pageInfo") or {}).get("hasNextPage"):
            fail("Linear issue {} has more than 100 {}, more than one read holds, so a link would be lost. "
                 "Nothing was written.".format(shown(node["identifier"]), name), 1)
    node = dict(node)
    node["comments"] = sorted(every_page(key, ISSUE_COMMENTS, {"id": node["identifier"]}, ("issue", "comments")),
                              key=lambda c: c["createdAt"])
    return node


def landing(issue):
    """Where a Linear issue lands on GitHub: (GitHub project title or None, milestone title or None,
    GitHub Status or None, needs a decision). A Status lives on a GitHub project, so an issue in no
    Linear project has none."""
    project = issue.get("project") or {}
    name = project.get("name")
    milestone = (issue.get("projectMilestone") or {}).get("name")
    title = None
    if name and milestone:
        order = sorted((project.get("projectMilestones") or {}).get("nodes") or [], key=lambda m: m["sortOrder"])
        numbers = {m["name"]: n for n, m in enumerate(order, 1)}
        title = github_milestone(name, milestone, numbers.get(milestone, 0))
    state = ((issue.get("state") or {}).get("name") or "").strip().lower()
    if state == NEEDS_HUMAN.lower():
        return name, title, "Todo" if name else None, True
    return name, title, next((s for s in GITHUB_STATUSES if s.lower() == state), None) if name else None, False


def label_color(color):
    """A Linear label color, #eb5757, as GitHub takes it, eb5757; grey when it is not one."""
    color = (color or "").lstrip("#")
    return color.lower() if re.fullmatch(r"[0-9A-Fa-f]{6}", color) else "ededed"


GH_COPIES = """query($owner:String!,$name:String!,$after:String){ repository(owner:$owner,name:$name){
  issues(first:100, after:$after, states:[OPEN,CLOSED], orderBy:{field:CREATED_AT, direction:ASC}){
    pageInfo{hasNextPage endCursor} nodes{ number databaseId id body } } } }"""

GH_ISSUE = """query($owner:String!,$name:String!,$number:Int!,$after:String){ repository(owner:$owner,name:$name){
  issue(number:$number){ title body parent{ number repository{nameWithOwner} }
    blockedBy(first:100){ pageInfo{hasNextPage} nodes{ number repository{nameWithOwner} } }
    comments(first:100, after:$after){ pageInfo{hasNextPage endCursor} nodes{ body } } } } }"""


def copied_from_linear(body):
    """The Linear key a GitHub copy's hidden line names, or None when the line is gone. Only the body's
    last non-blank line counts, where the copy put it."""
    lines = [line for line in (body or "").splitlines() if line.strip()]
    found = re.fullmatch(r"\s*<!-- copied from Linear ([A-Za-z][A-Za-z0-9]*-\d+) -->\s*", lines[-1]) if lines else None
    return found.group(1).upper() if found else None


def github_copies(repo):
    """Every issue of repo, open or closed, that a copy from Linear made, by its Linear key: found by its
    hidden line only, the earliest winning. Or stop, since a copy not found would be made again."""
    owner, name = repo.split("/", 1)
    found, after = {}, None
    while True:
        page = ((gh_graphql(GH_COPIES, owner=owner, name=name, after=after) or {}).get("repository")
                or {}).get("issues")
        if not page:
            fail("gh cannot read the issues of {}, so the copies an earlier run made cannot be found. "
                 "Nothing was written.".format(repo), 1)
        for node in page["nodes"]:
            key = copied_from_linear(node.get("body"))
            if key and key not in found:
                found[key] = {"number": node["number"], "databaseId": node.get("databaseId"), "id": node.get("id")}
        if not page["pageInfo"]["hasNextPage"]:
            return found
        after = page["pageInfo"]["endCursor"]


def github_issue(repo, number):
    """One GitHub issue's title, body, parent, blocked-by links and every comment's text, or None."""
    owner, name = repo.split("/", 1)
    issue, comments, after = None, [], None
    while True:
        page = ((gh_graphql(GH_ISSUE, owner=owner, name=name, number=number, after=after) or {}).get("repository")
                or {}).get("issue")
        if not page:
            return None
        issue = issue or page
        comments += [c.get("body") or "" for c in page["comments"]["nodes"]]
        if not page["comments"]["pageInfo"]["hasNextPage"]:
            break
        after = page["comments"]["pageInfo"]["endCursor"]
    issue = dict(issue)
    issue["comments"] = comments
    return issue


def linear_links(issues):
    """The parent and blocked-by links Linear holds for these issues, by key: parents as (sub-issue,
    parent), blocks as (blocker, the issue that waits). Read from both ends, so a link is found whichever
    of its two issues a run copies. A related or duplicate link is not one GitHub holds, and is left."""
    def nodes(issue, field):
        return (issue.get(field) or {}).get("nodes") or []

    parents, blocks = set(), set()
    for issue in issues:
        me = issue["identifier"].upper()
        if issue.get("parent"):
            parents.add((me, issue["parent"]["identifier"].upper()))
        parents.update((child["identifier"].upper(), me) for child in nodes(issue, "children"))
        blocks.update((me, r["relatedIssue"]["identifier"].upper()) for r in nodes(issue, "relations")
                      if r.get("type") == "blocks")
        blocks.update((r["issue"]["identifier"].upper(), me) for r in nodes(issue, "inverseRelations")
                      if r.get("type") == "blocks")
    return parents, blocks


def make_github_links(repo, parents, blocks, copies, send):
    """Make each Linear link between two issues that both have a copy in repo, once: the sub-issue's copy
    becomes a sub-issue of the parent's copy, and the blocker's copy blocks the waiting one's. The copy may
    come from an earlier run. A copy already under another parent on GitHub is left there. Returns the
    lines to print."""
    read = {}

    def issue_at(number):
        if number not in read:
            read[number] = github_issue(repo, number)
            if read[number] is None:
                fail("gh cannot read #{} of {}, so its links were not checked. Run the copy again; nothing is "
                     "copied twice.".format(number, repo), 1)
        return read[number]

    def here(node, number):
        return (((node or {}).get("repository") or {}).get("nameWithOwner") or "").lower() == repo.lower() \
            and node.get("number") == number

    new_parents = new_blocks = 0
    missing, kept = [], []
    for child, parent in sorted(parents):
        said = "{} is a sub-issue of {}".format(shown(child), shown(parent))
        if child not in copies or parent not in copies:
            missing.append(said)
            continue
        low, high = copies[child]["number"], copies[parent]["number"]
        now = issue_at(low).get("parent")
        if here(now, high):
            continue
        if now:
            kept.append(said)
            continue
        send("make #{} a sub-issue of #{}".format(low, high),
             ["api", "repos/{}/issues/{}/sub_issues".format(repo, high), "-X", "POST"],
             {"sub_issue_id": copies[child]["databaseId"]})
        read[low]["parent"] = {"number": high, "repository": {"nameWithOwner": repo}}
        new_parents += 1
    for blocker, waits in sorted(blocks):
        if blocker not in copies or waits not in copies:
            missing.append("{} blocks {}".format(shown(blocker), shown(waits)))
            continue
        first, then = copies[blocker]["number"], copies[waits]["number"]
        held = issue_at(then)
        nodes = (held.get("blockedBy") or {}).get("nodes") or []
        if any(here(node, first) for node in nodes):
            continue
        send("mark #{} as blocked by #{}".format(then, first),
             ["api", "repos/{}/issues/{}/dependencies/blocked_by".format(repo, then), "-X", "POST"],
             {"issue_id": copies[blocker]["databaseId"]})
        held["blockedBy"] = {"nodes": nodes + [{"number": first, "repository": {"nameWithOwner": repo}}]}
        new_blocks += 1

    lines = ["Links made now: {} parent link{}, {} blocked-by link{}.".format(
        new_parents, "" if new_parents == 1 else "s", new_blocks, "" if new_blocks == 1 else "s")]
    if missing:
        lines.append("Links not made, because one side has no copy on GitHub (closed in Linear, or not copied "
                     "yet): " + "; ".join(missing) + ".")
    if kept:
        lines.append("Left as it is, because the copy already has another parent on GitHub: " + "; ".join(kept) + ".")
    return lines


def chosen_linear(args):
    """Check the arguments and the saved plan, then read every chosen Linear issue: (key, the open ones,
    each with where it lands, and the keys of the closed ones)."""
    if not REPO.match(args.repo):
        fail("--repo takes <owner>/<repo>, such as acme/site.")
    if args.issues:
        bad = [k for k in args.issues if not LINEAR_ISSUE_KEY.match(k)]
        if bad:
            fail("Not Linear issue keys, such as WEB-12: {}. Nothing was written.".format(
                ", ".join(shown(k) for k in bad)))
        # Each key once, whatever its case, so one Linear issue never becomes two GitHub issues.
        args.issues = list(dict.fromkeys(k.upper() for k in args.issues))
    else:
        project_name(args)
    load_linear_plan(args.plan, args)
    key = read_key(args.key_env)
    if args.issues:
        wanted, closed = args.issues, []
    else:
        source = linear_project(key, args.project)[0]
        wanted, closed = source["open"], list(source["closed"])
    issues = []
    for wanted_key in wanted:
        issue = read_linear_issue(key, wanted_key)
        if (issue.get("state") or {}).get("type") not in OPEN:
            closed.append(issue["identifier"])
            continue
        issue["landing"] = landing(issue)
        issues.append(issue)
    return key, issues, closed


def copy_to_github(args):
    """Copy each open Linear issue to GitHub: one issue each, with its title, body, labels and every comment,
    in its milestone and GitHub project with the same Status, then the links between them. Writes nothing to
    Linear. Run it again and nothing is copied twice."""
    key, issues, closed = chosen_linear(args)
    owner = args.repo.split("/", 1)[0]
    if not issues:
        print(hide("No open Linear issue to copy{}. Nothing was written.".format(
            ", closed in Linear: " + ", ".join(shown(k) for k in closed) if closed else ""), key))
        return

    # Read all of GitHub before writing, so a refusal or a gap writes nothing.
    listed = gh_json("project", "list", "--owner", owner, "--format", "json", "--limit", "1000")
    if listed is None:
        fail("gh cannot list the projects of {}. Check `gh auth status` has the project scope. "
             "Nothing was written.".format(owner), 1)
    projects, problems = {}, []
    for name in sorted({i["landing"][0] for i in issues if i["landing"][0]}):
        same = [p for p in listed.get("projects") or [] if p.get("title") == name]
        if len(same) != 1:
            problems.append('{} GitHub projects of {} are named "{}"'.format(len(same) or "No", owner, shown(name)))
            continue
        fields = gh_json("project", "field-list", str(same[0]["number"]), "--owner", owner, "--format", "json",
                         "--limit", "100")
        if fields is None:
            fail('gh cannot read the fields of the GitHub project "{}". Nothing was written.'.format(shown(name)), 1)
        status = [f for f in fields.get("fields") or [] if f.get("name") == "Status"]
        options = {o["name"].lower(): o["id"] for o in (status[0].get("options") or [])} if status else {}
        projects[name] = {"id": same[0]["id"], "field": status[0]["id"] if status else None, "options": options}
        needed = sorted({i["landing"][2] for i in issues if i["landing"][0] == name and i["landing"][2]})
        missing = [s for s in needed if s.lower() not in options]
        if missing:
            problems.append('the GitHub project "{}" has no Status {}; add {} to its Status field on GitHub'.format(
                shown(name), " or ".join('"{}"'.format(s) for s in missing), "it" if len(missing) == 1 else "them"))
    pages = gh_json("api", "repos/{}/milestones?state=all&per_page=100".format(args.repo), "--paginate", "--slurp")
    if pages is None:
        fail("gh cannot read the milestones of {}. Nothing was written.".format(args.repo), 1)
    milestones = {m.get("title"): m.get("number") for page in pages for m in page}
    for title in sorted({i["landing"][1] for i in issues if i["landing"][1]}):
        if title not in milestones:
            problems.append('{} has no milestone "{}"'.format(args.repo, shown(title)))
    if problems:
        fail("Nothing was written, because " + "; ".join(problems) + ". Run structure for the Linear project "
             "first, which makes the GitHub project and its milestones, then run this again.", 1)
    pages = gh_json("api", "repos/{}/labels?per_page=100".format(args.repo), "--paginate", "--slurp")
    if pages is None:
        fail("gh cannot read the labels of {}. Nothing was written.".format(args.repo), 1)
    labels = {l["name"].lower(): l["name"] for page in pages for l in page}
    # Copies an earlier run made, open or closed, found by their hidden line only.
    copies = github_copies(args.repo)

    made, before, new_comments, new_labels = [], {}, 0, 0

    def send(what, gh_args, payload):
        """One gh write, with payload as JSON on stdin; what GitHub sends back. Stops on a refusal."""
        result = subprocess.run(["gh"] + gh_args + ["--input", "-"], input=json.dumps(payload),
                                capture_output=True, text=True)
        try:
            answer = json.loads(result.stdout or "null") if result.returncode == 0 else None
        except ValueError:
            answer = None
        if answer is None:
            stopped(what)
        return answer

    def stopped(what):
        done = ", ".join("{} as #{}".format(shown(k), n) for k, n in made) or "nothing"
        fail(hide("GitHub refused to {}. Made on GitHub before it stopped: {}. Run this again once GitHub takes "
                  "the write: each copy is found by its hidden line, so nothing is copied twice.".format(what, done),
                  key), 1)

    for issue in issues:
        ident = issue["identifier"]
        project, milestone, status, held = issue["landing"]
        if ident in copies:
            # Copied by an earlier run: post only the comments it is missing, and leave the rest as it is.
            number, node_id = copies[ident]["number"], copies[ident]["id"]
            have = github_issue(args.repo, number)
            if have is None:
                stopped("show #{}, the copy of {} an earlier run made".format(number, shown(ident)))
            before[ident] = number
            posted = collections.Counter(same_text(body) for body in have["comments"])
        else:
            names = [l["name"] for l in (issue.get("labels") or {}).get("nodes") or []]
            colors = {l["name"]: l.get("color") for l in (issue.get("labels") or {}).get("nodes") or []}
            if held:
                names.append(NEEDS_DECISION)
            chosen = []
            for name in names:
                if name.lower() not in labels:
                    send('make the label "{}"'.format(shown(name)),
                         ["api", "repos/{}/labels".format(args.repo), "-X", "POST"],
                         {"name": name, "color": label_color(colors.get(name))})
                    labels[name.lower()] = name
                    new_labels += 1
                if labels[name.lower()] not in chosen:
                    chosen.append(labels[name.lower()])
            payload = {"title": issue.get("title") or "", "body": with_linear_mark(issue.get("description"), ident)}
            if chosen:
                payload["labels"] = chosen
            if milestone:
                payload["milestone"] = milestones[milestone]
            new = send("make the GitHub issue for {}".format(shown(ident)),
                       ["api", "repos/{}/issues".format(args.repo), "-X", "POST"], payload)
            if not new.get("number") or not new.get("node_id") or not new.get("id"):
                stopped("make the GitHub issue for {}".format(shown(ident)))
            number, node_id = new["number"], new["node_id"]
            made.append((ident, number))
            copies[ident] = {"number": number, "databaseId": new["id"], "id": node_id}
            posted = collections.Counter()
        # Counted, not just looked up: two comments with the same words are two comments, and each one
        # already on the copy stands for one of them.
        for comment in issue["comments"]:
            body = linear_comment_body(comment)
            if posted[same_text(body)] > 0:
                posted[same_text(body)] -= 1
                continue
            send("post a comment on #{}".format(number),
                 ["api", "repos/{}/issues/{}/comments".format(args.repo, number), "-X", "POST"], {"body": body})
            new_comments += 1
        if project:
            where = projects[project]
            item = ((gh_graphql(ADD_ITEM, project=where["id"], content=node_id) or {})
                    .get("addProjectV2ItemById") or {}).get("item")
            if not item:
                stopped('add #{} to the GitHub project "{}"'.format(number, shown(project)))
            if status and not (item.get("fieldValueByName") or {}).get("name"):
                done = gh_graphql(SET_STATUS, project=where["id"], item=item["id"], field=where["field"],
                                  option=where["options"][status.lower()])
                if not (done or {}).get("updateProjectV2ItemFieldValue"):
                    stopped("set the Status of #{}".format(number))

    # Links last, once every chosen issue has its copy; `copies` now holds every copy in the repository.
    parents, blocks = linear_links(issues)
    link_lines = make_github_links(args.repo, parents, blocks, copies, send)

    lines = ["Copied to GitHub {}: {}, {} comment{}, {} label{} made.".format(
        args.repo, plural(len(made)), new_comments, "" if new_comments == 1 else "s", new_labels,
        "" if new_labels == 1 else "s")]
    if before:
        lines.append("Already on GitHub, so not made again: {}.".format(plural(len(before))))
    for issue in issues:
        ident = issue["identifier"]
        project, milestone, status, held = issue["landing"]
        lines.append("   {} {} #{}: {}, {}, Status {}{}".format(
            shown(ident), "was already" if ident in before else "became", copies[ident]["number"],
            'project "{}"'.format(shown(project)) if project else "no project",
            'milestone "{}"'.format(shown(milestone)) if milestone else "no milestone", status or "empty",
            ", needs-decision" if held else ""))
    if closed:
        lines.append("Not copied, closed in Linear: {}.".format(", ".join(shown(k) for k in closed)))
    empty = ["{} ({})".format(shown(i["identifier"]), shown(i["state"]["name"])) for i in issues
             if i["landing"][0] and not i["landing"][2]]
    if empty:
        lines.append("Status left empty, since GitHub has no Status for their Linear one: {}.".format(", ".join(empty)))
    loose = [shown(i["identifier"]) for i in issues if not i["landing"][0]]
    if loose:
        lines.append("In no Linear project, so in no GitHub project and with no Status: {}.".format(", ".join(loose)))
    lines += link_lines
    lines.append("Nothing was written to Linear.")
    print(hide("\n".join(lines), key))


# ---------------------------------------------------------------- Linear to GitHub: the finish

TEAM_STATES = """query($id:String!){ team(id:$id){ states(first:100){ nodes{ id name type } } } }"""

CANCEL = """mutation($id:String!,$input:IssueUpdateInput!){
  issueUpdate(id:$id, input:$input){ success issue{ id } } }"""


def canceled_state(states):
    """A team's status for work that will not be done: the canceled one named Canceled, else any canceled
    one but Duplicate, which says something else. None when the team has neither."""
    gone = [s for s in states if s.get("type") == "canceled"]
    named = [s for s in gone if (s.get("name") or "").strip().lower() in ("canceled", "cancelled")]
    rest = [s for s in gone if (s.get("name") or "").strip().lower() != "duplicate"]
    return (named or rest or [None])[0]


def matched_count(wanted, bodies, rule):
    """How many of the wanted comments are among bodies, each body standing for one, compared by rule."""
    posted, count = collections.Counter(rule(b) for b in bodies), 0
    for body in wanted:
        if posted[rule(body)] > 0:
            posted[rule(body)] -= 1
            count += 1
    return count


def finish_to_github(args):
    """Check each chosen Linear issue against its GitHub copy, print the counts on both sides, then cancel
    in Linear each issue whose copy holds the same title, body and every comment. Posts nothing to Linear,
    deletes nothing, and writes nothing to GitHub. One whose copy does not match stays open, and is named."""
    key, issues, closed = chosen_linear(args)
    if not issues:
        print(hide("No open Linear issue left to finish{}. Nothing was written.".format(
            ", closed in Linear: " + ", ".join(shown(k) for k in closed) if closed else ""), key))
        return
    copies = github_copies(args.repo)

    # Each team's Canceled status, found before anything is written.
    cancel = {}
    for issue in issues:
        team = (issue.get("team") or {}).get("id")
        if team not in cancel:
            states = ((linear(key, TEAM_STATES, {"id": team}).get("team") or {}).get("states") or {}).get(
                "nodes") or [] if team else []
            cancel[team] = (canceled_state(states) or {}).get("id")
    lacking = [shown(i["identifier"]) for i in issues if not cancel[(i.get("team") or {}).get("id")]]
    if lacking:
        fail("The Linear team of {} has no Canceled status, so those issues cannot be canceled. Add one in "
             "Linear, then finish again. Nothing was written.".format(", ".join(lacking)), 1)

    linear_comments = sum(len(i["comments"]) for i in issues)
    github_comments, ready, held = 0, [], []
    for issue in issues:
        ident = issue["identifier"]
        if ident not in copies:
            held.append("{} has no copy on GitHub".format(shown(ident)))
            continue
        have = github_issue(args.repo, copies[ident]["number"])
        if have is None:
            fail("gh cannot read #{}, the copy of {}. Nothing was canceled.".format(
                copies[ident]["number"], shown(ident)), 1)
        wanted = [linear_comment_body(c) for c in issue["comments"]]
        matched = matched_count(wanted, have["comments"], as_written)
        github_comments += matched
        if matched < len(wanted) and matched_count(wanted, have["comments"], same_text) == len(wanted):
            # Every comment is there by the copy's own rule, so running the copy again posts nothing:
            # the text differs, and only a hand edit mends it.
            held.append("{} has a comment whose text differs on GitHub".format(shown(ident)))
        elif matched < len(wanted):
            held.append("{} has {} of its {} comments on GitHub".format(shown(ident), matched, len(wanted)))
        elif as_written(have.get("title")) != as_written(issue.get("title")):
            held.append("{} has another title on GitHub".format(shown(ident)))
        elif as_written(without_mark(have.get("body"))) != as_written(
                without_mark(with_linear_mark(issue.get("description"), ident))):
            held.append("{} has other text on GitHub".format(shown(ident)))
        else:
            ready.append(issue)

    copied = sum(1 for i in issues if i["identifier"] in copies)
    lines = ["Linear: {}, {} comment{}.".format(plural(len(issues)), linear_comments,
                                                "" if linear_comments == 1 else "s"),
             "GitHub: {} of them copied, {} of those comments.".format(copied, github_comments),
             "The counts match." if copied == len(issues) and github_comments == linear_comments
             else "The counts do not match yet."]
    if held:
        lines.append("Left open in Linear, because the GitHub copy does not match yet: " + "; ".join(held)
                     + ". Run copy-to-github again for a missing copy or comment; where the text differs, make the "
                     "GitHub copy match Linear by hand, since the copy never rewrites one it finds. Then finish "
                     "again.")
    canceled, refused = [], []
    for issue in ready:
        answer = linear(key, CANCEL, {"id": issue["id"],
                                      "input": {"stateId": cancel[(issue.get("team") or {}).get("id")]}})
        (canceled if (answer.get("issueUpdate") or {}).get("success") else refused).append(shown(issue["identifier"]))
    if canceled:
        lines.append("Canceled in Linear: {}.".format(", ".join(canceled)))
    if refused:
        lines.append("Linear refused to cancel: {}. Finish again.".format(", ".join(refused)))
    if closed:
        lines.append("Not checked, closed in Linear already: {}.".format(", ".join(shown(k) for k in closed)))
    lines.append("Nothing in Linear was deleted, and nothing in Linear names its GitHub copy.")
    lines.append("Nothing was written to GitHub.")
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
    which.add_argument("--project-file")
    which.add_argument("--issues", nargs="+")
    saved = sub.add_parser("plan")
    saved.add_argument("--direction", required=True, choices=["github-to-linear", "linear-to-github"])
    whence = saved.add_mutually_exclusive_group(required=True)
    whence.add_argument("--source")
    whence.add_argument("--source-file")
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
    shape = sub.add_parser("structure")
    named = shape.add_mutually_exclusive_group(required=True)
    named.add_argument("--project")
    named.add_argument("--project-file")
    shape.add_argument("--repo", required=True)
    shape.add_argument("--key-env", required=True)
    shape.add_argument("--plan")
    back = sub.add_parser("copy-to-github")
    whose = back.add_mutually_exclusive_group(required=True)
    whose.add_argument("--project")
    whose.add_argument("--project-file")
    whose.add_argument("--issues", nargs="+")
    back.add_argument("--repo", required=True)
    back.add_argument("--key-env", required=True)
    back.add_argument("--plan")
    ended = sub.add_parser("finish-to-github")
    whom = ended.add_mutually_exclusive_group(required=True)
    whom.add_argument("--project")
    whom.add_argument("--project-file")
    whom.add_argument("--issues", nargs="+")
    ended.add_argument("--repo", required=True)
    ended.add_argument("--key-env", required=True)
    ended.add_argument("--plan")
    args = parser.parse_args()
    {"read-github": read_github, "check-linear": check_linear, "read-linear": read_linear,
     "plan": plan, "copy": copy, "finish": finish, "structure": structure,
     "copy-to-github": copy_to_github, "finish-to-github": finish_to_github}[args.command](args)


if __name__ == "__main__":
    main()
