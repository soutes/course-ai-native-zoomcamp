"""Markdown-to-HTML for the retro web page (#17).

`render_report_markdown` (`portfolio/services/render.py`) only ever emits a fixed,
self-generated subset of Markdown: ``# ``/``## `` headings, blank-line-separated
paragraphs, ``- `` bullet lists, and inline ``**bold**`` / `` `code` `` spans. This
module turns exactly that subset into HTML - it is not a general CommonMark parser
and must not grow into one; anything the report ever needs outside this subset
belongs in `render_report_markdown`, not typed into a `WeeklyReport` row by hand.

Written by hand instead of adding a Markdown dependency: `pyproject.toml` has no
markdown-to-HTML library today (`markdown-it-py` is only a transitive dependency
of `rich`, not a direct one - AGENTS.md: "Do not add dependencies without asking").
Because the input is a small, fixed, self-generated subset, a full parser is not
needed to satisfy #17's acceptance criteria.

Pure stdlib (``html`` only, no Django import - see the services layering rule in
AGENTS.md). Every character of user-derived text (repo names, commit subjects,
descriptions) is escaped with ``html.escape`` before any markup is added, so a
commit subject containing ``<script>`` renders as literal text, never executes.
The result is a plain ``str`` - no Django ``SafeString`` here, so this module stays
Django-free; the caller marks it safe once, at the template boundary, only after
this function has already escaped every user-derived character.
"""

from __future__ import annotations

import html
import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+?)`")


def _inline(text: str) -> str:
    """Escape the text, then apply the two inline spans this app's markdown uses."""
    escaped = html.escape(text)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _CODE_RE.sub(r"<code>\1</code>", escaped)
    return escaped


def render_markdown_html(markdown_text: str) -> str:
    """Render `render_report_markdown`'s fixed subset of Markdown to HTML.

    Headings (``#`` / ``##``), bullet lists (``- ``) and plain paragraphs, each with
    ``**bold**`` and `` `code` `` spans resolved inside them. Every other character in
    the source is HTML-escaped first, so markup-looking text a repo owner typed into a
    commit subject or repo description (``<script>``, stray ``<``/``>``/``&``) renders
    as visible text rather than as HTML.
    """
    out: list[str] = []
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()

        if not line:
            close_list()
            continue

        if line.startswith("## "):
            close_list()
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            close_list()
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if not list_open:
                out.append("<ul>")
                list_open = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        else:
            close_list()
            out.append(f"<p>{_inline(line)}</p>")

    close_list()
    return "\n".join(out)
