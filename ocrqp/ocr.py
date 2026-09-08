"""Pipeline orchestration: PDF -> processed document with per-question parts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .caches import ResultCache
from .client import OCRClient
from .config import Config
from .layout import image_bboxes, resolve_table_bboxes
from .render import Renderer, crop_px, px_bbox_to_pt
from .segment import QuestionPart, attach_diagrams, segment_page
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
    assets_dir = Path(assets_dir)
    cache = ResultCache(config.cache_dir)
    stem = pdf_path.stem.replace(" ", "_")
    doc = ProcessedDocument(source_pdf=str(pdf_path))

    with Renderer(pdf_path) as renderer:
        for i in range(renderer.page_count):
            page = renderer.render_page(i, config.page_dpi)
            pno = i + 1

            # ---- Pass 1: full page ------------------------------------- #
            ck = (str(pdf_path), pdf_path.stat().st_mtime, pno, "pass1", config.page_dpi)
            pass1 = cache.get(*ck)
            if pass1 is None:
                pass1 = client.parse_page(page.image, page_index=i)
                cache.set(pass1, *ck)

            # ---- Table rescue: pass 2 on each small embedded table crop ---- #
            # Skip rescue for tables that cover most of the page (e.g. a
            # markscheme whose whole content is one table): pass 1 already
            # OCR'd it well, and re-OCRing a full-page crop is slow/wasteful.
            table_boxes = resolve_table_bboxes(pass1, page.image)
            page_area = float(page.width * page.height) or 1.0
            rescued: list[str] = []
            for tb in table_boxes:
                area_frac = ((tb[2] - tb[0]) * (tb[3] - tb[1])) / page_area
                if not config.table_rescue or area_frac > config.rescue_max_area:
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

            spliced = splice_tables(pass1.markdown, rescued)

            # ---- Diagram cropping -------------------------------------- #
            img_boxes = image_bboxes(pass1)
            asset_paths: list[str] = []
            for n, ib in enumerate(img_boxes, start=1):
                crop = crop_px(page.image, ib)
                asset_paths.append(_save_asset(crop, assets_dir, stem, pno, n))

            # ---- Segment into questions + attach diagrams --------------- #
            parts = segment_page(spliced, page=pno)
            attach_diagrams(parts, img_boxes, asset_paths, page_height=page.height)

            doc.pages.append(
                ProcessedPage(index=pno, markdown=spliced, parts=parts, diagrams=asset_paths)
            )
    return doc
