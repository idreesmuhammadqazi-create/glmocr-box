"""Render a dataset JSON to a human-readable Markdown file for review.

This is a direct, lossless dump of the pipeline output — no hand-editing — so
the extraction quality can be checked against the source PDF.
"""
from __future__ import annotations

import json
from pathlib import Path


def dataset_to_markdown(dataset: dict) -> str:
    lines = [
        f"# {dataset.get('paper','')} — {dataset.get('kind','')}",
        "",
        f"- source_pdf: `{dataset.get('source_pdf','')}`",
        f"- series: {dataset.get('series','')}",
        f"- pages: {dataset.get('pages','')}",
        f"- questions: {len(dataset.get('questions', []))}",
        f"- total_marks: {sum((q.get('marks') or 0) for q in dataset.get('questions', []))}",
        "",
        "---",
        "",
    ]
    for q in dataset.get("questions", []):
        lines.append(f"## {q.get('id','')}  ({q.get('marks','?')} marks)")
        lines.append("")
        if q.get("working"):
            lines.append("**Working:**")
            lines.append("")
            lines.append(q["working"])
            lines.append("")
        if q.get("answer") and q.get("answer") != q.get("working"):
            lines.append(f"**Answer:** {q['answer']}")
            lines.append("")
        if q.get("notes"):
            lines.append(f"**Guidance:** {q['notes']}")
            lines.append("")
        if not q.get("working") and not q.get("answer"):
            lines.append(q.get("text", ""))
            lines.append("")
        for d in q.get("diagrams", []):
            lines.append(f"![diagram]({d})")
            lines.append("")
    return "\n".join(lines)


def convert(json_path: str | Path, md_path: str | Path) -> Path:
    dataset = json.loads(Path(json_path).read_text(encoding="utf-8"))
    md = dataset_to_markdown(dataset)
    out = Path(md_path)
    out.write_text(md, encoding="utf-8")
    return out
