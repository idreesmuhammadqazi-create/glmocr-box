"""Pipeline orchestration: PDF -> processed document with per-question parts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .caches import ResultCache
from .client import OCRClient
from .config import Config
from .layout import denormalize_bboxes, image_bboxes, resolve_table_bboxes
from .layout import denormalize_bboxes, image_bboxes, resolve_table_bboxes
from .pdftext import (
    apply_textlayer_marks, clean_junk, inject_question_numbers,
    orphan_marks, question_marks, question_numbers, textlayer_page_text,
)
from .render import Renderer, crop_px, px_bbox_to_pt
from .render import Renderer, crop_px, px_bbox_to_pt
from .segment import (
    QUESTION_RE, PART_RE, QuestionPart, attach_diagrams, segment_page,
    extract_tables, is_markscheme_table, parse_html_table,
)
from .splice import splice_tables


@dataclass
class ProcessedPage:
    index: int  # 1-based page number
    markdown: str  # pass-1 markdown with rescued tables spliced in
    parts: list[QuestionPart] = field(default_factory=list)
    diagrams: list[str] = field(default_factory=list)  # asset paths on this page


@dataclass
class ProcessedDocument:
    source_pdf: str
    pages: list[ProcessedPage] = field(default_factory=list)


def _save_asset(image, assets_dir: Path, stem: str, page: int, n: int) -> str:
    assets_dir.mkdir(parents=True, exist_ok=True)
    name = f"{stem}_p{page}_fig{n}.png"
    path = assets_dir / name
    image.save(path, format="PNG")
    return str(path)


def process_pdf(
    pdf_path: str | Path,
    client: OCRClient,
    config: Config,
    assets_dir: str | Path,
) -> ProcessedDocument:
    """Run the full two-pass pipeline over one PDF."""
    pdf_path = Path(pdf_path)
    assets_dir = Path(assets_dir).resolve()  # store absolute paths in the JSON
    cache = ResultCache(config.cache_dir)
    stem = pdf_path.stem.replace(" ", "_")
    doc = ProcessedDocument(source_pdf=str(pdf_path))
    carry_num: str | None = None  # last question number seen (continuations)

    with Renderer(pdf_path) as renderer:
        for i in range(renderer.page_count):
            page = renderer.render_page(i, config.page_dpi)
            pno = i + 1

            # ---- Pass 1: full page ------------------------------------- #
            ck = (str(pdf_path), pdf_path.stat().st_mtime, pno, "pass1", config.page_dpi)
            pass1 = cache.get(*ck)
            # ---- Pass 1: full page ------------------------------------- #
            ck = (str(pdf_path), pdf_path.stat().st_mtime, pno, "pass1", config.page_dpi)
            pass1 = cache.get(*ck)
            if pass1 is None:
                pass1 = client.parse_page(page.image, page_index=i)
                cache.set(pass1, *ck)

            # Digital PDFs: glm-ocr drops isolated margin question numbers
            # ("3" alone in the top-left box); re-inject from the text layer.
            md1 = inject_question_numbers(pass1.markdown, question_numbers(renderer.doc[i]))

            # glm-ocr sometimes returns ONLY the header markers for sparse
            # pages (answer-space-only continuation pages). Digital PDFs: fall
            # back to the text layer when OCR produced nothing meaningful.
            strip_markers = lambda t: [
                ln for ln in t.splitlines()
                if ln.strip() and not ln.strip().startswith("![")
                and "Cambridge University Press" not in ln
            ]
            if len("".join(strip_markers(md1)).strip()) < 20:
                tlt = textlayer_page_text(renderer.doc[i])
                if len(tlt.strip()) >= 20:
                    md1 = tlt
            if pass1 is None:
                pass1 = client.parse_page(page.image, page_index=i)
                cache.set(pass1, *ck)

            # ---- Table rescue: pass 2 on each small embedded table crop ---- #
            # Skip rescue for tables that cover most of the page (e.g. a
            # markscheme whose whole content is one table): pass 1 already
            # OCR'd it well, and re-OCRing a full-page crop is slow/wasteful.
            table_boxes = resolve_table_bboxes(pass1, page.image)
            page_area = float(page.width * page.height) or 1.0
            # If pass 1 already produced a valid markscheme table on this page,
            # trust it. Re-OCRing a big structured table returns a differently-
            # structured table (rowspan lost) and the splice would corrupt it.
            page_has_ms_table = any(
                is_markscheme_table(parse_html_table(t))
                for t, _ in extract_tables(md1)
            )
            rescued: list[str] = []
            for tb in table_boxes:
                area_frac = ((tb[2] - tb[0]) * (tb[3] - tb[1])) / page_area
                skip = (not config.table_rescue
                        or page_has_ms_table
                        or area_frac > config.rescue_max_area)
                if skip:
                    rescued.append("")  # keep the pass-1 table for this one
                    continue
                bbox_pt = px_bbox_to_pt(tb, page.scale)
                clip = renderer.render_clip(i, bbox_pt, config.table_dpi)
                rk = (str(pdf_path), pdf_path.stat().st_mtime, pno, "pass2",
                      config.table_dpi, tuple(round(v, 1) for v in tb))
                r = cache.get(*rk)
                if r is None:
                    r = client.parse_page(clip, page_index=i)
                    cache.set(r, *rk)
                rescued.append(r.markdown)
            spliced = clean_junk(splice_tables(md1, rescued))

            # ---- Diagram cropping -------------------------------------- #
            img_boxes = denormalize_bboxes(
                image_bboxes(pass1), page.width, page.height
            )
            area = float(page.width * page.height) or 1.0
            img_boxes = [
                ib for ib in img_boxes
                if ((ib[2] - ib[0]) * (ib[3] - ib[1])) / area >= config.min_figure_area
            ]
            asset_paths: list[str] = []
            for n, ib in enumerate(img_boxes, start=1):
                crop = crop_px(page.image, ib)
                asset_paths.append(_save_asset(crop, assets_dir, stem, pno, n))

            # ---- Continuation pages carry the previous question number ---- #
            # glm-ocr drops margin numbers on continuation pages; without a
            # leading number split_questions drops the whole page's text.
            starts_numbered = any(
                m and len(m.group(1)) <= 2 and not PART_RE.match(ln)
                for ln in spliced.splitlines()
                for m in [QUESTION_RE.match(ln)]
            )
            if carry_num and spliced.strip() and not starts_numbered:
                spliced = f"{carry_num} {spliced.lstrip()}"

            # ---- Segment into questions + attach diagrams --------------- #
            parts = segment_page(spliced, page=pno)
            # Digital PDFs: recover marks brackets ([N]) dropped from margins.
            try:
                apply_textlayer_marks(parts, question_marks(renderer.doc[i]))
                if not parts:
                    pass
                else:
                    orphans = orphan_marks(renderer.doc[i])
                    if orphans:
                        it = iter(orphans)
                        for p in parts:
                            if p.marks is None:
                                p.marks = next(it, None)
            except Exception:
                pass  # scanned PDFs have no usable text layer
            attach_diagrams(parts, img_boxes, asset_paths, page_height=page.height)

            # Track the current question number for continuation pages.
            for p in reversed(parts):
                m = re.match(r"^(\d{1,2})", p.id or "")
                if m:
                    carry_num = m.group(1)
                    break

            doc.pages.append(
                ProcessedPage(index=pno, markdown=spliced, parts=parts, diagrams=asset_paths)
            )
    return doc
