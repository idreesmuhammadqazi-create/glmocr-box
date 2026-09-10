"""Tests for digital-PDF text-layer fallbacks (pdftext)."""
from __future__ import annotations

from ocrqp.pdftext import (
    clean_junk,
    inject_question_numbers,
    is_front_matter,
    textlayer_page_text,
)


def test_inject_missing_number():
    md = "The variables x and y satisfy the equation.\n"
    out = inject_question_numbers(md, [(3, [50.0, 63.0, 55.0, 75.0])])
    assert out.startswith("3. The variables")


def test_inject_skips_when_already_numbered():
    md = "2 Solve the equation.\n"
    out = inject_question_numbers(md, [(2, [50.0, 63.0, 55.0, 75.0])])
    assert out == md  # unchanged


def test_inject_skips_front_matter():
    md = "CANDIDATE NAME\n\nMATHEMATICS\n"
    out = inject_question_numbers(md, [(3, [50.0, 63.0, 55.0, 75.0])])
    assert out == md


def test_inject_strips_leading_marker_lines():
    md = "![](page=0,bbox=[1,2,3,4])\n\n(b) Hence, find...\n"
    out = inject_question_numbers(md, [(5, [50.0, 63.0, 55.0, 90.0])])
    assert out == "5. (b) Hence, find..."


def test_clean_junk_drops_markers_and_footer():
    md = "![](page=0,bbox=[5,6,7,8])\nreal content\nCambridge University Press 2026\n"
    out = clean_junk(md)
    lines = [l for l in out.splitlines() if l.strip()]
    assert lines == ["real content"]


class _FakeRect:
    width = 595.0
    height = 842.0


class _FakePage:
    """Minimal pymupdf page stand-in returning fixed words."""

    rect = _FakeRect()

    def get_text(self, kind):
        return [
            (272.0, 63.0, 300.0, 75.0, "12"),
            (50.0, 120.0, 55.0, 150.0, "3"),
            (72.0, 120.0, 300.0, 132.0, "Solve the inequality"),
            (72.0, 150.0, 300.0, 162.0, "....."),
        ]


def test_textlayer_page_text_filters_header_and_dots():
    out = textlayer_page_text(_FakePage())
    assert "12" not in out
    assert "Solve the inequality" in out
    assert "....." not in out


def test_is_front_matter():
    assert is_front_matter("CANDIDATE NAME\n...")
    assert is_front_matter("This page is BLANK PAGE intentionally")
    assert not is_front_matter("1. Find the value of x.")
