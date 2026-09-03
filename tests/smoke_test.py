import asyncio
import re
import sys
import tempfile
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocrpdf.client import OcrClient
from ocrpdf.config import Settings
from ocrpdf.mathmd import cleanup_math, html_tables_to_pipes, mathify
from ocrpdf.pipeline import PageCache, process_pdf
from ocrpdf.render import detect_table_rects
from ocrpdf.splice import SENTINEL, splice_tables


def make_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "Marking Scheme — Paper 1", fontname="helv", fontsize=16)
    page.insert_text((72, 110), "Question 1(a)(i): Answer with formula", fontname="helv", fontsize=11)

    x0, y0, x1, y1 = 72, 140, 520, 400
    cols = [x0, x0 + 160, x0 + 320, x1]
    rows = [y0, y0 + 65, y0 + 130, y0 + 195, y1]
    for x in cols:
        page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1))
    for y in rows:
        page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y))

    cell = lambda cx, cy, s: page.insert_text((cx, cy), s, fontname="helv", fontsize=10)
    cell(cols[0] + 8, rows[0] + 40, "1(a)(i)")
    cell(cols[1] + 8, rows[0] + 40, "M1: x^2 + 2x + 1 = 0")
    cell(cols[2] + 8, rows[0] + 40, "(x+1)(x+1) = 0")
    cell(cols[3] + 8, rows[0] + 40, "[2]")
    cell(cols[0] + 8, rows[1] + 40, "1(a)(ii)")
    cell(cols[1] + 8, rows[1] + 40, "A1: x = -1")
    cell(cols[2] + 8, rows[1] + 40, "sqrt(2)/2 or 1/2")
    cell(cols[3] + 8, rows[1] + 40, "[1]")
    cell(cols[0] + 8, rows[2] + 40, "1(b)")
    cell(cols[1] + 8, rows[2] + 40, "B1: dy/dx = 3x^2")
    cell(cols[2] + 8, rows[2] + 40, "integral of f(x)")
    cell(cols[3] + 8, rows[2] + 40, "[3]")
    cell(cols[0] + 8, rows[3] + 40, "1(c)")
    cell(cols[1] + 8, rows[3] + 40, "M1: e^(2t) > 0")
    cell(cols[2] + 8, rows[3] + 40, "alpha + beta")
    cell(cols[3] + 8, rows[3] + 40, "[1]")

    page.insert_text((72, 450), "Notes: award marks as shown in the table above.", fontname="helv", fontsize=11)
    doc.save(path)
    doc.close()


def test_detection():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "sample.pdf"
        make_sample_pdf(pdf)
        doc = fitz.open(pdf)
        rects = detect_table_rects(doc[0])
        doc.close()
        assert len(rects) == 1, f"expected 1 table rect, got {len(rects)}: {rects}"
        r = rects[0]
        assert abs(r.x0 - 72) < 15 and abs(r.y0 - 140) < 15, f"rect off: {r}"
        assert abs(r.x1 - 520) < 15 and abs(r.y1 - 400) < 15, f"rect off: {r}"
        print("test_detection OK:", rects[0])


def test_splice_with_sentinels():
    page_md = (
        "Intro text.\n"
        f"{SENTINEL}\n"
        "| Q | Ans |\n|---|---|\n| 1 | mangled $$ \n\nAfter table text.\n"
        f"{SENTINEL}\n"
        "| Q | B |\n|---|---|\n| 2 | mangled2 |"
    )
    rescued = [
        "| Q | Ans |\n|---|---|\n| 1 | $x^2 + 2x + 1 = 0$ |",
        "| Q | B |\n|---|---|\n| 2 | $\\frac{1}{2}$ |",
    ]
    out, n = splice_tables(page_md, rescued)
    assert n == 2, f"expected 2 replacements, got {n}"
    assert "$x^2 + 2x + 1 = 0$" in out and "mangled" not in out
    print("test_splice_with_sentinels OK")


def test_splice_no_sentinels():
    page_md = "Text.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nTrailing text."
    rescued = ["| A | B |\n|---|---|\n| 1 | $e^{2t}$ |"]
    out, n = splice_tables(page_md, rescued)
    assert n == 1 and "$e^{2t}$" in out and "| 1 | 2 |" not in out
    print("test_splice_no_sentinels OK")


def test_splice_fallback_append():
    page_md = "No tables here."
    rescued = ["| A | B |\n|---|---|\n| 1 | 2 |"]
    out, n = splice_tables(page_md, rescued)
    assert n == 0 and "rescued tables" in out and "| 1 | 2 |" in out
    print("test_splice_fallback_append OK")


def test_html_table_to_pipes():
    md = (
        "Intro\n\n"
        '<table border="1"><tr><td>Q</td><td>Answer</td><td>Marks</td></tr>'
        "<tr><td>7(a)</td><td>-3&lt;x≤2</td><td>2</td></tr>"
        "<tr><td>9</td><td>M1 for $ k &lt; 5 $<br>OR<br>M2 for $a\\times b$</td><td>1</td></tr>"
        "</table>\n\nEnd"
    )
    out = html_tables_to_pipes(md)
    assert "<table" not in out
    seps = [ln for ln in out.splitlines() if re.fullmatch(r"\|(-{3}\|)+", ln)]
    assert len(seps) == 1
    assert "| 7(a) | -3<x≤2 | 2 |" in out
    assert "M1 for $ k < 5 $<br>OR<br>M2 for $a\\times b$ | 1 |" in out


def test_cleanup_math_entities_and_unicode():
    md = "text $ -3&lt;x≤2 $ more and `code $x&lt;1$ stays` end $ \\frac{1}{2}\\times5 $"
    out = cleanup_math(md)
    assert "$-3<x\\le2$" in out.replace(" ", "").replace("$ -3", "$-3") or "$-3<x\\le2$" in out.replace(" ", "")
    assert "&lt;" not in out.split("`")[0]
    assert "≤" not in out
    assert "code $x&lt;1$ stays" in out


def test_mathify_complex_table_kept():
    md = '<table><tr><td rowspan="2">a</td><td>b</td></tr><tr><td>c</td></tr></table>'
    out = mathify(md)
    assert "<table" in out


def test_mathify_simple_pipeline():
    md = '<table><tr><td>x</td><td>$\\frac{1}{2}$ &amp; more</td></tr></table>'
    out = mathify(md)
    assert "<table" not in out
    assert "&amp;" not in out


class MockClient:
    def __init__(self):
        self.calls = []

    async def parse_image(self, png: bytes, kind: str = "page"):
        self.calls.append(kind)
        if kind == "page":
            from ocrpdf.client import LayoutResult
            return LayoutResult(
                md=(
                    "Marking Scheme — Paper 1\n\n"
                    '<table border="1"><tr><td>Q</td><td>Working</td></tr>'
                    "<tr><td>1(a)(i)</td><td>(mangled)</td></tr></table>\n\n"
                    "Notes: award marks as shown in the table above."
                ),
                elements=[
                    {"label": "text", "bbox_2d": [72, 80, 300, 100], "width": 595, "height": 842},
                    {"label": "table", "bbox_2d": [72, 140, 520, 400], "width": 595, "height": 842},
                ],
            )
        from ocrpdf.client import LayoutResult
        return LayoutResult(
            md=('<table border="1"><tr><td>Q</td><td>Working</td></tr>'
                "<tr><td>1(a)(i)</td><td>$(x+1)(x+1) = 0$</td></tr></table>"),
            elements=[{"label": "table", "bbox_2d": [0, 0, 100, 100], "width": 100, "height": 100}],
        )


def test_pipeline_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pdf = tmp / "sample.pdf"
        make_sample_pdf(pdf)
        settings = Settings(api_key="test", base_url="http://localhost", model="glm-ocr")
        out = tmp / "sample.md"
        asyncio.run(process_pdf(pdf, out, settings, MockClient(), PageCache(tmp / "cache"), dry_run=False))
        text = out.read_text(encoding="utf-8")
        assert "===== Page 1 =====" in text
        assert "$(x+1)(x+1) = 0$" in text
        assert "(mangled)" not in text
        assert "Notes: award marks" in text
        print("test_pipeline_end_to_end OK")


if __name__ == "__main__":
    test_splice_with_sentinels()
    test_splice_no_sentinels()
    test_splice_fallback_append()
    test_html_table_to_pipes()
    test_cleanup_math_entities_and_unicode()
    test_mathify_complex_table_kept()
    test_mathify_simple_pipeline()
    test_detection()
    test_pipeline_end_to_end()
    print("ALL TESTS PASSED")
