"""End-to-end pipeline test using the mock OCR backend + a synthetic PDF."""
from __future__ import annotations

import fitz  # PyMuPDF
import pytest

from ocrqp.client import LayoutElement, MockClient, OCRResult
from ocrqp.config import Config
from ocrqp.json_out import document_to_dataset, parse_filename
from ocrqp.ocr import process_pdf
from ocrqp.splice import splice_tables


def make_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 in points
    page.insert_text((72, 72), "1 Find the value of x. [3]")
    page.draw_rect(fitz.Rect(72, 100, 220, 230))          # a "diagram"
    page.draw_rect(fitz.Rect(72, 300, 520, 460))          # a "table" region
    doc.save(str(path))
    doc.close()


def mock_handler():
    calls = {"n": 0}

    def handler(image, page_index):
        calls["n"] += 1
        w, h = image.size
        if calls["n"] == 1:
            # pass 1: mangled table + a diagram element
            md = "1 Find the value of $x$. [3]\n\n<table><tr><td>3x+2=17</td></tr></table>"
            els = [
                LayoutElement("table", (w * 0.1, h * 0.35, w * 0.9, h * 0.55)),
                LayoutElement("image", (w * 0.1, h * 0.12, w * 0.4, h * 0.28)),
            ]
            return OCRResult(markdown=md, elements=els)
        # pass 2: rescued table with clean LaTeX
        return OCRResult(markdown="<table><tr><td>$3x+2=17 \\Rightarrow x=5$</td></tr></table>")

    return handler


def test_splice_replaces_table():
    md = "before\n\n<table><tr><td>bad</td></tr></table>\n\nafter"
    out = splice_tables(md, ["<table><tr><td>$x=5$</td></tr></table>"])
    assert "$x=5$" in out and "bad" not in out


def test_parse_filename():
    meta = parse_filename("0580_w25_ms_41.pdf")
    assert meta["subject"] == "0580"
    assert meta["kind"] == "marking_scheme"
    assert meta["paper"] == "0580/41"
    assert "2025" in meta["series"]


def test_full_pipeline_mock(tmp_path):
    pdf = tmp_path / "0580_w25_ms_41.pdf"
    make_pdf(pdf)

    cfg = Config.from_env()
    cfg.backend = "mock"
    cfg.cache_dir = str(tmp_path / "cache")

    client = MockClient(mock_handler())
    assets = tmp_path / "assets"
    doc = process_pdf(pdf, client, cfg, assets)
    dataset = document_to_dataset(doc)

    assert dataset["kind"] == "marking_scheme"
    assert dataset["paper"] == "0580/41"
    assert len(dataset["questions"]) >= 1

    q1 = dataset["questions"][0]
    assert q1["id"].startswith("1")
    assert q1["marks"] == 3

    # rescued LaTeX table spliced into the content
    assert "x=5" in q1["text"] or any("x=5" in q["text"] for q in dataset["questions"])

    # a diagram was cropped and attached
    all_diagrams = [d for q in dataset["questions"] for d in q["diagrams"]]
    assert all_diagrams, "expected at least one diagram asset"
    for d in all_diagrams:
        assert (tmp_path / "assets" / d.split("/")[-1]).exists() or (assets / d.split("/")[-1]).exists()
