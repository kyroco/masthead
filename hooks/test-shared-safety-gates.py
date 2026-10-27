#!/usr/bin/env python3
"""Prove the shared gates that have no test file of their own refuse what they
must, allow the rest, and never wedge a session on their own broken plumbing.

    python3 ~/.claude/hooks/test-shared-safety-gates.py

Every hook is found beside this file. Every case runs against throwaway
directories, so no live record and no live session state is touched.

READ THE ORDER OF THE CASES. A fail-open case is worth nothing on its own: a
hook that allows everything passes it. So each section proves its deny cases
first, and only then that malformed input allows.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.abspath(__file__))
PROTOCOL = os.path.join(HOOKS, "engram-protocol.sh")
DOMAIN = os.path.join(HOOKS, "untrusted-domain-deny.py")
DISPATCH = os.path.join(HOOKS, "dispatch-record-gate.sh")
BRIEF_GATES = os.path.join(HOOKS, "agent-brief-gates.sh")


def run(argv, payload, env=None):
    merged = dict(os.environ)
    # The repo this is run from must not make a hook read its files.
    merged.pop("CLAUDE_PROJECT_DIR", None)
    if env is not None:
        merged.update(env)
    result = subprocess.run(argv, input=payload, capture_output=True,
                            text=True, check=False, env=merged)
    out = result.stdout.strip()
    if not out:
        return "allow"
    try:
        return json.loads(out)["hookSpecificOutput"].get("permissionDecision", "allow")
    except Exception:
        return "unparseable: " + out[:70]


def main():
    failures = []

    def check(label, actual, expected):
        ok = actual == expected
        if not ok:
            failures.append(label)
        print("{:4}  {:<44} expected {:<5} got {}".format(
            "ok" if ok else "FAIL", label, expected, actual))

    print("--- the domain gate refuses the two named classes ---")

    def domain_decision(tool, tool_input):
        return run([sys.executable, DOMAIN], json.dumps({
            "session_id": "test-shared-safety-gates",
            "tool_name": tool, "tool_input": tool_input}))

    check("an exfil sink",
          domain_decision("WebFetch", {"url": "https://webhook.site/abc?d=secret"}), "deny")
    check("a subdomain of one",
          domain_decision("WebFetch", {"url": "https://x.y.webhook.site/p"}), "deny")
    check("an anonymous paste",
          domain_decision("WebFetch", {"url": "https://pastebin.com/raw/aB3"}), "deny")
    check("an out-of-band dns sink",
          domain_decision("WebFetch", {"url": "http://data.oast.fun/"}), "deny")
    check("a sink named in a search",
          domain_decision("WebSearch", {"query": "https://webhook.site/leak"}), "deny")

    print("\n--- and leaves ordinary documentation alone ---")
    for label, url in (
        ("hexdocs", "https://hexdocs.pm/ecto/Ecto.Query.html"),
        ("the AWS docs", "https://docs.aws.amazon.com/ecs/latest/APIReference/"),
        ("a GitHub issue", "https://github.com/elixir-ecto/ecto/issues/4000"),
        ("an ordinary site", "https://example.org/changelog"),
        # A name that merely ENDS in the same letters is a different host.
        ("a lookalike host", "https://notpastebin.com/x"),
        ("a plain search", "https://www.google.com/search?q=ecto+preload"),
    ):
        check(label, domain_decision("WebFetch", {"url": url}), "allow")
    check("an ordinary search query",
          domain_decision("WebSearch", {"query": "ecto preload nested assoc"}), "allow")

    print("\n--- and fails open on its own broken plumbing ---")
    domain_argv = [sys.executable, DOMAIN]
    check("domain gate: malformed JSON", run(domain_argv, "{not json at all"), "allow")
    check("domain gate: empty stdin", run(domain_argv, ""), "allow")
    check("domain gate: JSON that is not an object", run(domain_argv, "[1,2,3]"), "allow")
    check("domain gate: payload with no tool_input",
          run(domain_argv, json.dumps({"tool_name": "Bash"})), "allow")

    print("\n--- the Stop gate cannot hold the session ---")
    stop_tmp = tempfile.mkdtemp()
    stop_env = dict(os.environ, TMPDIR=stop_tmp)
    stop_env.pop("CLAUDE_PROJECT_DIR", None)
    stop_cwd = tempfile.mkdtemp()
    stop_payload = json.dumps({"session_id": "stop-budget", "hook_event_name": "Stop",
                               "cwd": stop_cwd,
                               "last_assistant_message": "All eight passed."})

    def stop_once():
        out = subprocess.run(["bash", PROTOCOL, "gate-stop"], input=stop_payload,
                             capture_output=True, text=True, check=False,
                             env=stop_env).stdout.strip()
        return json.loads(out).get("decision") if out else "allow"

    # A session that changed files and captured nothing. The worst case there is.
    subprocess.run(["bash", PROTOCOL, "mark-edit"],
                   input=json.dumps({"session_id": "stop-budget"}),
                   capture_output=True, text=True, check=False, env=stop_env)
    turns = []
    for _ in range(8):
        turns.append(stop_once())
        if turns[-1] != "block":
            break
    for i, decision in enumerate(turns, 1):
        print("      turn {}: gate-stop {}".format(i, decision))
    check("it refuses a session that captured nothing", turns[0], "block")
    check("and then lets the session end", turns[-1] != "block", True)
    check("within its budget of one refusal", len(turns) <= 2, True)

    print("\n--- every dispatch is recorded with its model, and none is refused ---")
    # A RECORD, NOT A GATE. The Model-choice line used to be a
    # precondition and caused 181 of 974 refusals. The model now comes from the
    # call or from the agent's own file, and a dispatch is never refused.
    #
    # A THROWAWAY ROOT AND A THROWAWAY USER FOLDER. The hook appends to
    # <cwd>/.claude/state/dispatches.tsv and reads agent files from the project
    # and then from the user folder, so both are built here or the live
    # session's agents answer instead.
    DISPATCH_ROOT = tempfile.mkdtemp(prefix="dispatch-suite-")
    USER_ROOT = tempfile.mkdtemp(prefix="dispatch-user-")
    agents_dir = os.path.join(DISPATCH_ROOT, ".claude", "agents")
    user_agents_dir = os.path.join(USER_ROOT, "agents")
    os.makedirs(agents_dir)
    os.makedirs(user_agents_dir)
    with open(os.path.join(agents_dir, "fixture-agent.md"), "w") as fh:
        fh.write("---\nname: fixture-agent\nmodel: sonnet\n---\n\nBody.\n")
    with open(os.path.join(agents_dir, "crlf-agent.md"), "w", newline="") as fh:
        fh.write("---\r\nname: crlf-agent\r\nmodel: haiku\r\n---\r\n")
    with open(os.path.join(agents_dir, "no-header.md"), "w") as fh:
        fh.write("No frontmatter.\n\n---\n\nmodel: bogus\n")
    with open(os.path.join(DISPATCH_ROOT, "outside.md"), "w") as fh:
        fh.write("---\nmodel: stolen\n---\n")
    # The shared agents live in the user folder. One exists only there, and one
    # exists in both places, where the project's file has to win.
    with open(os.path.join(user_agents_dir, "user-agent.md"), "w") as fh:
        fh.write("---\nname: user-agent\nmodel: opus\n---\n\nBody.\n")
    with open(os.path.join(user_agents_dir, "fixture-agent.md"), "w") as fh:
        fh.write("---\nname: fixture-agent\nmodel: haiku\n---\n\nBody.\n")

    def dispatch_decision(tool_input, tool="Agent", session="dispatch-suite"):
        return run(["bash", DISPATCH], json.dumps({
            "session_id": session, "cwd": DISPATCH_ROOT,
            "tool_name": tool, "tool_input": tool_input}),
            env={"CLAUDE_PROJECT_DIR": DISPATCH_ROOT, "CLAUDE_PLUGIN_ROOT": USER_ROOT})

    STATED = ("Model-choice: haiku, mechanical sweep the suite verifies\n\n"
              "List every hook file that carries a shebang.")
    UNSTATED = "List every hook file that carries a shebang."
    DISCUSSES = ("You are fixing dispatch-record-gate.sh, which reads a line\n"
                 "reading Model-choice: opus, because it decides.")

    check("a dispatch that states its model",
          dispatch_decision({"prompt": STATED, "subagent_type": "general-purpose",
                             "model": "haiku", "name": "sweeper"}), "allow")
    check("a dispatch that does not is allowed",
          dispatch_decision({"prompt": UNSTATED, "subagent_type": "general-purpose",
                             "model": "opus", "name": "lane"}), "allow")
    check("a non-Agent call is out of scope",
          dispatch_decision({"command": "ls"}, tool="Bash"), "allow")
    check("a broken payload allows", run(["bash", DISPATCH], "{not json at all"), "allow")
    check("empty stdin allows", run(["bash", DISPATCH], ""), "allow")
    check("a payload with no tool_input allows",
          run(["bash", DISPATCH], json.dumps({"tool_name": "Agent"})), "allow")

    # THE RECORD IS THE DELIVERABLE. Rows from this run carry a marker unique
    # to it, so each is looked for under that marker rather than anywhere.
    marker = os.path.basename(DISPATCH_ROOT)
    dispatch_decision({"prompt": STATED, "subagent_type": "claude",
                       "model": "haiku", "name": marker + "-stated"})
    dispatch_decision({"prompt": UNSTATED, "subagent_type": "fixture-agent",
                       "name": marker + "-fromfile"})
    dispatch_decision({"prompt": UNSTATED, "subagent_type": "user-agent",
                       "name": marker + "-fromuser"})
    dispatch_decision({"prompt": DISCUSSES, "subagent_type": "claude",
                       "name": marker + "-discusses"})
    dispatch_decision({"prompt": "\n\nModel-choice: opus, leading blanks",
                       "subagent_type": "claude", "name": marker + "-blanks"})
    dispatch_decision({"prompt": "   Model-choice: opus, indented",
                       "subagent_type": "claude", "name": marker + "-indented"})
    dispatch_decision({"prompt": "# Brief\nModel-choice: opus, under a heading",
                       "subagent_type": "claude", "name": marker + "-heading"})
    dispatch_decision({"prompt": UNSTATED, "subagent_type": "fork", "model": "haiku",
                       "name": marker + "-fork"})
    dispatch_decision({"prompt": UNSTATED, "subagent_type": "crlf-agent",
                       "name": marker + "-crlf"})
    dispatch_decision({"prompt": UNSTATED, "subagent_type": "no-header",
                       "name": marker + "-noheader"})
    dispatch_decision({"prompt": UNSTATED, "subagent_type": "../../outside",
                       "name": marker + "-traversal"})
    rec = os.path.join(DISPATCH_ROOT, ".claude/state/dispatches.tsv")
    rows = open(rec).read().splitlines() if os.path.exists(rec) else []
    by_name = {r.split("\t")[2]: r.split("\t") for r in rows[1:] if len(r.split("\t")) >= 7}
    check("it has a header naming the model column",
          bool(rows) and "model" in rows[0].split("\t"), True)
    stated = by_name.get(marker + "-stated", [""] * 7)
    check("a stated dispatch records the call's model", stated[4], "haiku")
    dispatch_decision({"prompt": "Re-verify: round 2, claims 1 and 3\nVerify the fix commits.\nClaims: x",
                       "subagent_type": "verifier", "model": "opus"})
    reverify = open(rec).read().splitlines()[-1].split("\t")
    check("a re-verify brief is recorded with its round", reverify[5], "re-verify round 2")
    dispatch_decision({"prompt": "Re-verify: claims 1 and 3\nVerify the fix commits.",
                       "subagent_type": "verifier", "model": "opus"})
    unnumbered = open(rec).read().splitlines()[-1].split("\t")
    check("a re-verify brief with no round is still a re-verify", unnumbered[5], "re-verify")
    dispatch_decision({"prompt": "- Re-verify: round 3, claim 2\nVerify the fix commits.",
                       "subagent_type": "verifier", "model": "opus"})
    marked = open(rec).read().splitlines()[-1].split("\t")
    check("a re-verify line as a list item is still recorded as one", marked[5], "re-verify round 3")
    dispatch_decision({"prompt": "> - Re-verify: round 4, claim 2\nVerify the fix commits.",
                       "subagent_type": "verifier", "model": "opus"})
    quoted = open(rec).read().splitlines()[-1].split("\t")
    check("a re-verify line under two prefixes is still recorded as one", quoted[5], "re-verify round 4")
    # The outcome cannot be preset from the environment: the wrapper passes a
    # refusal as an argument, so an operator variable changes nothing (edge-5).
    run(["bash", DISPATCH], json.dumps({
        "session_id": "dispatch-suite", "cwd": DISPATCH_ROOT, "tool_name": "Agent",
        "tool_input": {"prompt": "Re-verify: round 2\nVerify.", "subagent_type": "verifier", "model": "opus"}}),
        env={"MASTHEAD_DISPATCH_OUTCOME": "dispatched"})
    preset = open(rec).read().splitlines()[-1].split("\t")
    check("an environment outcome is ignored", preset[5], "re-verify round 2")
    run(["bash", DISPATCH, "--refused"], json.dumps({
        "session_id": "dispatch-suite", "cwd": DISPATCH_ROOT, "tool_name": "Agent",
        "tool_input": {"prompt": "Re-verify: round 2\nVerify.", "subagent_type": "verifier", "model": "opus"}}))
    argued = open(rec).read().splitlines()[-1].split("\t")
    check("the wrapper's refusal argument is recorded", argued[5], "refused")
    check("every row carries the branch column",
          all(len(r.split("\t")) == 8 for r in open(rec).read().splitlines()), True)
    check("and records the stated reason",
          stated[6], "haiku, mechanical sweep the suite verifies")
    fromfile = by_name.get(marker + "-fromfile", [""] * 7)
    check("no model on the call: the project's agent file wins",
          fromfile[4], "sonnet (agent file)")
    check("and the missing line is noted", fromfile[6], "(no Model-choice line)")
    check("an unstated dispatch is recorded as dispatched", fromfile[5], "dispatched")
    discusses = by_name.get(marker + "-discusses", [""] * 7)
    check("a declaration below the first line is not read as one",
          discusses[6], "(no Model-choice line)")
    check("an unknown agent with no model stays inherited",
          discusses[4], "(inherited)")

    def row(suffix):
        return by_name.get(marker + suffix, [""] * 7)
    check("an agent only the user folder has is read from there",
          row("-fromuser")[4], "opus (agent file)")
    check("a declaration after leading blank lines is read",
          row("-blanks")[6], "opus, leading blanks")
    check("an indented declaration is read", row("-indented")[6], "opus, indented")
    check("a declaration under a heading is not",
          row("-heading")[6], "(no Model-choice line)")
    check("a fork records the parent's model, not the call's",
          row("-fork")[4], "(parent)")
    check("a CRLF agent file records a clean model",
          row("-crlf")[4], "haiku (agent file)")
    check("a divider in a file with no header is not a header",
          row("-noheader")[4], "(inherited)")
    check("an agent type naming a path reads nothing",
          row("-traversal")[4], "(inherited)")
    # The record never outranks the work. Driven against a root whose .claude
    # is a FILE, so mkdir genuinely fails.
    broken = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                          "dispatch-noroot-{}".format(os.getpid()))
    shutil.rmtree(broken, ignore_errors=True)
    os.makedirs(broken)
    open(os.path.join(broken, ".claude"), "w").write("not a directory\n")
    check("an unwritable record still lets the dispatch through",
          run(["bash", DISPATCH], json.dumps({
              "session_id": "dispatch-suite", "cwd": broken, "tool_name": "Agent",
              "tool_input": {"prompt": STATED, "subagent_type": "claude"}})), "allow")
    shutil.rmtree(broken, ignore_errors=True)
    shutil.rmtree(DISPATCH_ROOT, ignore_errors=True)
    shutil.rmtree(USER_ROOT, ignore_errors=True)

    print("\n--- a search has to land, and be about the work ---")
    # gate-edit asked one question: did a search CALL happen. So a search whose
    # result nobody read, and a search about nothing in particular, both passed.
    # What is honestly checkable is that the search RETURNED something and was
    # about this task. Whether the model READ it is not observable from a hook
    # and nothing here pretends otherwise.
    KTMP = tempfile.mkdtemp()
    KCWD = tempfile.mkdtemp()

    def kstate(sid, rows=None, searched=True):
        d = os.path.join(KTMP, "masthead-{}".format(os.getuid()), "claude-engram", sid)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        if searched:
            open(os.path.join(d, "searched"), "w").close()
        if rows is not None:
            open(os.path.join(d, "searches.tsv"), "w").write(
                "".join("{}\t{}\n".format(n, q) for n, q in rows))
        return d

    def kgate(mode, payload, env=None):
        merged = {"TMPDIR": KTMP + "/"}
        merged.update(env or {})
        return run(["bash", PROTOCOL, mode], json.dumps(payload), env=merged)

    def edit_gate(sid, env=None):
        return kgate("gate-edit", {"session_id": sid, "cwd": KCWD,
                                   "tool_name": "Write",
                                   "tool_input": {"file_path": "/tmp/x",
                                                  "content": "y"}}, env)

    kstate("k-none", searched=False)
    check("no search at all is still refused", edit_gate("k-none"), "deny")

    print("\n--- hook state is private and a session id cannot leave it ---")
    ESC = tempfile.mkdtemp()
    ESC_TMP = os.path.join(ESC, "a", "b")
    os.makedirs(ESC_TMP)
    run(["bash", PROTOCOL, "mark-edit"], json.dumps({
        "session_id": "../../../escaped", "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/x"}}), env={"TMPDIR": ESC_TMP})
    check("a session id with slashes and .. stays inside the state root",
          " ".join(sorted(os.listdir(ESC)) + sorted(os.listdir(os.path.join(ESC, "a")))), "a b")
    inside = [os.path.join(dp, n) for dp, dn, fn in os.walk(ESC_TMP) for n in dn + fn]
    uid_root = os.path.join(ESC_TMP, "masthead-{}".format(os.getuid()))
    check("every state path sits under the user's private root",
          all(p.startswith(uid_root) for p in inside) and bool(inside), True)
    modes = {os.path.relpath(p, ESC_TMP): oct(os.stat(p).st_mode & 0o777) for p in inside}
    check("state folders are 0700 and state files 0600",
          " ".join(sorted({m for p, m in modes.items() if os.path.isdir(os.path.join(ESC_TMP, p))}) +
                   sorted({m for p, m in modes.items() if os.path.isfile(os.path.join(ESC_TMP, p))})),
          "0o700 0o600")
    shutil.rmtree(ESC, ignore_errors=True)
    kstate("k-hit", [("8", "heredoc strip hook gate bypass")])
    check("a search that returned something", edit_gate("k-hit"), "allow")
    kstate("k-zero", [("0", "heredoc gate")])
    check("returned nothing, tried one wording", edit_gate("k-zero"), "deny")
    kstate("k-zero2", [("0", "heredoc gate"), ("0", "irreversible awk strip")])
    check("returned nothing twice, two wordings is evidence",
          edit_gate("k-zero2"), "allow")
    kstate("k-old", None)
    check("no record of what was searched allows", edit_gate("k-old"), "allow")
    kstate("k-off", [("0", "x")])
    check("the operator's search escape",
          edit_gate("k-off", {"MASTHEAD_SEARCH_GATE": "off"}), "allow")

    print("\n--- a capture is filed under the name that made it ---")
    # ADR-0120: source_agent is the one field that answers who decided this.
    # MEASURED on 1434 real captures from 2026-08-20: this refuses 0 of them when
    # the name matches and 1076 when it does not, which is the separation the
    # length and importance rules could not produce. Those are not enforced and
    # the reason is in the hook's own comment.
    def cap_gate(agent, source, extra=None):
        ti = {"source_agent": source, "content": "x",
              "thought_type": "decision", "importance": 0.6}
        if extra:
            ti.update(extra)
        p = {"session_id": "k-cap", "cwd": KCWD,
             "tool_name": "mcp__korium__agent_capture", "tool_input": ti}
        if agent:
            p["agent_name"] = agent
        return kgate("gate-capture", p)

    check("filed under another agent's name", cap_gate("zeina", "thiago"), "deny")
    check("filed under its own name", cap_gate("zeina", "zeina"), "allow")
    check("a variant of its own name", cap_gate("zeina", "zeina-validity"), "allow")
    check("re-filing with captured_by set",
          cap_gate("zeina", "thiago", {"captured_by": "zeina"}), "allow")
    check("the main session names no agent", cap_gate(None, "anything"), "allow")
    check("the operator's capture escape",
          kgate("gate-capture", {"session_id": "k-cap", "cwd": KCWD,
                                 "agent_name": "zeina",
                                 "tool_name": "mcp__korium__agent_capture",
                                 "tool_input": {"source_agent": "thiago"}},
                {"MASTHEAD_CAPTURE_GATE": "off"}), "allow")

    print("\n--- the brief checks answer together, in one decision ---")
    # agent-brief-gates.sh runs the one brief check, the model option and the
    # dispatch record on every dispatch and joins what they say, so a brief with
    # two problems hears about both at once.
    FAN_TMP = tempfile.mkdtemp()
    FAN_CWD = tempfile.mkdtemp()
    FAN_USER = tempfile.mkdtemp()

    def fan_out(prompt, hook=BRIEF_GATES, subagent="general-purpose", raw=None,
                model="haiku"):
        # model haiku by default, so model-choice-gate stays out of the cases
        # that are about the other checks; model=None leaves it unset.
        payload = raw
        if payload is None:
            tool_input = {"prompt": prompt, "subagent_type": subagent,
                          "name": "fan-out-case"}
            if model:
                tool_input["model"] = model
            payload = json.dumps({
                "session_id": "brief-fan", "cwd": FAN_CWD, "tool_name": "Agent",
                "tool_input": tool_input})
        env = dict(os.environ, TMPDIR=FAN_TMP + "/", CLAUDE_CONFIG_DIR=FAN_USER)
        env.pop("CLAUDE_PROJECT_DIR", None)
        return subprocess.run(["bash", hook], input=payload, capture_output=True,
                              text=True, check=False, env=env).stdout.strip()

    def reason_of(out):
        try:
            return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        except Exception:
            return "unparseable: " + out[:70]

    # A verifier brief with no claims list, sent with model opus on the call and
    # no Model-choice line: the one brief check and the model option both refuse.
    TWO_PROBLEMS = "Verify this diff and report what you find."
    out = fan_out(TWO_PROBLEMS, subagent="verifier", model="opus")
    reason = reason_of(out)
    check("a brief with two problems is refused once",
          out.count('"hookSpecificOutput"'), 1)
    check("and the one decision parses", reason.startswith("unparseable"), False)
    for name in ("model-choice-gate", "gate-verify-brief"):
        check("it names {}".format(name), "] " + name + "\n" in reason, True)
    check("and counts them", "refused by 2 of the 3 brief checks" in reason, True)
    one = reason_of(fan_out(TWO_PROBLEMS, subagent="verifier"))
    check("the same brief on haiku is one refusal",
          "] gate-verify-brief\n" in one and "refused by 1 of the 3 brief checks" in one, True)
    check("the record-only check never appears as a refusal",
          "dispatch-record-gate" in reason, False)
    record = os.path.join(FAN_CWD, ".claude", "state", "dispatches.tsv")
    check("the dispatch was still recorded", os.path.exists(record), True)
    refused_rows = [r.split("\t") for r in open(record).read().splitlines()[1:]]
    check("and a refused dispatch is recorded as refused, so it never counts as a round",
          all(r[5] == "refused" for r in refused_rows) and len(refused_rows) == 2, True)
    # The removed checks stay removed: a build brief with no Korium line, no
    # evidence plan and an unowned impossibility goes through on haiku.
    check("a build brief is not screened for a Korium line, evidence or an impossibility",
          fan_out("Fix the crash in the parser. This cannot be done any other way."), "")

    CLEAN = ("read_only: true\n"
             "List every hook file that carries a shebang.")
    check("a brief with nothing wrong is allowed", fan_out(CLEAN), "")
    check("empty stdin allows", fan_out(None, raw=""), "")

    # A CHECK THAT CANNOT RUN IS A REFUSAL. The fan-out copied somewhere with
    # no checks beside it must say so rather than allow everything.
    lonely = tempfile.mkdtemp()
    shutil.copy2(BRIEF_GATES, os.path.join(lonely, "agent-brief-gates.sh"))
    lonely_reason = reason_of(fan_out(CLEAN, hook=os.path.join(lonely, "agent-brief-gates.sh")))
    check("a missing check file is refused, not skipped",
          "could not be run at all" in lonely_reason, True)
    check("and every missing check is named",
          "refused by 3 of the 3 brief checks" in lonely_reason, True)
    for tree in (lonely, FAN_TMP, FAN_CWD, FAN_USER, KTMP, KCWD, stop_tmp, stop_cwd):
        shutil.rmtree(tree, ignore_errors=True)

    print("\n--- every hook in hooks.json runs through run.sh and names a file that is here ---")
    wiring = json.load(open(os.path.join(HOOKS, "hooks.json")))["hooks"]
    commands = [hook["command"] for groups in wiring.values() for group in groups for hook in group["hooks"]]
    print("      {} entries".format(len(commands)))
    bad = []
    for command in commands:
        found = re.search(r'run\.sh" ([A-Za-z0-9_.-]+\.(?:py|sh))', command)
        if not found or not os.path.isfile(os.path.join(HOOKS, found.group(1))):
            bad.append(command[-50:])
    check("every entry names a hook file that is installed", "; ".join(bad) or "all present", "all present")

    print("")
    if failures:
        print("{} of the cases are wrong:".format(len(failures)))
        for label in failures:
            print("  " + label)
        return 1
    print("every case correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
