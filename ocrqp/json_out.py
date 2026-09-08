"""Assemble the final per-question JSON dataset from a processed document."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .ocr import ProcessedDocument

# Cambridge filename: 0580_w25_ms_41.pdf -> subject/series/kind/paper+variant
FNAME_RE = re.compile(
    r"(?P<subject>\d{4})[_-](?P<series>[smw]\d{2})[_-](?P<kind>ms|qp|in)[_-](?P<paper>\d{2})",
    re.IGNORECASE,
)
SERIES_MAP = {"s": "May/June", "w": "Oct/Nov", "m": "Feb/March"}
KIND_MAP = {"ms": "marking_scheme", "qp": "question_paper", "in": "insert"}


def parse_filename(name: str) -> dict:
    m = FNAME_RE.search(name)
    if not m:
        return {"subject": "", "series": "", "kind": "unknown", "paper": ""}
    subject = m.group("subject")
    scode = m.group("series").lower()
    series = f"{SERIES_MAP.get(scode[0], '')} 20{scode[1:]}".strip()
    kind = KIND_MAP.get(m.group("kind").lower(), "unknown")
    paper = m.group("paper")
    return {
        "subject": subject,
        "series": series,
        "kind": kind,
        "paper": f"{subject}/{paper}",
        "variant": paper,
    }


def document_to_dataset(doc: ProcessedDocument) -> dict:
    meta = parse_filename(Path(doc.source_pdf).name)
    kind = meta.get("kind", "unknown")

    questions: list[dict] = []
    for page in doc.pages:
        for part in page.parts:
            q = {
                "id": part.id,
                "marks": part.marks,
                "text": part.text,
                "diagrams": part.diagrams,
                "page": part.page,
            }
            if kind == "marking_scheme":
                # Best-effort split; refine answer/working/notes against real
                # markscheme output once sample docs are available.
                q["answer"] = part.text
                q["working"] = ""
                q["notes"] = ""
            questions.append(q)

    return {
        "paper": meta.get("paper", ""),
        "subject": meta.get("subject", ""),
        "series": meta.get("series", ""),
        "kind": kind,
        "source_pdf": Path(doc.source_pdf).name,
        "pages": len(doc.pages),
        "questions": questions,
    }


def write_dataset(dataset: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = Path(dataset["source_pdf"]).stem + ".json"
    path = out / name
    path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
