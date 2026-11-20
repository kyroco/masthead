#!/usr/bin/env python3
"""MAST-48: in a cloud session, a hook reads the facts of each repository the session attached.

A cloud session (a Project thread among them) starts in a folder that holds its
clones, not in a repository, so CLAUDE_PROJECT_DIR names no checkout and a hook
trusted none of them: the push gate printed "not this session's repository" and
ran no check. attached-repos.py records each repository the session attached in
~/.claude/cloud-session-repos, the list trusted() already reads.

Scenario 1: a repository attached at the session's start, or during it with
register_repo_root, has its committed facts read by a hook, and the push gate
counts it as the session's.
Scenario 2: a checkout the session did not attach gives no fact: a clone the
session made itself, a register_repo_root whose folder is not that repository,
and a checkout found when a session resumes or compacts.
Scenario 3: outside a cloud session nothing is recorded, and facts are read
exactly as before.

Run from anywhere: python3 hooks/tests/attached-repos-test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.dirname(HERE)
FACT = os.path.join(HOOKS, "project_fact.py")
RUN = os.path.join(HOOKS, "run.sh")

passed = 0
failed = 0


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print("FAIL {}: got {!r}, want {!r}".format(name, got, want))


GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_COUNT": "0"}


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=dict(os.environ, **GIT_ENV))


def make_repo(path, origin, check="scripts/check.sh"):
    os.makedirs(os.path.join(path, ".claude"))
    with open(os.path.join(path, ".claude", "settings.json"), "w") as handle:
        json.dump({"env": {"PROJECT_PUSH_CHECK": check, "ISSUE_TRACKER": "linear"}}, handle)
    git("init", "-q", cwd=path)
    if origin:
        git("remote", "add", "origin", origin, cwd=path)
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=path)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=path)


def base_env(tmp, cloud=True, project=None):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_", "MASTHEAD_", "GIT_CONFIG_"))}
    env.update(GIT_ENV)
    env["HOME"] = os.path.join(tmp, "root")
    env["CLAUDE_CONFIG_DIR"] = os.path.join(tmp, "root", ".claude")
    env["TMPDIR"] = tmp
    env["CLAUDE_PROJECT_DIR"] = project or os.path.join(tmp, "home")
    if cloud:
        env["CLAUDE_CODE_REMOTE"] = "true"
    return env


def hook(env, payload):
    """Run attached-repos.py the way hooks.json does, through run.sh."""
    out = subprocess.run(["bash", RUN, "attached-repos.py"], input=json.dumps(payload), env=env,
                         capture_output=True, text=True, cwd=env["CLAUDE_PROJECT_DIR"])
    return out.returncode


def fact(env, root, name="PROJECT_PUSH_CHECK"):
    out = subprocess.run([sys.executable, FACT, "--root", root, name], env=env, capture_output=True, text=True,
                         cwd=env["CLAUDE_PROJECT_DIR"])
    return out.stdout.strip()


def trusted(env, root):
    return subprocess.run([sys.executable, FACT, "--trusted", root], env=env, capture_output=True,
                          cwd=env["CLAUDE_PROJECT_DIR"]).returncode == 0


def recorded(env):
    path = os.path.join(env["CLAUDE_CONFIG_DIR"], "cloud-session-repos")
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return [line.strip() for line in handle if line.strip()]


def no_folder(env, expr, cwd):
    """What a hook that names no folder reads, such as adr_shape.folder() or state_dir()."""
    code = "import sys; sys.path.insert(0, sys.argv[1]); import project_fact as p; print(" + expr + ")"
    out = subprocess.run([sys.executable, "-c", code, HOOKS], env=env, capture_output=True, text=True, cwd=cwd)
    return out.stdout.strip()


def gate(env, name, payload, cwd):
    """'deny' or 'allow': what the hook `name`, run through run.sh, decides on `payload`."""
    out = subprocess.run(["bash", RUN, name], input=json.dumps(payload), env=env, capture_output=True, text=True,
                         cwd=cwd).stdout
    return "deny" if '"deny"' in out else "allow"


def register(env, directory, owner="kyroco", repo="masthead"):
    return hook(env, {"session_id": "s1", "hook_event_name": "PostToolUse",
                      "tool_name": "mcp__claude-code-remote__register_repo_root",
                      "tool_input": {"owner": owner, "repo": repo, "directory": directory},
                      "tool_response": {"status": "context_reload_requested"}})


def start(env, source="startup"):
    return hook(env, {"session_id": "s1", "hook_event_name": "SessionStart", "source": source})


def fresh():
    tmp = os.path.realpath(tempfile.mkdtemp())
    os.makedirs(os.path.join(tmp, "root", ".claude"))
    os.makedirs(os.path.join(tmp, "home"))
    return tmp


def main():
    # Scenario 1, during the session: register_repo_root records the clone, and its facts are read.
    tmp = fresh()
    try:
        env = base_env(tmp)
        repo = os.path.join(tmp, "home", "masthead")
        make_repo(repo, "https://github.com/kyroco/masthead")
        expect("s1: before the attach, no fact (the bug)", fact(env, repo), "")
        expect("s1: before the attach, the push gate does not trust it", trusted(env, repo), False)
        expect("s1: the hook exits 0", register(env, repo), 0)
        expect("s1: the clone is recorded", recorded(env), [repo])
        expect("s1: its push check is read", fact(env, repo), "scripts/check.sh")
        expect("s1: its tracker is read", fact(env, repo, "ISSUE_TRACKER"), "linear")
        expect("s1: the push gate trusts it", trusted(env, repo), True)
        expect("s1: a subfolder of it reads the same fact", fact(env, os.path.join(repo, ".claude")),
               "scripts/check.sh")
        wt = os.path.join(tmp, "home", "masthead-wt")
        git("worktree", "add", "-q", "-b", "wt", wt, cwd=repo)
        expect("s1: a worktree of it reads the main checkout's fact", fact(env, wt), "scripts/check.sh")
        register(env, repo)
        expect("s1: a second attach records it once", recorded(env), [repo])
        # The .git suffix and the SSH form of the same GitHub repository, and its case, name it too.
        for n, url in enumerate(("https://github.com/Kyroco/Masthead.git", "git@github.com:kyroco/masthead.git",
                                 "ssh://git@github.com/kyroco/masthead")):
            other = os.path.join(tmp, "home", "form{}".format(n))
            make_repo(other, url)
            register(env, other)
            expect("s1: origin {} names kyroco/masthead".format(url), fact(env, other), "scripts/check.sh")
    finally:
        shutil.rmtree(tmp)

    # Scenario 1, a hook that names no folder (adr_shape.folder(), state_dir() in scope-gate.py and
    # review-write-fence.py): in a cloud session whose folder holds the clones, it reads the attached repository.
    tmp = fresh()
    try:
        env = base_env(tmp)
        home = os.path.join(tmp, "home")
        repo = os.path.join(home, "masthead")
        make_repo(repo, "https://github.com/kyroco/masthead")
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as handle:
            json.dump({"env": {"ADR_DIR": "docs/adr", "PROJECT_STATE_DIR": ".kyroco"}}, handle)
        expect("s1 no folder: before the attach, the default", no_folder(env, "p.fact('ADR_DIR')", home), "None")
        register(env, repo)
        expect("s1 no folder: from the clones folder, the one attached repository's ADR_DIR",
               no_folder(env, "p.fact('ADR_DIR')", home), "docs/adr")
        expect("s1 no folder: its state folder", no_folder(env, "p.state_dir()", home), ".kyroco")
        expect("s1 no folder: its state path", no_folder(env, "p.state_path()", home), os.path.join(repo, ".kyroco"))
        expect("s1 no folder: from inside it", no_folder(env, "p.fact('ADR_DIR')", os.path.join(repo, ".claude")),
               "docs/adr")
        other = os.path.join(home, "app")
        make_repo(other, "https://github.com/kyroco/app")
        register(env, other, repo="app")
        expect("s1 no folder: two attached, from inside the second, the second's fact",
               no_folder(env, "p.fact('PROJECT_PUSH_CHECK')", other), "scripts/check.sh")
        expect("s1 no folder: two attached, from inside the first, the first's fact",
               no_folder(env, "p.fact('ADR_DIR')", repo), "docs/adr")
        expect("s1 no folder: two attached, from the clones folder, no guess",
               no_folder(env, "p.fact('ADR_DIR')", home), "None")
        stranger = os.path.join(home, "stranger")
        make_repo(stranger, "https://github.com/someone/tool", check="evil.sh")
        expect("s2 no folder: from inside a clone the session made, never its fact",
               no_folder(env, "p.fact('PROJECT_PUSH_CHECK')", stranger) != "evil.sh", True)
        env3 = base_env(tmp, cloud=False)
        expect("s3 no folder: outside a cloud session, the session folder as before",
               no_folder(env3, "p.project_root()", repo), home)
    finally:
        shutil.rmtree(tmp)

    # Scenario 1, two repositories attached: a hook that checks a file reads the facts of the repository that
    # holds that file, whichever repository it is and wherever the hook runs from (MAST-48, round 1 F1).
    tmp = fresh()
    try:
        env = base_env(tmp)
        home = os.path.join(tmp, "home")
        a = os.path.join(home, "a")
        b = os.path.join(home, "b")
        make_repo(a, "https://github.com/kyroco/a")
        make_repo(b, "https://github.com/kyroco/b")
        with open(os.path.join(a, ".claude", "settings.json"), "w") as handle:
            json.dump({"env": {"PROJECT_STATE_DIR": ".kyroco", "ADR_DIR": "docs/adr"}}, handle)
        register(env, a, repo="a")
        register(env, b, repo="b")
        os.makedirs(os.path.join(a, ".kyroco", "review"))
        os.makedirs(os.path.join(b, ".claude", "state", "review"))

        def write(path, agent=None, content="x"):
            payload = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": home,
                       "tool_input": {"file_path": path, "content": content}}
            if agent:
                payload["agent_type"] = agent
            return payload
        for cwd in (home, b):
            where = "from the clones folder" if cwd == home else "from inside B"
            expect("s1 two repos, {}: a verifier writes A's own review folder".format(where),
                   gate(env, "review-write-fence.py",
                        write(os.path.join(a, ".kyroco", "review", "findings-verifier-x.json"), "verifier"), cwd),
                   "allow")
            expect("s1 two repos, {}: and not A's default folder".format(where),
                   gate(env, "review-write-fence.py",
                        write(os.path.join(a, ".claude", "state", "review", "findings-verifier-x.json"), "verifier"),
                        cwd), "deny")
            expect("s1 two repos, {}: a verifier writes B's default review folder".format(where),
                   gate(env, "review-write-fence.py",
                        write(os.path.join(b, ".claude", "state", "review", "findings-verifier-y.json"), "verifier"),
                        cwd), "allow")
            expect("s1 two repos, {}: scratch under A's own review folder".format(where),
                   gate(env, "review-write-fence.py",
                        write(os.path.join(a, ".kyroco", "review", "scratch", "probe.sh"), "verifier"), cwd), "allow")
        # A's scope file, in A's own state folder, holds an edit to A.
        os.makedirs(os.path.join(a, "src"))
        with open(os.path.join(a, ".kyroco", "scope.json"), "w") as handle:
            json.dump({"allowed_paths": ["src/a.py"]}, handle)
        for cwd in (home, b):
            where = "from the clones folder" if cwd == home else "from inside B"
            expect("s1 two repos, {}: A's scope allows src/a.py".format(where),
                   gate(env, "scope-gate.py", write(os.path.join(a, "src", "a.py")), cwd), "allow")
            expect("s1 two repos, {}: A's scope refuses src/b.py".format(where),
                   gate(env, "scope-gate.py", write(os.path.join(a, "src", "b.py")), cwd), "deny")
            expect("s1 two repos, {}: B has no scope file, so B is free".format(where),
                   gate(env, "scope-gate.py", write(os.path.join(b, "src", "b.py")), cwd), "allow")
        os.remove(os.path.join(a, ".kyroco", "scope.json"))
        # A opted in to ADRs in docs/adr; a new record there with no sections is refused, and B is not opted in.
        for cwd in (home, b):
            where = "from the clones folder" if cwd == home else "from inside B"
            expect("s1 two repos, {}: A's ADR folder holds a new record to its shape".format(where),
                   gate(env, "adr-sections-gate.py", write(os.path.join(a, "docs", "adr", "0001-x.md"),
                                                           content="# Title\n\nNothing else.\n"), cwd), "deny")
            expect("s1 two repos, {}: B is not opted in".format(where),
                   gate(env, "adr-sections-gate.py", write(os.path.join(b, "docs", "adr", "0001-x.md"),
                                                           content="# Title\n\nNothing else.\n"), cwd), "allow")
    finally:
        shutil.rmtree(tmp)

    # Scenario 1, at the start: a clone already in the session's folder when it starts is recorded.
    tmp = fresh()
    try:
        env = base_env(tmp)
        repo = os.path.join(tmp, "home", "app")
        make_repo(repo, "https://github.com/kyroco/app")
        os.makedirs(os.path.join(tmp, "home", "notes"))
        expect("s1 start: the hook exits 0", start(env), 0)
        expect("s1 start: the clone is recorded, the plain folder is not", recorded(env), [repo])
        expect("s1 start: its push check is read", fact(env, repo), "scripts/check.sh")
    finally:
        shutil.rmtree(tmp)

    # Scenario 1, at the start, when the session's folder is the repository itself: as before.
    tmp = fresh()
    try:
        repo = os.path.join(tmp, "home", "solo")
        make_repo(repo, "https://github.com/kyroco/solo")
        env = base_env(tmp, project=repo)
        start(env)
        expect("s1 solo: its push check is read", fact(env, repo), "scripts/check.sh")
    finally:
        shutil.rmtree(tmp)

    # Scenario 2: checkouts the session did not attach.
    tmp = fresh()
    try:
        env = base_env(tmp)
        start(env)
        stranger = os.path.join(tmp, "home", "stranger")
        make_repo(stranger, "https://github.com/someone/tool")
        expect("s2: a clone made after the start gives no fact", fact(env, stranger), "")
        expect("s2: the push gate does not trust it", trusted(env, stranger), False)
        register(env, stranger, owner="kyroco", repo="masthead")
        expect("s2: register_repo_root naming another repository records nothing", recorded(env) or [], [])
        expect("s2: and it still gives no fact", fact(env, stranger), "")
        noremote = os.path.join(tmp, "home", "noremote")
        make_repo(noremote, None)
        register(env, noremote, owner="kyroco", repo="noremote")
        expect("s2: a folder with no origin records nothing", recorded(env) or [], [])
        attached = os.path.join(tmp, "home", "masthead")
        make_repo(attached, "https://github.com/kyroco/masthead")
        register(env, os.path.join(attached, ".claude"))
        expect("s2: a subfolder named as the directory records nothing", recorded(env) or [], [])
        register(env, os.path.join(tmp, "home"))
        expect("s2: the session folder named as the directory records nothing", recorded(env) or [], [])
        for source in ("resume", "compact", "clear"):
            start(env, source)
            expect("s2: a SessionStart from {} records nothing".format(source), recorded(env) or [], [])
        expect("s2: a non-JSON payload exits 0", subprocess.run(["bash", RUN, "attached-repos.py"], input="x",
               env=env, capture_output=True, text=True).returncode, 0)
    finally:
        shutil.rmtree(tmp)

    # Scenario 2, a skill through the Bash tool, which sets no CLAUDE_PROJECT_DIR: run from inside a clone the
    # session made, the skill flags never read that clone's settings (Korium c394a752, rule 2).
    tmp = fresh()
    try:
        env = base_env(tmp)
        home = os.path.join(tmp, "home")
        repo = os.path.join(home, "masthead")
        make_repo(repo, "https://github.com/kyroco/masthead")
        register(env, repo)
        stranger = os.path.join(home, "stranger")
        make_repo(stranger, "https://github.com/someone/tool")
        with open(os.path.join(stranger, ".claude", "settings.json"), "w") as handle:
            json.dump({"env": {"ISSUE_TRACKER": "linear", "PROJECT_STATE_DIR": "stranger-state"}}, handle)
        shell = dict(env)
        del shell["CLAUDE_PROJECT_DIR"]

        def flag(name, cwd):
            return subprocess.run([sys.executable, FACT, name], env=shell, capture_output=True, text=True,
                                  cwd=cwd).stdout.strip()
        expect("s2 shell: --tracker from inside a stranger clone is not its value", flag("--tracker", stranger),
               "github")
        expect("s2 shell: --state-path from inside a stranger clone is not its folder",
               flag("--state-path", stranger), os.path.join(stranger, ".claude/state"))
        expect("s1 shell: --tracker from inside the attached repository", flag("--tracker", repo), "linear")
        expect("s1 shell: --tracker from the clones folder, one repository attached", flag("--tracker", home),
               "linear")
        expect("s1 shell: --state-path from the clones folder, one repository attached",
               flag("--state-path", home), os.path.join(repo, ".claude/state"))
        terminal = {k: v for k, v in shell.items() if k != "CLAUDE_CODE_REMOTE"}
        expect("s3 shell: in a terminal, the shell's checkout is the session's, as before",
               subprocess.run([sys.executable, FACT, "--state-path"], env=terminal, capture_output=True, text=True,
                              cwd=stranger).stdout.strip(), os.path.join(stranger, "stranger-state"))
    finally:
        shutil.rmtree(tmp)

    # Scenario 3: a terminal or desktop session records nothing and reads facts as before.
    tmp = fresh()
    try:
        repo = os.path.join(tmp, "home", "masthead")
        make_repo(repo, "https://github.com/kyroco/masthead")
        env = base_env(tmp, cloud=False)
        start(env)
        register(env, repo)
        expect("s3: nothing is recorded", recorded(env), None)
        expect("s3: a repository that is not the session's gives no fact", fact(env, repo), "")
        env = base_env(tmp, cloud=False, project=repo)
        expect("s3: the session's own repository gives its fact", fact(env, repo), "scripts/check.sh")
    finally:
        shutil.rmtree(tmp)

    # The wiring: hooks.json runs it after register_repo_root and at the start of a session.
    with open(os.path.join(HOOKS, "hooks.json")) as handle:
        wiring = json.load(handle)["hooks"]

    def wired(event, matcher):
        return any(group.get("matcher") == matcher and
                   any(h["command"].endswith('run.sh" attached-repos.py') for h in group["hooks"])
                   for group in wiring.get(event, []))
    expect("wiring: after register_repo_root", wired("PostToolUse", "mcp__.*__register_repo_root"), True)
    expect("wiring: at session start", wired("SessionStart", "startup"), True)

    print("{} passed, {} failed".format(passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
