"""Offline demo: synthetic PDF -> per-question JSON -> custom paper.

Runs the whole pipeline with the mock OCR backend (no API key needed) so you
can see the exact output shape. Swap OCRQP_BACKEND=glm + a real key for the
real thing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocrqp.builder import build_custom_paper
from ocrqp.client import LayoutElement, MockClient, OCRResult
from ocrqp.config import Config
from ocrqp.json_out import document_to_dataset, write_dataset
from ocrqp.ocr import process_pdf

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
OUT = ROOT / "out"
ASSETS = ROOT / "assets"


def make_demo_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "1 (a) Simplify 3x + 2x. [1]")
    page.insert_text((72, 110), "   (b) Solve 3x + 2 = 17. [3]")
    page.draw_rect(fitz.Rect(72, 140, 260, 280))            # diagram
    page.insert_text((72, 320), "2 The table shows values of x and y.")
    for r in range(4):                                       # table grid
        for c in range(3):
            page.draw_rect(fitz.Rect(72 + c * 120, 340 + r * 40, 192 + c * 120, 380 + r * 40))
    doc.save(str(path))
    doc.close()


def mock_handler():
    calls = {"n": 0}

    def handler(image, page_index):
        calls["n"] += 1
        w, h = image.size
        if calls["n"] % 2 == 1:  # pass 1 (full page)
            md = (
                "1 (a) Simplify $3x + 2x$. [1]\n"
                "(b) Solve $3x + 2 = 17$. [3]\n\n"
                "2 The table shows values of $x$ and $y$.\n\n"
                "<table><tr><td>x</td><td>y</td></tr><tr><td>1</td><td>3</td></tr></table>"
            )
            els = [
                LayoutElement("image", (w * 0.10, h * 0.16, w * 0.45, h * 0.33)),
                LayoutElement("table", (w * 0.10, h * 0.40, w * 0.90, h * 0.62)),
            ]
            return OCRResult(markdown=md, elements=els)
        # pass 2 (table crop): rescued with clean LaTeX
        return OCRResult(
            markdown=("<table><tr><td>$x$</td><td>$y=2x+1$</td></tr>"
                      "<tr><td>1</td><td>3</td></tr>"
                      "<tr><td>2</td><td>5</td></tr></table>")
        )

    return handler


def main() -> int:
    SAMPLES.mkdir(exist_ok=True)
    pdf = SAMPLES / "0580_w25_qp_41.pdf"
    make_demo_pdf(pdf)

    cfg = Config.from_env()
    cfg.backend = "mock"
    cfg.cache_dir = str(ROOT / ".ocrqp-cache")

    client = MockClient(mock_handler())
    doc = process_pdf(pdf, client, cfg, ASSETS)
    dataset = document_to_dataset(doc)
    out = write_dataset(dataset, OUT)
    print(f"dataset -> {out}")
    for q in dataset["questions"]:
        print(f"  {q['id']:8} marks={q['marks']} diagrams={len(q['diagrams'])}  {q['text'][:40]!r}")

    # Build a custom paper from a couple of selected questions.
    paper = dataset["paper"]
    selections = [(paper, q["id"]) for q in dataset["questions"][:2]]
    summary = build_custom_paper(
        OUT, selections, OUT / "custom_paper.md", OUT / "custom_paper.html",
        title="My Custom Paper",
    )
    print(f"custom paper -> {OUT/'custom_paper.md'} / .html  {summary['count']} Qs, {summary['total_marks']} marks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
