"""Build docs/medium_article.html from docs/MEDIUM_ARTICLE.md.

- Converts markdown -> HTML (tables, fenced code, etc.).
- Replaces the 4 gisted code blocks with Gist markers + <script> embed +
  mobile fallback link (per the medium-article skill).
- Wraps in a template with a version header and the gist-marker / mobile CSS.
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown

SRC = Path("docs/MEDIUM_ARTICLE.md")
OUT = Path("docs/medium_article.html")
VERSION = "1.0.0"
DATE = "2026-10-01"

# gisted blocks: signature substring -> (gist id, number)
GISTS = [
    ("def verdict(p, yes=0.8", "6c495c8005a0e1c9184c7bd45ab21805", 1),
    ("class Triage(BaseModel)", "f17b7d8ec6dad852de0ddd9a1f770ee4", 2),
    ("SELECT ai_decide(", "2f8aedfe6cd206a12f020f8415ada2c2", 3),
    ("SLA_CUTS = {", "34e57844b6232f21e27fd9c4ec6fbff0", 4),
]

md = SRC.read_text()

# Replace each gisted fenced block with a placeholder token (leave other code
# fences — the bash "Try it yourself" blocks — as native code).
def replace_block(md: str, sig: str, token: str) -> str:
    pattern = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
    def repl(m):
        return token if sig in m.group(1) else m.group(0)
    return pattern.sub(repl, md, count=0)

for sig, gid, n in GISTS:
    md = replace_block(md, sig, f"\n\n[[GIST{n}]]\n\n")

body = markdown.markdown(md, extensions=["tables", "fenced_code"])

USER = "LaurentPRAT-DB"
for sig, gid, n in GISTS:
    marker = (
        f'<p class="gist-marker">GIST #{n} — DELETE THIS BLOCK, PASTE THE URL ON AN EMPTY LINE:<br>'
        f'https://gist.github.com/{USER}/{gid}</p>\n'
        f'<script src="https://gist.github.com/{USER}/{gid}.js"></script>\n'
        f'<p class="mobile-fallback">📱 On mobile? '
        f'<a href="https://gist.github.com/{USER}/{gid}/raw">View raw code</a></p>'
    )
    body = body.replace(f"<p>[[GIST{n}]]</p>", marker)

html = f"""<!DOCTYPE html>
<!--
  Medium Article: Databricks ai_decide and TypeSafe jev are the same model
  Version: {VERSION}
  Last Updated: {DATE}
  Features: Gist markers, mobile fallback links (/raw)
-->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="version" content="{VERSION}">
<meta name="last-updated" content="{DATE}">
<title>Databricks ai_decide and TypeSafe jev are the same model</title>
<style>
  body {{ font-family: -apple-system, Georgia, serif; max-width: 740px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; color: #222; }}
  img {{ max-width: 100%; height: auto; }}
  pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }}
  code {{ font-family: ui-monospace, Menlo, monospace; font-size: 0.9em; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
  blockquote {{ border-left: 4px solid #FF3621; margin: 1em 0; padding: 0.2em 1em; color: #555; }}
  .gist-marker {{ background: #fff3cd; border: 2px dashed #ffc107; padding: 12px; border-radius: 5px; margin: 1em 0; font-family: monospace; font-size: 0.9em; }}
  .mobile-fallback {{ font-style: italic; color: #666; font-size: 0.9em; margin-top: 0.5em; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

OUT.write_text(html)
remaining = [n for _, _, n in GISTS if f"GIST #{n}" not in html]
print(f"wrote {OUT} ({len(html)} bytes); gist markers present: "
      f"{[n for _, _, n in GISTS if f'GIST #{n}' in html]}; missing: {remaining}")
