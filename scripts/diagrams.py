#!/usr/bin/env python3
"""Draw every diagram under docs/images from its words, so no label can leave its box.

Each box is sized from the longest line it holds, at a wide estimate of the font
(0.6 of the font size per character, 0.66 when bold), and every arrow starts and
ends on a box edge. Run `python3 scripts/diagrams.py` after changing a word, then
`python3 scripts/svgcheck.py docs/images/*.svg` to prove the fit.
"""
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images")
FONT = "-apple-system, Segoe UI, Helvetica, Arial, sans-serif"
MONO = "Menlo, Consolas, monospace"

# Palette: one color per actor, used the same way in every picture.
INK = {"fill": "#f3f4f6", "stroke": "#9ca3af", "text": "#374151", "sub": "#4b5563"}      # documents, neutral
YOU = {"fill": "#fce7f3", "stroke": "#db2777", "text": "#9d174d", "sub": "#9d174d"}      # the person
FOREMAN = {"fill": "#eef2ff", "stroke": "#6366f1", "text": "#312e81", "sub": "#4338ca"}  # the foreman and workers
CHECK = {"fill": "#fef3c7", "stroke": "#d97706", "text": "#78350f", "sub": "#92400e"}    # readers, checks, reviewers
MEMORY = {"fill": "#f5f3ff", "stroke": "#7c3aed", "text": "#4c1d95", "sub": "#5b21b6"}   # optional memory
GOOD = {"fill": "#dcfce7", "stroke": "#16a34a", "text": "#14532d", "sub": "#166534"}     # merged, the fix list
JUDGE = {"fill": "#ecfeff", "stroke": "#0891b2", "text": "#164e63", "sub": "#155e75"}
WARN = {"fill": "#fff7ed", "stroke": "#ea580c", "text": "#7c2d12", "sub": "#7c2d12"}
RED = {"fill": "#fee2e2", "stroke": "#dc2626", "text": "#7f1d1d", "sub": "#7f1d1d"}
OUTBOX = {"fill": "#f9fafb", "stroke": "#d1d5db", "text": "#6b7280", "sub": "#6b7280"}
GREY = "#6b7280"


def width_of(text, size, bold=False):
    return len(text) * size * (0.66 if bold else 0.6)


class Canvas:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=12, color=GREY, anchor="start", bold=False, mono=False):
        weight = ' font-weight="600"' if bold else ""
        family = f' font-family="{MONO}"' if mono else ""
        shown = s.replace(" ", "\u00a0") if mono else s
        self.add(f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="{anchor}" font-size="{size}"{weight}{family} fill="{color}">{esc(shown)}</text>')

    def box(self, x, y, lines, style, min_w=0, pad=14, dash=False, title_size=14, body_size=12, gap=4):
        """lines: [(text, kind)] with kind 'title', 'body' or 'mono'. Returns (x, y, w, h)."""
        widths = [width_of(t, title_size if k == "title" else body_size, bold=(k == "title")) for t, k in lines]
        w = max(min_w, max(widths) + 2 * pad)
        heights = [(title_size if k == "title" else body_size) + gap for t, k in lines]
        h = sum(heights) + 2 * pad - gap
        dashed = ' stroke-dasharray="6 3"' if dash else ""
        self.add(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="10" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1.5"{dashed}/>')
        cy = y + pad
        for (t, k), lh in zip(lines, heights):
            size = title_size if k == "title" else body_size
            cy += size
            self.text(x + w / 2, cy - 2, t, size=size, color=style["text"] if k == "title" else style["sub"],
                      anchor="middle", bold=(k == "title"), mono=(k == "mono"))
            cy += gap
        return (x, y, w, h)

    def arrow(self, x1, y1, x2, y2, color=GREY, dash=False):
        dashed = ' stroke-dasharray="5 4"' if dash else ""
        self.add(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{color}" stroke-width="2"{dashed} marker-end="url(#m{color[1:]})"/>')

    def path(self, d, color=GREY, dash=False, arrow=True):
        dashed = ' stroke-dasharray="5 4"' if dash else ""
        head = f' marker-end="url(#m{color[1:]})"' if arrow else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"{dashed}{head}/>')

    def write(self, name):
        colors = {GREY, FOREMAN["stroke"], GOOD["stroke"], YOU["stroke"], CHECK["stroke"], RED["stroke"]}
        defs = "".join(f'<marker id="m{c[1:]}" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in sorted(colors))
        body = "\n  ".join(self.parts)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" font-family="{FONT}" font-size="14">\n'
               f'  <rect width="{self.w}" height="{self.h}" fill="#ffffff"/>\n  <defs>{defs}</defs>\n  {body}\n</svg>\n')
        with open(os.path.join(OUT, name), "w") as fh:
            fh.write(svg)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mid(b):
    return b[0] + b[2] / 2


def bottom(b):
    return b[1] + b[3]


def right(b):
    return b[0] + b[2]


# ---------------------------------------------------------------- gates.svg
def gates():
    c = Canvas(1000, 400)
    c.text(40, 40, "A rule written in prose", size=20, color="#1f2937", bold=True)
    c.text(40, 66, '"Never push without running the tests."', size=14, color="#4b5563")
    c.add('<rect x="40" y="90" width="400" height="150" rx="10" fill="#f9fafb" stroke="#d1d5db"/>')
    c.text(60, 116, "How strongly Claude follows it", size=13, color="#374151")
    c.add('<line x1="60" y1="216" x2="420" y2="216" stroke="#9ca3af"/>')
    c.text(60, 234, "hour 1", size=12); c.text(240, 234, "hour 2", size=12, anchor="middle"); c.text(420, 234, "hour 3", size=12, anchor="end")
    c.add('<path d="M 60 134 C 160 136, 240 164, 300 194 S 400 216, 420 216" fill="none" stroke="#dc2626" stroke-width="4" stroke-linecap="round"/>')
    c.text(40, 276, "It fades as the session gets long, and nobody notices", size=14, color="#4b5563")
    c.text(40, 298, "until something has already slipped through.", size=14, color="#4b5563")

    c.text(520, 40, "The same rule as a check", size=20, color="#1f2937", bold=True)
    c.text(520, 66, "A small check runs before the action, every time.", size=14, color="#4b5563")
    claude = c.box(520, 100, [("Claude", "title")], FOREMAN, min_w=100)
    gate = c.box(680, 92, [("the check", "title"), ("tests passed on", "body"), ("this commit?", "body")], CHECK)
    c.arrow(right(claude), claude[1] + claude[3] / 2, gate[0] - 2, claude[1] + claude[3] / 2)
    c.text((right(claude) + gate[0]) / 2, claude[1] + claude[3] / 2 - 8, "git push", size=12, anchor="middle")
    pushed = c.box(right(gate) + 50, 104, [("pushed", "title")], GOOD, min_w=90)
    c.arrow(right(gate), gate[1] + 30, pushed[0] - 2, gate[1] + 30, color=GOOD["stroke"])
    c.text((right(gate) + pushed[0]) / 2, gate[1] + 22, "yes", size=12, color=GOOD["stroke"], anchor="middle")
    refused = c.box(mid(gate) - 130, bottom(gate) + 50, [("refused, with the reason", "title"), ('"run the tests, then push again"', "body")], RED, min_w=260)
    c.arrow(mid(gate), bottom(gate), mid(gate), refused[1] - 2, color=RED["stroke"])
    c.text(mid(gate) + 12, bottom(gate) + 28, "no", size=12, color=RED["stroke"])
    c.text(520, bottom(refused) + 40, "Claude reads the reason and does the right thing instead.", size=14, color="#4b5563")
    c.text(520, bottom(refused) + 62, "The check runs the same way at hour one and at hour ten.", size=14, color="#4b5563")
    c.write("gates.svg")


# ------------------------------------------------------------- workflow.svg
WORKER_STEPS = [
    "1. read the issue, the README, the decisions",
    "2. plan: a change and a test per scenario",
    "   (a blind verifier passes it first)",
    "3. build, test first; search memory",
    "4. decision-record review",
    "5. one verifier per scenario, then the judge",
    "6. fix the list, test first; re-verify what broke",
    "7. push check: tests on this commit",
]


def workflow():
    c = Canvas(1120, 700)
    c.text(40, 40, "A run: the issues are checked, a foreman plans, workers build in parallel", size=20, color="#1f2937", bold=True)
    work = c.box(40, 70, [("the work, written down", "title"), ("project README: why, shape, rules", "body"),
                          ("issues: why, scenarios, out of scope, questions", "body"), ("decision records, mockups", "body")], INK)
    check = c.box(right(work) + 40, 70, [("/analyze-issues", "title"), ("an agent per issue: checks it, fixes only what fails, asks", "body"),
                                         ("one check of every issue: what was dropped, what is too big", "body"), ("asks you only what nothing settles", "body")], CHECK)
    c.arrow(right(work), work[1] + 40, check[0] - 2, work[1] + 40)
    fy = bottom(check) + 60
    foreman = c.box(0, fy, [("/work-on foreman", "title"), ("reads the brief and every issue, proposes one plan: build order, dependencies, effort, parallelism", "body"),
                            ("you decide how many run at once", "body")], FOREMAN)
    # centre the foreman under the two boxes above
    fx = (right(check) + 40) / 2 - foreman[2] / 2
    c.parts = c.parts[:-4]  # redraw at the centred x
    foreman = c.box(fx, fy, [("/work-on foreman", "title"), ("reads the brief and every issue, proposes one plan: build order, dependencies, effort, parallelism", "body"),
                             ("you decide how many run at once", "body")], FOREMAN)
    ey = (bottom(check) + foreman[1]) / 2
    c.path(f"M {mid(check):.0f} {bottom(check):.0f} L {mid(check):.0f} {ey:.0f} L {mid(foreman):.0f} {ey:.0f} L {mid(foreman):.0f} {foreman[1] - 2:.0f}")

    # three workers, each sized from the longest step
    wy = bottom(foreman) + 70
    cols = []
    x = 40
    for n in ("41", "42", "45"):
        lines = [(f"worker for issue #{n}", "title")] + [(s, "body") for s in WORKER_STEPS] + [(f"9. one pull request, Fixes #{n}", "body")]
        b = c.box(x, wy, lines, OUTBOX, pad=16)
        cols.append(b)
        x = right(b) + 36
    total = right(cols[-1])
    if total + 40 > c.w:
        c.w = int(total + 40)
    # the foreman to each worker, and the workers back to the foreman
    for b in cols:
        c.path(f"M {mid(foreman):.0f} {bottom(foreman):.0f} L {mid(foreman):.0f} {wy - 30} L {mid(b):.0f} {wy - 30} L {mid(b):.0f} {wy - 2}", color=FOREMAN["stroke"])
    c.text(mid(cols[0]), wy - 38, "one fresh session per issue, each in its own worktree", size=12, color=FOREMAN["sub"], anchor="middle")
    rx = right(cols[-1]) - 30
    c.path(f"M {rx:.0f} {wy:.0f} L {rx:.0f} {foreman[1] + foreman[3] / 2:.0f} L {right(foreman) + 2:.0f} {foreman[1] + foreman[3] / 2:.0f}", color=GREY, dash=True)
    c.text(right(foreman) + 12, foreman[1] + foreman[3] / 2 - 8, "plans, questions and reports come back to the foreman", size=11, color=GREY)

    # merge bar
    my = bottom(cols[0]) + 40
    bar = c.box(40, my, [("the foreman queues each passing pull request, closes its issue and any big issue now done, and gives that worker its next issue", "title"),
                         ("the run ends when every issue is merged, parked or skipped, with one line per issue saying which", "body")], GOOD, min_w=total - 40, title_size=13)
    for b in cols:
        c.arrow(mid(b), bottom(b), mid(b), my - 2, color=GOOD["stroke"])
    c.text(40, bottom(bar) + 30, "A worker that stops on a failure gets one message; a second failure parks the issue with a comment. Memory steps run only when Korium is connected.", size=12)
    c.h = int(bottom(bar) + 50)
    c.write("workflow.svg")


# --------------------------------------------------------------- review.svg
def review():
    c = Canvas(1100, 620)
    c.text(40, 40, "The verification: verifiers who read cold, and a judge that confirms and places", size=20, color="#1f2937", bold=True)
    worker = c.box(40, 120, [("the worker", "title"), ("finishes the change and sends", "body"), ("each scenario, the diff, its claims", "body")], FOREMAN)
    rx = right(worker) + 50
    names = ["verifier: scenario 1", "verifier: scenario 2", "verifier: scenario 3", "verifier: scenario 4"]
    revs = []
    y = 70
    for n in names:
        b = c.box(rx, y, [(n, "body")], CHECK, min_w=170, pad=10)
        revs.append(b); y = bottom(b) + 8
    sec = c.box(rx, y, [("security reviewer", "body")], RED, min_w=170, pad=10)
    revs.append(sec); y = bottom(sec) + 10
    note = c.box(rx, y, [("each one tries to make every claim false:", "body"), ("no author's notes, no editing, no network", "body")], OUTBOX, pad=10)
    c.arrow(right(worker), worker[1] + 40, revs[1][0] - 2, worker[1] + 40)

    jx = right(revs[0]) + 70
    judge = c.box(jx, 150, [("the judge", "title"), ("runs each false claim's reproduction,", "body"), ("nothing from the worker,", "body"), ("and places it; that is final", "body")], JUDGE)
    c.arrow(right(revs[2]), revs[2][1] + 18, judge[0] - 2, revs[2][1] + 18)
    c.text((right(revs[2]) + judge[0]) / 2, revs[2][1] + 8, "false claims", size=12, anchor="middle")

    ox = right(judge) + 60
    fix = c.box(ox, 90, [("the fix list", "title"), ("confirmed, and belongs to this change;", "body"), ("a file and a line for each one", "body")], GOOD)
    new = c.box(ox, bottom(fix) + 24, [("new issues to file", "title"), ("confirmed and serious, but outside this change:", "body"), ("filed and linked, never fixed here", "body")], INK)
    out = c.box(ox, bottom(new) + 24, [("thrown out", "title"), ("not real, not confirmed, or not worth", "body"), ("a change; gone for good", "body")], OUTBOX)
    c.arrow(right(judge), judge[1] + 30, fix[0] - 2, fix[1] + fix[3] / 2, color=GOOD["stroke"])
    c.arrow(right(judge), judge[1] + 50, new[0] - 2, new[1] + new[3] / 2)
    c.arrow(right(judge), judge[1] + 70, out[0] - 2, out[1] + out[3] / 2, dash=True)
    widest = max(right(fix), right(new), right(out))
    if widest + 60 > c.w:
        c.w = int(widest + 60)

    # back to the worker, around the outside
    ay = max(bottom(out), bottom(note)) + 30
    lines = [("the worker fixes each item on the list, test first,", "body"), ("and only the claims the fix broke are re-verified, at most twice", "body")]
    aw = max(width_of(t, 12) for t, _ in lines) + 28
    again = c.box(mid(judge) - aw / 2, ay, lines, FOREMAN)
    loop_y = bottom(again) + 30
    c.path(f"M {right(fix):.0f} {fix[1] + 20:.0f} L {widest + 24:.0f} {fix[1] + 20:.0f} L {widest + 24:.0f} {loop_y} L {mid(worker):.0f} {loop_y} L {mid(worker):.0f} {bottom(worker) + 2:.0f}", color=FOREMAN["stroke"])
    c.text(40, loop_y + 40, "Then: the tests run on the final commit, and one pull request goes up.", size=13, color="#4b5563")
    c.h = int(loop_y + 60)
    c.write("review.svg")


# ------------------------------------------------------------- the day, six small pictures
def day1():
    c = Canvas(960, 230)
    c.add('<circle cx="90" cy="86" r="26" fill="#fce7f3" stroke="#db2777" stroke-width="2"/>')
    c.text(90, 91, "you", size=13, color=YOU["text"], anchor="middle", bold=True)
    c.text(90, 136, "Monday morning", size=12, anchor="middle")
    c.add('<rect x="160" y="40" width="360" height="110" rx="10" fill="#1f2937"/>')
    c.add('<circle cx="178" cy="56" r="4" fill="#f87171"/><circle cx="192" cy="56" r="4" fill="#fbbf24"/><circle cx="206" cy="56" r="4" fill="#34d399"/>')
    c.text(180, 100, "> /work-on milestone 4", size=18, color="#e5e7eb", mono=True)
    c.text(180, 130, "one command, that's all you type", size=12, color="#9ca3af", mono=True)
    c.arrow(530, 95, 580, 95)
    items = ["milestone 4: nine issues", "#41 the sign-in page remembers the email", "#42 export a month as a file",
             "#43 refuse a save past the plan limit", "#44 show who can read a note", "#45, #46, #47, #48, #49"]
    c.box(590, 30, [(items[0], "title")] + [(t, "body") for t in items[1:]], INK)
    c.write("day-1-start.svg")


def day2():
    c = Canvas(1000, 250)
    fore = c.box(40, 70, [("the foreman", "title"), ("builds nothing yet.", "body"), ("It reads.", "body")], FOREMAN, min_w=150)
    docs = [("the project README", "why, shape, rules: the brief"), ("every issue, every comment", "your rulings arrive as comments"),
            ("the decision records", "named now, read by builders in full"), ("architecture notes and mockups", "named now, looked up by section")]
    y = 24
    boxes = []
    for t, s in docs:
        b = c.box(right(fore) + 50, y, [(t, "title"), (s, "body")], INK, title_size=13, pad=8)
        boxes.append(b); y = bottom(b) + 8
    c.arrow(right(fore), fore[1] + 40, boxes[1][0] - 2, fore[1] + 40)
    mem = c.box(right(fore) + 50, y, [("memory", "title"), ("what earlier sessions learned (optional)", "body")], MEMORY, title_size=13, pad=8, dash=True)
    boxes.append(mem)
    rule = c.box(max(right(b) for b in boxes) + 40, 60, [("the one rule of reading", "title"), ("The brief and every issue: all of it.", "body"), ("An answer quotes the section it read.", "body"),
                                        ("An issue read alone builds the wrong thing.", "body")], CHECK, title_size=13, pad=10)
    c.w = int(max(c.w, right(rule) + 30))
    c.h = int(max(bottom(boxes[-1]), bottom(rule)) + 24)
    c.write("day-2-read.svg")


def day3():
    c = Canvas(1000, 330)
    c.text(40, 34, "Nine small agents, one per issue, all at once", size=16, color="#1f2937", bold=True)
    x = 40
    for n in range(41, 50):
        b = c.box(x, 50, [(f"agent, #{n}", "body")], CHECK, pad=8)
        x = right(b) + 8
    q = c.box(40, 110, [("each checks its issue against its sources, and fixes only what fails", "title"), ("Are the four parts there? Is every line you wrote still quoted?", "body"),
                        ("Does each scenario cite a source line that exists, and can a test show it?", "body"), ("Does it say how? Does it fit one session?", "body"),
                        ("An issue that passes is left alone: no edit, no comment.", "body")], CHECK, title_size=13)
    m = c.box(right(q) + 30, 110, [("then one more agent checks every issue", "title"), ("Did an edit drop anything? It puts it back.", "body"), ("Are two issues building the same thing?", "body"),
                                   ("Does one contradict the decision record?", "body"), ("Is there a decision nobody is building?", "body"), ("Is the order right? It fixes the links.", "body"), ("Is one still too big for one session?", "body")], CHECK, title_size=13)
    c.w = int(max(c.w, right(m) + 40))
    then = c.box(40, bottom(q) + 20, [("Then: big ones split, questions looked up in the sources,", "body"),
                                      ("and only what nothing settles comes to you, one at a time, with a recommendation", "body")], INK, min_w=right(m) - 40)
    c.h = int(bottom(then) + 24)
    c.write("day-3-check.svg")


def day4():
    c = Canvas(1000, 260)
    rows = ["issue   after    with     effort   why",
            "#41     none     #42      medium   small screen change",
            "#42     none     #41      medium   one module, one test file",
            "#43     #41      none     high     touches the plan limits",
            "#44     none     #45      medium   read side only",
            "#45     none     #44      medium   ...",
            "suggested: 3 workers at once"]
    plan = c.box(40, 30, [("the foreman's plan, one table", "title")] + [(r, "mono") for r in rows], FOREMAN, pad=16)
    c.arrow(right(plan), plan[1] + 90, right(plan) + 50, plan[1] + 90)
    cx = right(plan) + 100
    c.add(f'<circle cx="{cx + 60:.0f}" cy="{plan[1] + 40:.0f}" r="26" fill="#fce7f3" stroke="#db2777" stroke-width="2"/>')
    c.text(cx + 60, plan[1] + 45, "you", size=13, color=YOU["text"], anchor="middle", bold=True)
    c.text(cx + 60, plan[1] + 4, "you pick how many run at once", size=12, anchor="middle")
    ans = c.box(cx - 20, plan[1] + 90, [('"three"', "title"), ("nothing starts until you say a number", "body")], YOU)
    c.w = int(max(c.w, right(ans) + 40))
    c.h = int(bottom(plan) + 30)
    c.write("day-4-plan.svg")


def day5():
    c = Canvas(1000, 300)
    fore = c.box(40, 110, [("the foreman", "title"), ("starts three", "body")], FOREMAN, min_w=140)
    ws = []
    y = 40
    for n in ("41", "42", "44"):
        b = c.box(right(fore) + 70, y, [(f"worker for #{n}", "title"), ("its own session, its own copy of the repo", "body")], OUTBOX, title_size=13, pad=10)
        ws.append(b); y = bottom(b) + 12
    for b in ws:
        c.arrow(right(fore), fore[1] + fore[3] / 2, b[0] - 2, b[1] + b[3] / 2, color=FOREMAN["stroke"])
    plan = c.box(right(ws[0]) + 50, 40, [("a worker's first message: its plan, one line per scenario, passed", "title"),
                                        ("scenario 1: change sign_in/form.ex,", "mono"), ("  test: remembers the email on reload", "mono"),
                                        ("scenario 2: change sign_in/cookie.ex,", "mono"), ("  test: the cookie expires after 30 days", "mono"),
                                        ("a blind verifier read the plan, the issue and the decisions, and passed it", "body")], INK, title_size=13)
    c.arrow(right(ws[1]), ws[1][1] + ws[1][3] / 2, plan[0] - 2, ws[1][1] + ws[1][3] / 2)
    c.w = int(max(c.w, right(plan) + 40))
    low = max(bottom(plan), bottom(ws[-1]))
    c.text(40, low + 34, "A plan that fails its verifier twice stops and asks. A line the sources don't settle is a question for you, not a guess.", size=12)
    c.h = int(low + 54)
    c.write("day-5-workers.svg")


def day6():
    c = Canvas(1000, 300)
    c.add('<circle cx="90" cy="64" r="26" fill="#fce7f3" stroke="#db2777" stroke-width="2"/>')
    c.text(90, 69, "you", size=13, color=YOU["text"], anchor="middle", bold=True)
    c.add('<path d="M 128 56 h 26 v 20 a 6 6 0 0 1 -6 6 h -14 a 6 6 0 0 1 -6 -6 z" fill="#fde68a" stroke="#d97706"/><path d="M 154 62 h 6 a 5 5 0 0 1 0 10 h -6" fill="none" stroke="#d97706"/>')
    c.text(90, 180, "having coffee", size=12, anchor="middle")
    fore = c.box(330, 60, [("the foreman", "title"), ("answers from the sources", "body")], FOREMAN)
    ask = c.box(right(fore) + 110, 50, [("a worker asks", "title"), ('"does the limit count drafts, or only saved notes?"', "body"), ("it already re-read the issue's comments", "body")], OUTBOX, title_size=13)
    c.arrow(ask[0], ask[1] + 36, right(fore) + 2, ask[1] + 36)
    found = c.box(fore[0], bottom(fore) + 36, [("found in the decision record, line quoted:", "body"), ('"saved notes only." Written on the issue.', "body")], INK, pad=10)
    c.arrow(mid(fore), bottom(fore), mid(fore), found[1] - 2)
    c.path(f"M {fore[0]:.0f} {fore[1] + 30:.0f} L 230 {fore[1] + 30:.0f} L 230 150 L 90 150 L 90 92", color=YOU["stroke"], dash=True)
    c.text(160, 142, "only when nothing settles it", size=11, color=YOU["text"], anchor="middle")
    parked = c.box(right(found) + 30, found[1], [("a worker fails twice: the issue is parked,", "body"), ("with a comment saying what happened", "body")], WARN, pad=10)
    c.w = int(max(c.w, right(ask) + 40, right(parked) + 40))
    end = c.box(40, max(bottom(found), bottom(parked)) + 24, [("end of day: #41 merged, #42 merged, #43 merged, #44 parked (needs a decision), #45 merged ... one line per issue", "body")], GOOD, min_w=c.w - 80, pad=10)
    c.h = int(bottom(end) + 24)
    c.write("day-6-coffee.svg")


if __name__ == "__main__":
    for draw in (gates, workflow, review, day1, day2, day3, day4, day5, day6):
        draw()
    print("drawn:", ", ".join(sorted(os.listdir(OUT))))
