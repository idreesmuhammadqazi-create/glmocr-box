import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import List, Optional

import pymupdf as fitz

from .client import OcrClient
from .config import Settings
from .mathmd import mathify
from .render import (
    detect_table_rects,
    render_clip_png,
    render_page_png,
    table_rects_from_elements,
)
from .splice import splice_tables

log = logging.getLogger("ocrpdf")


class PageCache:
    def __init__(self, root: Optional[Path], enabled: bool = True):
        self.root = root
        self.enabled = enabled and root is not None

    def _path(self, pdf_hash: str, name: str) -> Path:
        assert self.root is not None
        d = self.root / pdf_hash
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def get(self, pdf_hash: str, name: str) -> Optional[str]:
        if not self.enabled:
            return None
        p = self._path(pdf_hash, name)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    def put(self, pdf_hash: str, name: str, text: str) -> None:
        if not self.enabled:
            return
        self._path(pdf_hash, name).write_text(text, encoding="utf-8")

    def get_json(self, pdf_hash: str, name: str):
        raw = self.get(pdf_hash, name)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def put_json(self, pdf_hash: str, name: str, obj) -> None:
        self.put(pdf_hash, name, json.dumps(obj))


async def process_pdf(
    pdf_path: Path,
    out_path: Path,
    settings: Settings,
    client: OcrClient,
    cache: PageCache,
    dry_run: bool = False,
) -> dict:
    started = time.time()
    pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    doc = fitz.open(pdf_path)
    log.info("%s: %d pages", pdf_path.name, len(doc))

    sem = asyncio.Semaphore(settings.workers)

    async def handle_page(idx: int, page: fitz.Page) -> str:
        async with sem:
            try:
                return await _process_page(idx, page, settings, client, cache, pdf_hash, dry_run)
            except Exception as e:
                log.error("[page %d] failed: %s (re-run to fill this page from cache)", idx + 1, e)
                return f"_(OCR failed for page {idx + 1}: {e})_"

    pages = await asyncio.gather(*[handle_page(i, doc[i]) for i in range(len(doc))])
    doc.close()

    parts = [f"# {pdf_path.stem} — OCR\n"]
    for i, content in enumerate(pages, start=1):
        parts.append(f"\n---\n\n<!-- ===== Page {i} ===== -->\n\n{content.strip()}\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    log.info("%s: wrote %s in %.1fs", pdf_path.name, out_path, time.time() - started)
    return {"pages": len(pages), "out": str(out_path)}


async def _process_page(
    idx: int,
    page: fitz.Page,
    settings: Settings,
    client: OcrClient,
    cache: PageCache,
    pdf_hash: str,
    dry_run: bool,
) -> str:
    t0 = time.time()
    page_png = render_page_png(page, settings.page_dpi)
    stem = f"page_{idx + 1:03d}_d{settings.page_dpi}_{settings.model}"
    page_md = cache.get(pdf_hash, stem + ".md")
    cached_rects = cache.get_json(pdf_hash, stem + ".bboxes.json")

    if page_md is None:
        if dry_run:
            rects = detect_table_rects(page)
            log.info("[page %d] dry run: %d table region(s) detected", idx + 1, len(rects))
            return (f"_(dry run: page {idx + 1}, {len(rects)} table region(s) detected "
                    f"at {', '.join(str(r) for r in rects)})_")
        result = await client.parse_image(page_png, kind="page")
        page_md = result.md
        cache.put(pdf_hash, stem + ".md", page_md)
        rects = table_rects_from_elements(result.elements, page.rect)
        cache.put_json(pdf_hash, stem + ".bboxes.json", [[r.x0, r.y0, r.x1, r.y1] for r in rects])
        if not rects:
            rects = detect_table_rects(page)
            if rects:
                log.info("[page %d] model found no tables; geometric fallback found %d", idx + 1, len(rects))
    else:
        if cached_rects:
            rects = [fitz.Rect(*bb) & page.rect for bb in cached_rects]
        else:
            rects = detect_table_rects(page)

    if dry_run:
        return page_md

    rescued = []
    for k, rect in enumerate(rects):
        rname = f"table_{idx + 1:03d}_{k:02d}_d{settings.table_dpi}.md"
        table_md = cache.get(pdf_hash, rname)
        if table_md is None:
            clip_png = render_clip_png(page, rect, settings.table_dpi)
            result = await client.parse_image(clip_png, kind="table")
            table_md = result.md
            cache.put(pdf_hash, rname, table_md)
        rescued.append(table_md)

    if rescued:
        page_md, n_replaced = splice_tables(page_md, rescued)
        if n_replaced < len(rescued):
            log.warning("[page %d] only %d/%d rescued tables spliced in place",
                        idx + 1, n_replaced, len(rescued))

    page_md = mathify(page_md)

    log.info("[page %d] done in %.1fs (%d table regions)", idx + 1, time.time() - t0, len(rects))
    return page_md
