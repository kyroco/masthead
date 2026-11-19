#!/usr/bin/env python3
"""A stand-in for `gh` that answers the few GitHub calls setup's batch.py makes (INFRA-272).

It keeps a pretend repository on GitHub in the JSON file FAKE_GH_STATE and logs
each call, one JSON line, to FAKE_GH_LOG. A missing thing answers the way gh
does: "gh: Not Found (HTTP 404)" on stderr and exit 1.
"""
import json
import os
import sys


def load():
    with open(os.environ["FAKE_GH_STATE"], encoding="utf-8") as handle:
        return json.load(handle)


def save(state):
    with open(os.environ["FAKE_GH_STATE"], "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def log(entry):
    with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def missing():
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)


def answer(value):
    print(json.dumps(value))
    sys.exit(0)


def main(argv):
    state = load()
    if argv[:2] == ["repo", "view"]:
        log({"call": "repo view"})
        if not state.get("repo"):
            print("no git remotes found", file=sys.stderr)
            sys.exit(1)
        print(state["repo"])
        return
    if not argv or argv[0] != "api":
        print("fake gh: unknown call " + " ".join(argv), file=sys.stderr)
        sys.exit(2)
    args = argv[1:]
    method = "GET"
    body = None
    path = None
    i = 0
    while i < len(args):
        if args[i] == "-X":
            method = args[i + 1]
            i += 2
        elif args[i] == "--input":
            body = json.loads(sys.stdin.read() or "null")
            i += 2
        else:
            path = args[i]
            i += 1
    log({"method": method, "path": path, "body": body})
    if state.get("fail_all"):
        print("gh: Forbidden (HTTP 403)", file=sys.stderr)
        sys.exit(1)
    route, _, query = path.partition("?")
    prefix = "repos/{}/".format(state["repo"])
    if not route.startswith(prefix):
        missing()
    rest = route[len(prefix):].split("/")

    if rest[:3] == ["git", "ref", "heads"] and method == "GET":
        sha = state["refs"].get("/".join(rest[3:]))
        if not sha:
            missing()
        answer({"ref": "refs/heads/" + "/".join(rest[3:]), "object": {"sha": sha, "type": "commit"}})
    if rest == ["git", "refs"] and method == "POST":
        state["refs"][body["ref"][len("refs/heads/"):]] = body["sha"]
        save(state)
        answer({"ref": body["ref"], "object": {"sha": body["sha"]}})

    if rest[0] == "environments":
        envs = state.setdefault("environments", {})
        name = rest[1]
        if len(rest) == 2 and method == "PUT":
            env = envs.setdefault(name, {"custom": False, "protected": False, "policies": [], "secrets": []})
            policy = (body or {}).get("deployment_branch_policy")
            env["custom"] = bool(policy and policy.get("custom_branch_policies"))
            env["protected"] = bool(policy and policy.get("protected_branches"))
            save(state)
            answer({"name": name})
        if name not in envs:
            missing()
        env = envs[name]
        if len(rest) == 2:
            policy = {"protected_branches": env["protected"], "custom_branch_policies": env["custom"]} \
                if env["custom"] or env["protected"] else None
            answer({"name": name, "deployment_branch_policy": policy})
        if rest[2] == "deployment-branch-policies":
            if len(rest) == 3 and method == "GET":
                answer({"total_count": len(env["policies"]), "branch_policies": env["policies"]})
            if len(rest) == 3 and method == "POST":
                new = {"id": state.setdefault("next_id", 100), "name": body["name"], "type": body.get("type", "branch")}
                state["next_id"] += 1
                env["policies"].append(new)
                save(state)
                answer(new)
            if len(rest) == 4 and method == "DELETE":
                env["policies"] = [p for p in env["policies"] if str(p["id"]) != rest[3]]
                save(state)
                return
        if rest[2] == "secrets" and method == "GET":
            answer({"total_count": len(env["secrets"]), "secrets": [{"name": n} for n in env["secrets"]]})
        missing()

    if rest == ["actions", "secrets"]:
        names = state.get("repo_secrets", [])
        answer({"total_count": len(names), "secrets": [{"name": n} for n in names]})
    if rest == ["actions", "organization-secrets"]:
        names = state.get("org_secrets", [])
        answer({"total_count": len(names), "secrets": [{"name": n} for n in names]})

    if rest[0] == "rulesets":
        rulesets = state.setdefault("rulesets", [])
        if len(rest) == 1 and method == "GET":
            own_only = "includes_parents=false" in query
            answer([{k: r[k] for k in ("id", "name", "target", "source_type", "enforcement")}
                    for r in rulesets if not own_only or r.get("source_type") == "Repository"])
        if len(rest) == 1 and method == "POST":
            new = dict(body, id=state.setdefault("next_id", 100), source_type="Repository")
            state["next_id"] += 1
            rulesets.append(new)
            save(state)
            answer(new)
        found = [r for r in rulesets if str(r["id"]) == rest[1]]
        if not found:
            missing()
        if method == "GET":
            answer(found[0])
        if method == "PUT":
            found[0].clear()
            found[0].update(dict(body, id=int(rest[1]), source_type="Repository"))
            save(state)
            answer(found[0])

    if rest[0] == "branches" and rest[-1] == "protection":
        if state.get("classic_protection"):
            answer({"url": "x"})
        missing()
    missing()


if __name__ == "__main__":
    main(sys.argv[1:])
