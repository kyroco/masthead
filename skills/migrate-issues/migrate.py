#!/usr/bin/env python3
"""The first step of /masthead:migrate-issues: look, ask, and write nothing.

usage:
  migrate.py read-github --repo <owner>/<repo> --project <number>
  migrate.py check-linear --key-env <NAME> [--team <KEY>]
  migrate.py read-linear --key-env <NAME> (--project <name> | --issues <KEY>...)
  migrate.py plan --direction github-to-linear|linear-to-github
                  --source <what> --target <where>
                  --access key|connector [--key-env <NAME> --kept <where>]
                  [--out <file>]

read-github reads one repository's open issues in one of its GitHub projects
through `gh`, and prints what they become in Linear: one Linear project with
the GitHub project's name, each milestone a milestone inside it. Issues the
project holds from other repositories are left out. check-linear asks Linear
who the key belongs to, and whether a team exists. read-linear reads a Linear
project, or issues named by key, and prints what each becomes on GitHub. plan
saves what the person agreed to. None of them writes to GitHub or Linear.

The Linear key is read from the environment variable the person names, at run
time. It is never printed, logged or saved: everything Linear sends back is
shown with the key hidden, and the plan file holds only where the key is kept.
"""
import argparse
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


def read_project(repo, number):
    """The project's title and the milestones of its open issues in repo, or None when gh cannot see it."""
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
                milestones.append((content.get("milestone") or {}).get("title"))
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
        title, args.repo, len(named), "" if len(named) == 1 else "s", len(milestones), "" if len(milestones) == 1 else "s"), ""]
    lines.append("In Linear it becomes one project with the same name, each milestone a milestone inside it:")
    lines.append('   Linear project "{}"'.format(title))
    for name in named:
        lines.append('     milestone "{}" ({})'.format(inside(title, name), plural(counts[name])))
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


SEND = urllib.request.build_opener(NoRedirect)


def linear(key, query, variables=None):
    """Send one read to Linear. Returns its data, or stops with its error, the key hidden."""
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
    print(hide('Linear answers: the key belongs to {} in the workspace "{}".'.format(viewer, org.get("name", "-")), key))
    if args.team:
        teams = (data.get("teams") or {}).get("nodes") or []
        if not teams:
            fail('No Linear team with the key "{}" in that workspace.'.format(args.team.upper()), 1)
        print(hide('It can see the team "{}" ({}).'.format(teams[0]["name"], teams[0]["key"]), key))


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
            project["name"], len(order), "" if len(order) == 1 else "s", total, "" if total == 1 else "s"))
        lines.append("")
        lines.append("On GitHub the structure stays as it is:")
        lines.append('   GitHub project "{}", with its brief as the project README'.format(project["name"]))
        for m in order:
            if counts.get(m["name"]):
                lines.append('     milestone "{}" ({})'.format(
                    github_milestone(project["name"], m["name"], numbers[m["name"]]), plural(counts[m["name"]])))
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
            place = 'GitHub project "{}"'.format(project) if project else "no project"
            if project and milestone:
                order = sorted(((node.get("project") or {}).get("projectMilestones") or {}).get("nodes") or [],
                               key=lambda m: m["sortOrder"])
                numbers = {m["name"]: n for n, m in enumerate(order, 1)}
                place += ', milestone "{}"'.format(github_milestone(project, milestone, numbers.get(milestone, 0)))
            if (node.get("state") or {}).get("type") not in OPEN:
                place += " (closed in Linear)"
            lines.append("   {}: {}".format(node["identifier"], place))
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
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as out:
        json.dump(record, out, indent=2)
        out.write("\n")
    os.chmod(path, 0o600)
    print("Saved the plan to {}. Nothing has been written to GitHub or Linear.".format(path))


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
    args = parser.parse_args()
    {"read-github": read_github, "check-linear": check_linear, "read-linear": read_linear,
     "plan": plan}[args.command](args)


if __name__ == "__main__":
    main()
