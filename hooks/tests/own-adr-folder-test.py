#!/usr/bin/env python3
"""MAST-53: Masthead's own decision records live in the repository.

1. This repository's settings name ADR_DIR, and adr_shape.folder() takes it as a folder inside the repository.
2. That folder exists in the repository.

Rests on Robert, November 20, 2026: "just use the local repo as ADR tracking the wiki has been causing a lot
of problems". Run: python3 hooks/tests/own-adr-folder-test.py
"""
import os
import sys

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = os.path.dirname(HOOKS)
# Read this checkout as the session's project, as a session started in it would.
os.environ["CLAUDE_PROJECT_DIR"] = TOP
sys.path.insert(0, HOOKS)
import adr_shape  # noqa: E402
import project_fact  # noqa: E402

passed = failed = 0


def check(name, ok):
    global passed, failed
    if ok:
        passed += 1
        print("ok   - " + name)
    else:
        failed += 1
        print("FAIL - " + name)


# The committed settings file only, read the one way Masthead reads settings (docs/architecture.md).
named = project_fact.settings_env(os.path.join(TOP, ".claude", "settings.json")).get("ADR_DIR") or ""
check("1: this repository's settings name ADR_DIR", bool(named.strip()))
check("1: ADR_DIR names no folder outside the repository", not adr_shape.outside(os.path.expanduser(named), TOP))
where = adr_shape.folder(TOP)
check("1: the ADR gates take it as this repository's ADR folder", where is not None)
check("2: the folder is in the repository", bool(where) and os.path.isdir(os.path.join(TOP, where)))

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
