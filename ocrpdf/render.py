import re

import cv2
import pymupdf as fitz
import numpy as np

from typing import List

CV_DETECT_DPI = 150
PAD_FRACTION = 0.015
MIN_TABLE_WIDTH_PT = 70.0
MIN_TABLE_HEIGHT_PT = 30.0
MAX_PAGE_COVERAGE = 0.85


def render_page_png(page: fitz.Page, dpi: int) -> bytes:
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
    return pix.tobytes("png")


def render_clip_png(page: fitz.Page, rect: fitz.Rect, dpi: int) -> bytes:
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, clip=rect)
    return pix.tobytes("png")


def detect_table_rects(page: fitz.Page) -> List[fitz.Rect]:
    rects = _rects_from_find_tables(page)
    if not rects:
        rects = _rects_from_cv(page)
    rects = _merge_overlapping(rects)
    page_area = abs(page.rect)
    result = []
    for r in rects:
        r = fitz.Rect(r.x0 - PAD_FRACTION * page.rect.width,
                      r.y0 - PAD_FRACTION * page.rect.height,
                      r.x1 + PAD_FRACTION * page.rect.width,
                      r.y1 + PAD_FRACTION * page.rect.height) & page.rect
        if r.is_empty:
            continue
        if r.width < MIN_TABLE_WIDTH_PT or r.height < MIN_TABLE_HEIGHT_PT:
            continue
        if abs(r) > MAX_PAGE_COVERAGE * page_area:
            continue
        result.append(r)
    result.sort(key=lambda r: (r.y0, r.x0))
    return result


def _rects_from_find_tables(page: fitz.Page) -> List[fitz.Rect]:
    try:
        finder = page.find_tables()
        return [fitz.Rect(t.bbox) for t in finder.tables]
    except Exception:
        return []


def _rects_from_cv(page: fitz.Page) -> List[fitz.Rect]:
    try:
        pix = page.get_pixmap(dpi=CV_DETECT_DPI, colorspace=fitz.csGRAY)
        img = np.frombuffer(pix.samples, dtype=np.uint8)
        img = img.reshape(pix.height, pix.width)
    except Exception:
        return []

    binary = cv2.adaptiveThreshold(
        ~img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
    )

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(img.shape[1] // 25, 1), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(img.shape[0] // 25, 1)))
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    grid = cv2.add(horiz, vert)

    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 0.15 * img.shape[1] or h < 0.04 * img.shape[0]:
            continue
        if not _has_grid_lines(horiz, vert, x, y, w, h):
            continue
        scale = 72.0 / CV_DETECT_DPI
        rects.append(fitz.Rect(x * scale, y * scale, (x + w) * scale, (y + h) * scale))
    return rects


def _has_grid_lines(horiz: np.ndarray, vert: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
    h_roi = horiz[y:y + h, x:x + w]
    v_roi = vert[y:y + h, x:x + w]
    if h_roi.size == 0 or v_roi.size == 0:
        return False
    inner_h = h_roi[2:-2, :]
    inner_v = v_roi[:, 2:-2]
    if inner_h.size == 0 or inner_v.size == 0:
        return False
    row_hits = (inner_h.sum(axis=1) > 0.5 * inner_h.shape[1] * 255).sum()
    col_hits = (inner_v.sum(axis=0) > 0.5 * inner_v.shape[0] * 255).sum()
    return row_hits >= 1 and col_hits >= 1


def _merge_overlapping(rects: List[fitz.Rect]) -> List[fitz.Rect]:
    rects = sorted(rects, key=lambda r: -abs(r))
    merged: List[fitz.Rect] = []
    for r in rects:
        absorbed = False
        for i, m in enumerate(merged):
            inter = r & m
            if not inter.is_empty and abs(inter) > 0.5 * min(abs(r), abs(m)):
                merged[i] = m | r
                absorbed = True
                break
        if not absorbed:
            merged.append(r)
    return merged
