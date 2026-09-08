"""PDF rendering and cropping helpers (PyMuPDF)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


@dataclass
class PageImage:
    """A rendered page plus the scale between PDF points and pixels."""

    index: int  # 0-based page number
    image: Image.Image
    scale: float  # pixels per PDF point (dpi/72)

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


class Renderer:
    """Holds an open PDF so pages and regions can be rendered at any DPI."""

    def __init__(self, pdf_path: str | Path):
        self.path = str(pdf_path)
        self.doc = fitz.open(self.path)

    def __enter__(self) -> "Renderer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def render_page(self, index: int, dpi: int) -> PageImage:
        zoom = dpi / 72.0
        pix = self.doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return PageImage(index=index, image=img, scale=zoom)

    def render_pages(self, dpi: int) -> list[PageImage]:
        return [self.render_page(i, dpi) for i in range(self.page_count)]

    def render_clip(
        self, index: int, bbox_pt: tuple[float, float, float, float], dpi: int
    ) -> Image.Image:
        """Render a page region (PDF-point bbox) at the given DPI."""
        zoom = dpi / 72.0
        clip = fitz.Rect(*bbox_pt)
        pix = self.doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def crop_px(image: Image.Image, bbox_px: tuple[float, float, float, float]) -> Image.Image:
    """Crop a PIL image by a pixel bbox (x0, y0, x1, y1), clamped to bounds."""
    x0, y0, x1, y1 = bbox_px
    w, h = image.size
    x0 = max(0, min(int(round(x0)), w))
    y0 = max(0, min(int(round(y0)), h))
    x1 = max(0, min(int(round(x1)), w))
    y1 = max(0, min(int(round(y1)), h))
    if x1 <= x0 or y1 <= y0:
        return Image.new("RGB", (1, 1), "white")
    return image.crop((x0, y0, x1, y1))


def pt_bbox_to_px(
    bbox_pt: tuple[float, float, float, float], scale: float
) -> tuple[float, float, float, float]:
    return tuple(v * scale for v in bbox_pt)  # type: ignore[return-value]


def px_bbox_to_pt(
    bbox_px: tuple[float, float, float, float], scale: float
) -> tuple[float, float, float, float]:
    return tuple(v / scale for v in bbox_px)  # type: ignore[return-value]
