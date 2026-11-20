#!/usr/bin/env python3
"""MAST-48: one repo_root() decides which repository a hook or a skill is about, Masthead wide.

The folder Claude Code starts in, the workspace, is often not a repository: a Project thread starts in
/home/user, which holds the clone, and Robert starts the CLI in ~/projects, which holds his repositories.
Before this, a hook trusted only the workspace itself, so there it read every fact as its default and the
push gate printed "not this session's repository" and ran no check.

repo_root(path, cwd), Robert's design of November 20, 2026:
1. a file path: the checkout that holds it;
2. otherwise the checkout that holds the shell's folder;
3. the workspace itself, when it holds exactly one repository;
4. otherwise the repository is unclear, and Masthead says so in one line.
A fact is read only from one of the workspace's repositories: the workspace when it is a checkout, else each
checkout directly inside it, a worktree counting as its main checkout.

Run from anywhere: python3 hooks/tests/repo-root-test.py
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
SKILLS = os.path.join(os.path.dirname(HOOKS), "skills")
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


def make_repo(path, env=None):
    os.makedirs(os.path.join(path, ".claude"), exist_ok=True)
    with open(os.path.join(path, ".claude", "settings.json"), "w") as handle:
        json.dump({"env": env or {"PROJECT_PUSH_CHECK": "scripts/check.sh", "ISSUE_TRACKER": "linear"}}, handle)
    git("init", "-q", cwd=path)
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=path)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=path)


def env_for(tmp, workspace):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "MASTHEAD_", "GIT_CONFIG_"))}
    env.update(GIT_ENV)
    env["HOME"] = os.path.join(tmp, "root")
    env["CLAUDE_CONFIG_DIR"] = os.path.join(tmp, "root", ".claude")
    env["TMPDIR"] = tmp
    if workspace:
        env["CLAUDE_PROJECT_DIR"] = workspace
    return env


def root_of(env, path=None, cwd=None):
    """repo_root() as a hook calls it: the folder, or 'unclear: <its line>'."""
    code = ("import sys, json; sys.path.insert(0, sys.argv[1]); import project_fact as p\n"
            "a = json.loads(sys.argv[2])\n"
            "try:\n    print(p.repo_root(a['path'], a['cwd']))\n"
            "except p.RepoUnclear as e:\n    print('unclear: ' + str(e))\n")
    out = subprocess.run([sys.executable, "-c", code, HOOKS, json.dumps({"path": path, "cwd": cwd})],
                         env=env, capture_output=True, text=True, cwd=cwd or env.get("CLAUDE_PROJECT_DIR") or "/")
    return out.stdout.strip() or out.stderr.strip()


def cli(env, args, cwd):
    out = subprocess.run([sys.executable, FACT, *args], env=env, capture_output=True, text=True, cwd=cwd)
    return out.returncode, out.stdout.strip(), out.stderr.strip()


def hook(env, name, payload, cwd):
    out = subprocess.run(["bash", RUN, name], input=json.dumps(payload), env=env, capture_output=True, text=True,
                         cwd=cwd)
    return "deny" if '"deny"' in out.stdout else "allow"


def push_gate(env, payload, cwd):
    """The push gate's exit code and what it printed for the session."""
    out = subprocess.run(["bash", RUN, "hard-gate.sh"], input=json.dumps(payload), env=env, capture_output=True,
                         text=True, cwd=cwd)
    return out.returncode, out.stderr.strip()


def connector_pr(cwd):
    return {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "mcp__github__create_pull_request",
            "cwd": cwd, "tool_input": {"title": "t", "body": "b", "head": "x", "base": "main"}}


def skill_env(env):
    """A skill's shell: no CLAUDE_PROJECT_DIR, and the workspace session start wrote to CLAUDE_ENV_FILE."""
    shell = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
    shell["MASTHEAD_WORKSPACE"] = env["CLAUDE_PROJECT_DIR"]
    return shell


def prime(env, mode, cwd, args=()):
    """What prime-context.py prints for the session in MODE."""
    payload = {"session_id": "s1", "hook_event_name": "SessionStart", "cwd": cwd}
    out = subprocess.run(["bash", RUN, "prime-context.py", mode, *args], input=json.dumps(payload), env=env,
                         capture_output=True, text=True, cwd=cwd)
    return out.stdout


def write(path, cwd, agent=None, content="x"):
    payload = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": cwd,
               "tool_input": {"file_path": path, "content": content}}
    if agent:
        payload["agent_type"] = agent
    return payload


def fresh():
    tmp = os.path.realpath(tempfile.mkdtemp())
    os.makedirs(os.path.join(tmp, "root", ".claude"))
    return tmp


def main():
    # A workspace that holds one repository: a Project thread's /home/user.
    tmp = fresh()
    try:
        home = os.path.join(tmp, "home")
        repo = os.path.join(home, "masthead")
        os.makedirs(repo)
        make_repo(repo)
        os.makedirs(os.path.join(home, "notes"))
        env = env_for(tmp, home)
        expect("one repo, step 1: a file in it", root_of(env, os.path.join(repo, "hooks", "new.py"), home), repo)
        expect("one repo, step 2: the shell inside it", root_of(env, None, os.path.join(repo, ".claude")), repo)
        expect("one repo, step 3: the shell in the workspace", root_of(env, None, home), repo)
        expect("one repo, step 3: a file in no repository, the shell in the workspace",
               root_of(env, os.path.join(home, "notes", "a.txt"), home), repo)
        expect("one repo: the push gate trusts it (the bug)", cli(env, ["--trusted", repo], home)[0], 0)
        expect("one repo: a hook reads its push check", cli(env, ["--root", repo, "PROJECT_PUSH_CHECK"], home)[1],
               "scripts/check.sh")
        shell = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
        expect("one repo: a skill from the workspace reads its tracker", cli(shell, ["--tracker"], home)[1], "linear")
        expect("one repo: a skill from inside it reads its tracker", cli(shell, ["--tracker"], repo)[1], "linear")
        env_file = os.path.join(tmp, "claude-env")
        open(env_file, "w").close()
        prime(dict(env, CLAUDE_PLUGIN_OPTION_KORIUM="off", CLAUDE_ENV_FILE=env_file), "session-start", home)
        with open(env_file) as handle:
            written = handle.read()
        expect("one repo: session start hands the workspace to the skills' shell through CLAUDE_ENV_FILE",
               "export MASTHEAD_WORKSPACE=" + home in written, True)
        expect("one repo: the session starts with no unclear line",
               "unclear" in prime(dict(env, CLAUDE_PLUGIN_OPTION_KORIUM="off"), "session-start", home), False)
        os.makedirs(os.path.join(repo, ".claude", "references"))
        with open(os.path.join(repo, ".claude", "references", "session-cliffs.md"), "w") as handle:
            handle.write("**Opening a PR.** The repository's own steps.\n")
        expect("one repo: from the workspace, a worker reads the repository's own PR steps",
               "own steps" in prime(shell, "show", home, ["Opening a PR"]), True)
        # A skill script finds the repository from the workspace too: bad-commit reads its stored Gate.
        os.makedirs(os.path.join(repo, ".github", "workflows"))
        with open(os.path.join(repo, ".github", "workflows", "gate.yml"), "w") as handle:
            handle.write("name: Gate\non: [workflow_call]\njobs: {}\n")
        with open(os.path.join(repo, ".claude", "gate.json"), "w") as handle:
            json.dump({"workflow": ".github/workflows/gate.yml", "starts": ["workflow_call"]}, handle)
        git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "gate", cwd=repo)
        said = subprocess.run([sys.executable, os.path.join(SKILLS, "work-on", "bad-commit.py"), "1"],
                              env=skill_env(env), cwd=home, capture_output=True, text=True)
        expect("one repo: bad-commit from the workspace reads the repository's stored Gate",
               "workflow_dispatch" in said.stdout + said.stderr, True)
        # A worktree outside the workspace counts as its main checkout.
        wt = os.path.join(tmp, "wt")
        git("worktree", "add", "-q", "-b", "wt", wt, cwd=repo)
        expect("one repo: a file in its worktree", root_of(env, os.path.join(wt, "a.py"), home), wt)
        expect("one repo: its worktree is trusted", cli(env, ["--trusted", wt], home)[0], 0)
        expect("one repo: its worktree reads the main checkout's fact",
               cli(env, ["--root", wt, "PROJECT_PUSH_CHECK"], home)[1], "scripts/check.sh")
        # A clone outside the workspace is never read (scenario 2).
        stranger = os.path.join(tmp, "elsewhere", "tool")
        os.makedirs(stranger)
        make_repo(stranger, {"PROJECT_PUSH_CHECK": "evil.sh", "ISSUE_TRACKER": "linear"})
        expect("stranger: step 1 names it", root_of(env, os.path.join(stranger, "x"), home), stranger)
        expect("stranger: not trusted", cli(env, ["--trusted", stranger], home)[0], 1)
        expect("stranger: no fact from it", cli(env, ["--root", stranger, "PROJECT_PUSH_CHECK"], home)[1], "")
        # The review fence and the scope gate read the repository's own state folder (step 1).
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as handle:
            json.dump({"env": {"PROJECT_STATE_DIR": ".kyroco", "ADR_DIR": "docs/adr"}}, handle)
        os.makedirs(os.path.join(repo, ".kyroco", "review"))
        expect("fence: a verifier writes the repository's own review folder",
               hook(env, "review-write-fence.py",
                    write(os.path.join(repo, ".kyroco", "review", "findings-verifier-x.json"), home, "verifier"), home),
               "allow")
        expect("fence: and not the default one",
               hook(env, "review-write-fence.py",
                    write(os.path.join(repo, ".claude", "state", "review", "findings-verifier-x.json"), home,
                          "verifier"), home), "deny")
        os.makedirs(os.path.join(repo, "src"))
        with open(os.path.join(repo, ".kyroco", "scope.json"), "w") as handle:
            json.dump({"allowed_paths": ["src/a.py"]}, handle)
        expect("scope: the repository's scope allows src/a.py",
               hook(env, "scope-gate.py", write(os.path.join(repo, "src", "a.py"), home), home), "allow")
        expect("scope: and refuses src/b.py",
               hook(env, "scope-gate.py", write(os.path.join(repo, "src", "b.py"), home), home), "deny")
        os.remove(os.path.join(repo, ".kyroco", "scope.json"))
        expect("ADR: a new record in the repository's ADR folder is held to its shape",
               hook(env, "adr-sections-gate.py",
                    write(os.path.join(repo, "docs", "adr", "0001-x.md"), home, content="# T\n\nNothing.\n"), home),
               "deny")
    finally:
        shutil.rmtree(tmp)

    # A workspace that holds several repositories: Robert's ~/projects.
    tmp = fresh()
    try:
        projects = os.path.join(tmp, "projects")
        a = os.path.join(projects, "a")
        b = os.path.join(projects, "b")
        for r in (a, b):
            os.makedirs(r)
            make_repo(r)
        env = env_for(tmp, projects)
        expect("two repos, step 1: a file in A", root_of(env, os.path.join(a, "x.py"), projects), a)
        expect("two repos, step 2: the shell in B", root_of(env, None, b), b)
        expect("two repos, step 4: the shell in the workspace is unclear",
               root_of(env, None, projects).startswith("unclear: "), True)
        expect("two repos: A is trusted", cli(env, ["--trusted", a], projects)[0], 0)
        expect("two repos: B's push check is read", cli(env, ["--root", b, "PROJECT_PUSH_CHECK"], projects)[1],
               "scripts/check.sh")
        shell = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
        code, out, err = cli(shell, ["--tracker"], projects)
        expect("two repos: a skill from the workspace stops", code != 0, True)
        expect("two repos: and prints nothing on stdout", out, "")
        expect("two repos: its line says the repository is unclear and names the workspace",
               "unclear" in err and projects in err and len(err.splitlines()) == 1, True)
        expect("two repos: a skill from inside A reads A", cli(shell, ["--tracker"], a)[1], "linear")
        # A skill's shell knows the workspace from session start, so a plain subfolder or a stray clone in one
        # is not taken for the workspace.
        notes = os.path.join(projects, "notes")
        old = os.path.join(projects, "archive", "old")
        os.makedirs(notes)
        os.makedirs(old)
        make_repo(old, {"ISSUE_TRACKER": "linear", "PROJECT_WARM_BUILD": "touch STRANGER_RAN"})
        code, out, err = cli(skill_env(env), ["--tracker"], notes)
        expect("two repos: a skill in a plain subfolder stops", (code != 0, out), (True, ""))
        expect("two repos: and its line names the real workspace and its two repositories",
               projects + " holds 2 repositories" in err, True)
        expect("two repos: a skill inside a stray clone in a subfolder reads none of its facts",
               cli(skill_env(env), ["--tracker"], old)[1], "github")
        subprocess.run(["bash", os.path.join(SKILLS, "work-on", "warm-build.sh"), "build"], env=skill_env(env),
                       cwd=old, capture_output=True, text=True)
        expect("two repos: warm-build in that stray clone never runs its command",
               os.path.exists(os.path.join(old, "STRANGER_RAN")), False)
        said = prime(dict(env, CLAUDE_PLUGIN_OPTION_KORIUM="off"), "session-start", projects)
        expect("two repos: the session starts with the one line saying the repository is unclear, once",
               [line for line in said.splitlines() if "unclear" in line] != [] and said.count("unclear") == 1, True)
        # With the shell in the workspace, a hook that is given a file finds its repository by the file (step 1).
        with open(os.path.join(a, ".claude", "settings.json"), "w") as handle:
            json.dump({"env": {"PROJECT_STATE_DIR": ".kyroco", "ADR_DIR": "docs/adr"}}, handle)
        os.makedirs(os.path.join(a, ".kyroco", "review"))
        expect("two repos, fence: a verifier writes A's own review folder",
               hook(env, "review-write-fence.py",
                    write(os.path.join(a, ".kyroco", "review", "findings-verifier-x.json"), projects, "verifier"),
                    projects), "allow")
        os.makedirs(os.path.join(a, "src"))
        with open(os.path.join(a, ".kyroco", "scope.json"), "w") as handle:
            json.dump({"allowed_paths": ["src/a.py"]}, handle)
        expect("two repos, scope: A's scope refuses src/b.py",
               hook(env, "scope-gate.py", write(os.path.join(a, "src", "b.py"), projects), projects), "deny")
        os.remove(os.path.join(a, ".kyroco", "scope.json"))
        # A pull request opened from the workspace names no repository: the push gate refuses, never passing
        # with no checks run.
        code, err = push_gate(env, connector_pr(projects), projects)
        expect("two repos, push gate: a pull request from the workspace is refused", code, 2)
        expect("two repos, push gate: and says the repository is unclear", "unclear" in err, True)
        expect("two repos, ADR: a new record in A's ADR folder is held to its shape",
               hook(env, "adr-sections-gate.py",
                    write(os.path.join(a, "docs", "adr", "0001-x.md"), projects, content="# T\n\nNothing.\n"),
                    projects), "deny")
    finally:
        shutil.rmtree(tmp)

    # One repository and a worktree of it, side by side in the workspace: still one repository (step 3).
    tmp = fresh()
    try:
        home = os.path.join(tmp, "home")
        repo = os.path.join(home, "masthead")
        os.makedirs(repo)
        make_repo(repo)
        git("worktree", "add", "-q", "-b", "side", os.path.join(home, "masthead-side"), cwd=repo)
        env = env_for(tmp, home)
        expect("repo and sibling worktree, step 3: the shell in the workspace is the repository",
               root_of(env, None, home), repo)
        shell = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
        expect("repo and sibling worktree: a skill from the workspace reads its tracker",
               cli(shell, ["--tracker"], home)[1], "linear")
    finally:
        shutil.rmtree(tmp)

    # One repository in the workspace: a pull request opened from the workspace is checked in it.
    tmp = fresh()
    try:
        home = os.path.join(tmp, "home")
        repo = os.path.join(home, "masthead")
        os.makedirs(repo)
        make_repo(repo, {"PROJECT_PUSH_CHECK": "check.sh"})
        with open(os.path.join(repo, "check.sh"), "w") as handle:
            handle.write("echo the-push-check-ran >&2\nexit 1\n")
        git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "check", cwd=repo)
        code, err = push_gate(env_for(tmp, home), connector_pr(home), home)
        expect("one repo, push gate: a pull request from the workspace runs the repository's push check",
               "the-push-check-ran" in err, True)
    finally:
        shutil.rmtree(tmp)

    # A workspace that holds no repository.
    tmp = fresh()
    try:
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        env = env_for(tmp, empty)
        expect("no repo, step 4: unclear", root_of(env, None, empty).startswith("unclear: "), True)
        shell = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
        expect("no repo: a skill stops", cli(shell, ["--state-path"], empty)[0] != 0, True)
    finally:
        shutil.rmtree(tmp)

    # A terminal session started in the repository: exactly as before (scenario 3).
    tmp = fresh()
    try:
        repo = os.path.join(tmp, "kyroco")
        os.makedirs(repo)
        make_repo(repo)
        nested = os.path.join(repo, "deps", "lib")
        os.makedirs(nested)
        make_repo(nested, {"PROJECT_PUSH_CHECK": "evil.sh"})
        env = env_for(tmp, repo)
        expect("terminal: the shell in it", root_of(env, None, repo), repo)
        expect("terminal: its push check", cli(env, ["--root", repo, "PROJECT_PUSH_CHECK"], repo)[1],
               "scripts/check.sh")
        expect("terminal: a clone nested inside it is not trusted", cli(env, ["--trusted", nested], repo)[0], 1)
        expect("terminal: and gives no fact", cli(env, ["--root", nested, "PROJECT_PUSH_CHECK"], repo)[1], "")
        shell = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
        expect("terminal: a skill from inside it", cli(shell, ["--tracker"], repo)[1], "linear")
        # A hook that names no root reads the repository from its own folder, a subfolder included.
        os.makedirs(os.path.join(repo, "lib"))
        expect("terminal: a hook in a subfolder reads the fact with no root",
               cli(env, ["PROJECT_PUSH_CHECK"], os.path.join(repo, "lib"))[1], "scripts/check.sh")
        # Its worktrees, inside or beside it, are trusted; a clone beside it is not.
        inner = os.path.join(repo, ".claude", "worktrees", "w")
        git("worktree", "add", "-q", "-b", "w", inner, cwd=repo)
        expect("terminal: a worktree inside it is trusted", cli(env, ["--trusted", inner], repo)[0], 0)
        expect("terminal: and reads the main checkout's fact", cli(env, ["--root", inner, "PROJECT_PUSH_CHECK"], repo)[1],
               "scripts/check.sh")
        sibling = os.path.join(tmp, "sibling")
        os.makedirs(sibling)
        make_repo(sibling, {"PROJECT_PUSH_CHECK": "evil.sh"})
        expect("terminal: a clone beside it is not trusted", cli(env, ["--trusted", sibling], repo)[0], 1)
        # Step 1: a record written in a worktree belongs to that worktree, so the ADR gate reads the architecture
        # doc on the worktree's own branch.
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as handle:
            json.dump({"env": {"PROJECT_PUSH_CHECK": "scripts/check.sh", "ARCHITECTURE_DOC": "docs/arch.md"}}, handle)
        os.makedirs(os.path.join(inner, "docs"), exist_ok=True)
        open(os.path.join(inner, "docs", "arch.md"), "w").close()
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import adr_shape\n"
                "print(adr_shape.architecture_doc(adr_shape.repo_of(sys.argv[2]))[0])\n")
        doc = subprocess.run([sys.executable, "-c", code, HOOKS, os.path.join(inner, "docs", "adr", "0001-x.md")],
                             env=env, capture_output=True, text=True, cwd=repo).stdout.strip()
        expect("terminal: an ADR in a worktree is held to the worktree's own architecture doc",
               doc, os.path.join(inner, "docs", "arch.md"))
        expect("terminal: a session started in a subfolder trusts the repository",
               cli(dict(env, CLAUDE_PROJECT_DIR=os.path.join(repo, "lib")), ["--trusted", repo], repo)[0], 0)
    finally:
        shutil.rmtree(tmp)

    # No per-session list is read: a cloud-session-repos file names nothing a hook trusts.
    tmp = fresh()
    try:
        projects = os.path.join(tmp, "projects")
        os.makedirs(projects)
        listed = os.path.join(tmp, "listed")
        os.makedirs(listed)
        make_repo(listed)
        with open(os.path.join(tmp, "root", ".claude", "cloud-session-repos"), "w") as handle:
            handle.write(listed + "\n")
        env = dict(env_for(tmp, projects), CLAUDE_CODE_REMOTE="true")
        expect("no list: a repository named in cloud-session-repos is not trusted",
               cli(env, ["--trusted", listed], projects)[0], 1)
    finally:
        shutil.rmtree(tmp)

    print("{} passed, {} failed".format(passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
