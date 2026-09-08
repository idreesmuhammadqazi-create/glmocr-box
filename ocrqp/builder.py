"""Custom paper builder: pick questions across datasets -> assembled paper.

Outputs Markdown and a self-contained HTML (images embedded as base64,
LaTeX rendered via MathJax) so a selected set of questions becomes a paper.
"""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path


def load_datasets(json_dir: str | Path) -> list[dict]:
    out = []
    for p in sorted(Path(json_dir).glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def index_questions(datasets: list[dict]) -> dict[tuple[str, str], dict]:
    """Map (paper, question_id) -> question record (with paper/series/kind)."""
    idx: dict[tuple[str, str], dict] = {}
    for ds in datasets:
        for q in ds.get("questions", []):
            rec = dict(q)
            rec["paper"] = ds.get("paper", "")
            rec["series"] = ds.get("series", "")
            rec["kind"] = ds.get("kind", "")
            idx[(ds.get("paper", ""), q.get("id", ""))] = rec
    return idx


def _img_data_uri(path: str) -> str:
    try:
        b = Path(path).read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(b).decode("ascii")


def render_markdown(questions: list[dict], title: str = "Custom Paper") -> str:
    lines = [f"# {title}", ""]
    total = 0
    for i, q in enumerate(questions, 1):
        marks = q.get("marks") or 0
        total += marks
        lines.append(f"## {i}. ({q.get('paper','')} {q.get('id','')})  [{marks} marks]")
        lines.append("")
        lines.append(q.get("text", ""))
        for d in q.get("diagrams", []):
            lines.append(f"\n![diagram]({d})")
        lines.append("")
    lines.append(f"---\n**Total: {total} marks**")
    return "\n".join(lines)


def render_html(questions: list[dict], title: str = "Custom Paper") -> str:
    cards = []
    total = 0
    for i, q in enumerate(questions, 1):
        marks = q.get("marks") or 0
        total += marks
        figs = "".join(
            f'<img src="{_img_data_uri(d)}" alt="diagram" style="max-width:100%"/>'
            for d in q.get("diagrams", [])
            if _img_data_uri(d)
        )
        body = html.escape(q.get("text", ""))
        cards.append(
            f'<div class="q"><div class="qh">'
            f'<span>Q{i} &middot; {html.escape(q.get("paper",""))} '
            f'{html.escape(q.get("id",""))}</span>'
            f'<span class="mk">[{marks} marks]</span></div>'
            f'<div class="qb">{body}</div>{figs}</div>'
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<script>window.MathJax={{tex:{{inlineMath:[['$','$'],['\\\\(','\\\\)']]}}}};</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<style>
 body{{font-family:system-ui,serif;max-width:800px;margin:2rem auto;padding:0 1rem}}
 .q{{border:1px solid #ccc;border-radius:8px;padding:1rem;margin:1rem 0}}
 .qh{{display:flex;justify-content:space-between;font-weight:600;color:#444}}
 .qb{{white-space:pre-wrap;margin-top:.5rem}}
 .mk{{color:#888}}
</style></head>
<body><h1>{html.escape(title)}</h1>{''.join(cards)}
<p><strong>Total: {total} marks</strong></p>
</body></html>"""


def build_custom_paper(
    json_dir: str | Path,
    selections: list[tuple[str, str]],
    out_md: str | Path,
    out_html: str | Path | None = None,
    title: str = "Custom Paper",
) -> dict:
    """Build a paper from selected (paper, question_id) pairs.

    Returns a summary dict with the questions included and total marks.
    """
    idx = index_questions(load_datasets(json_dir))
    chosen: list[dict] = []
    missing: list[tuple[str, str]] = []
    for key in selections:
        if key in idx:
            chosen.append(idx[key])
        else:
            missing.append(key)

    Path(out_md).write_text(render_markdown(chosen, title), encoding="utf-8")
    if out_html:
        Path(out_html).write_text(render_html(chosen, title), encoding="utf-8")

    return {
        "title": title,
        "count": len(chosen),
        "total_marks": sum((q.get("marks") or 0) for q in chosen),
        "included": [(q.get("paper"), q.get("id")) for q in chosen],
        "missing": missing,
    }
