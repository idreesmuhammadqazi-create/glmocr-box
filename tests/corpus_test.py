import asyncio
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocrpdf.client import LayoutResult
from ocrpdf.config import Settings
from ocrpdf.katex_repair import KatexRepairer
from ocrpdf.pipeline import PageCache, process_pdf
from ocrpdf.structural import check_structural


NASTY_MODEL_OUTPUTS = [
    r"\frac{256}{3}\pi}{8^{3}}\times100",
    r"\frac{-(-2)\pm\sqrt{([-]2)^{2}-4(7)(-80)}{2(7)}",
    r"\sqrt",
    r"[y=\frac{9}{\sqrt{x+1}}",
]


class NastyModel:
    def __init__(self, outputs):
        self.outputs = outputs
        self.i = 0

    async def parse_image(self, png: bytes, kind: str = "page"):
        outs = self.outputs
        if kind == "table":
            md = outs[self.i % len(outs)]
            return LayoutResult(md=md, elements=[])
        md = '<table border="1"><tr><td>Q</td><td>Working</td></tr><tr><td>1</td><td>prose text only</td></tr></table>'
        self.i += 1
        return LayoutResult(
            md=md + "\n\nprose and more text without tables",
            elements=[{"label": "table", "bbox_2d": [50, 100, 500, 400], "width": 595, "height": 842}],
        )


def make_pdf(path: Path) -> None:
    import pymupdf as fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "Test", fontname="helv", fontsize=12)
    x0, y0, x1, y1 = 72, 120, 520, 360
    for x in (x0, x0 + 150, x1):
        page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1))
    for y in (y0, y0 + 80, y1):
        page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y))
    page.insert_text((78, y0 + 40), "cell text A", fontname="helv", fontsize=10)
    page.insert_text((78, y0 + 120), "cell text B", fontname="helv", fontsize=10)
    doc.save(str(path))
    doc.close()


def run_pdf(tmp: Path, outputs) -> str:
    pdf = tmp / f"in_{abs(hash(tuple(outputs)))}.pdf"
    make_pdf(pdf)
    out = tmp / (pdf.stem + ".md")
    settings = Settings(api_key="test", base_url="http://localhost", model="glm-ocr")
    asyncio.run(process_pdf(pdf, out, settings, NastyModel(list(outputs)), PageCache(tmp / "cache")))
    return out.read_text(encoding="utf-8")


def structural_clean(md: str) -> bool:
    return not check_structural(md)


if __name__ == "__main__":
    rep = KatexRepairer()
    with tempfile.TemporaryDirectory() as tmp:
        md = run_pdf(Path(tmp), NASTY_MODEL_OUTPUTS)
        assert "<table" not in md.lower(), "raw HTML table leaked"
        assert "\\$" not in md, "escaped dollar leaked"
        for line in md.splitlines():
            if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
                inner = line.strip()[1:-1]
                for cell in re.split(r"(?<!\\)\|", inner):
                    assert cell.count("$") % 2 == 0, f"odd-$ cell: {cell!r} in: {line}"
        if rep.available:
            failures = asyncio.run(rep.verify_markdown(md))
            assert not failures, f"KaTeX failures: {failures[:3]}"
            print("corpus: all math segments render with KaTeX,", end=" ")
        print("corpus test PASSED")
