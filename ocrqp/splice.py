"""Splice pass-2 rescued tables back over pass-1 markdown tables.

glm-ocr emits tables as HTML ``<table>`` blocks. Pass 1 gives the page
markdown with (possibly mangled) tables; pass 2 re-OCRs each table crop at
higher DPI so formulas survive as LaTeX. We replace the pass-1 tables in
order with the rescues. If a rescue can't be matched positionally it is
appended with a marker comment rather than dropped.
"""
from __future__ import annotations

import re

TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)


def find_table_spans(markdown: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in TABLE_RE.finditer(markdown)]


def splice_tables(markdown: str, rescued: list[str]) -> str:
    """Replace pass-1 <table> blocks in order with rescued table HTML.

    Extra rescues (no matching pass-1 table) are appended with a marker.
    Missing rescues leave the original pass-1 table in place.
    """
    spans = find_table_spans(markdown)
    out: list[str] = []
    last = 0
    for i, (s, e) in enumerate(spans):
        out.append(markdown[last:s])
        if i < len(rescued) and rescued[i].strip():
            out.append(rescued[i])
        else:
            out.append(markdown[s:e])  # keep original if no rescue
        last = e
    out.append(markdown[last:])

    # Append unmatched rescues with a marker so nothing is silently dropped.
    if len(rescued) > len(spans):
        for extra in rescued[len(spans):]:
            if extra.strip():
                out.append("\n\n<!-- rescued-table (unmatched) -->\n" + extra)
    return "".join(out)
