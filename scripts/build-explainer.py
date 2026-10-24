#!/usr/bin/env python3
"""Build docs/explainer.html from docs/explainer.template.html, inlining each {{name}} as docs/images/name.svg."""
import os, re
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
images = os.path.join(root, "docs", "images")
def inline(name):
    s = open(os.path.join(images, name + ".svg")).read()
    s = re.sub(r'<rect width="\d+" height="\d+" fill="#ffffff"/>\n', "", s, count=1)
    s = re.sub(r'<svg xmlns="http://www.w3.org/2000/svg" width="\d+" height="\d+"', '<svg xmlns="http://www.w3.org/2000/svg" role="img"', s, count=1)
    tag = re.sub(r"[^a-z0-9]", "", name)
    s = re.sub(r'id="([A-Za-z0-9_-]+)"', lambda m: f'id="{tag}-{m.group(1)}"', s)
    s = re.sub(r'url\(#([A-Za-z0-9_-]+)\)', lambda m: f'url(#{tag}-{m.group(1)})', s)
    return s
page = open(os.path.join(root, "docs", "explainer.template.html")).read()
page = re.sub(r"\{\{([a-z0-9-]+)\}\}", lambda m: inline(m.group(1)), page)
open(os.path.join(root, "docs", "explainer.html"), "w").write(page)
print(len(page), "bytes,", page.count("<svg"), "pictures")
