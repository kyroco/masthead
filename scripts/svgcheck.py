#!/usr/bin/env python3
"""Flag any text that would leave its box at a wide font. Width estimate: chars * size * 0.6 (bold 0.66)."""
import re, sys
def attrs(tag):
    return dict(re.findall(r'([a-zA-Z-]+)="([^"]*)"', tag))
def run(path):
    s = open(path).read()
    default_fs = float(attrs(re.search(r"<svg[^>]*>", s).group(0)).get("font-size", 14))
    rects = [(float(a["x"]), float(a["y"]), float(a["width"]), float(a["height"]))
             for a in (attrs(t) for t in re.findall(r"<rect[^>]*>", s)) if "x" in a and "width" in a]
    vb = attrs(re.search(r"<svg[^>]*>", s).group(0))["viewBox"].split()
    W, H = float(vb[2]), float(vb[3])
    bad = []
    # group-level font-size inheritance (one level)
    for m in re.finditer(r"<text([^>]*)>(.*?)</text>", s, re.S):
        a = attrs(m.group(1)); txt = re.sub(r"<[^>]+>", "", m.group(2))
        fs = float(a.get("font-size", default_fs))
        # inherit from nearest enclosing <g font-size=...>
        before = s[:m.start()]
        g = list(re.finditer(r"<g([^>]*)>", before)); gclose = before.count("</g>")
        if g and len(g) > gclose and "font-size" not in a:
            ga = attrs(g[-1].group(1))
            if "font-size" in ga: fs = float(ga["font-size"])
        factor = 0.66 if a.get("font-weight") == "600" else 0.6
        w = len(txt) * fs * factor
        x, y = float(a["x"]), float(a["y"])
        anchor = a.get("text-anchor", "start")
        x0 = x - w/2 if anchor == "middle" else (x - w if anchor == "end" else x)
        x1 = x0 + w
        # which rect encloses the baseline point?
        box = [r for r in rects if r[0] <= x <= r[0]+r[2] and r[1] <= y <= r[1]+r[3] and r[2] < W]
        if box:
            r = min(box, key=lambda r: r[2]*r[3])
            if x0 < r[0] + 6 or x1 > r[0] + r[2] - 6:
                bad.append(f"{path}: '{txt[:50]}' needs {w:.0f}px, box {r[2]:.0f}px wide at x={r[0]:.0f}")
        elif x0 < 0 or x1 > W:
            bad.append(f"{path}: '{txt[:50]}' runs off the canvas ({x0:.0f}..{x1:.0f} of {W:.0f})")
    return bad
problems = [b for p in sys.argv[1:] for b in run(p)]
print("\n".join(problems) or "all labels fit")
sys.exit(1 if problems else 0)
