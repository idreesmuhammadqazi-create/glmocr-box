"""OCR client: GLM layout_parsing (real) + offline mock backend.

The client is the only place that talks to the model. Everything downstream
works on the normalized :class:`OCRResult`, so swapping backends is trivial.
"""
from __future__ import annotations

import base64
import io
import sys
from dataclasses import dataclass, field
from typing import Callable, Protocol

import requests
from PIL import Image

from .config import Config


# --------------------------------------------------------------------------- #
# Normalized result model
# --------------------------------------------------------------------------- #
@dataclass
class LayoutElement:
    """One detected layout element on a page."""

    label: str  # e.g. "table", "image", "text", "title", "formula"
    bbox_2d: tuple[float, float, float, float]  # pixels, in the submitted image
    content: str | None = None

    def is_table(self) -> bool:
        return self.label.lower() in {"table", "table_full"}

    def is_image(self) -> bool:
        return self.label.lower() in {"image", "figure", "picture", "chart"}


@dataclass
class OCRResult:
    markdown: str
    elements: list[LayoutElement] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class OCRClient(Protocol):
    def parse_page(self, image: Image.Image, *, page_index: int) -> OCRResult:
        ...


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def image_to_data_url(image: Image.Image, fmt: str = "PNG") -> str:
    """Encode a PIL image as a data URL (glm-ocr requires this form)."""
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/{fmt.lower()};base64,{b64}"


def _as_bbox(value) -> tuple[float, float, float, float] | None:
    try:
        x0, y0, x1, y1 = (float(v) for v in value[:4])
        return (x0, y0, x1, y1)
    except Exception:
        return None


def normalize_response(payload: dict) -> OCRResult:
    """Tolerantly normalize a glm-ocr layout_parsing response.

    The exact schema can vary between gateways/versions, so we probe a few
    shapes. Adjust here once the real docs/response are in hand.
    """
    data = payload.get("data", payload) if isinstance(payload, dict) else {}

    markdown = (
        data.get("md_results")
        or data.get("markdown")
        or data.get("md")
        or ""
    )

    elements: list[LayoutElement] = []
    details = data.get("layout_details") or data.get("layout") or []
    # layout_details is commonly a list-of-lists (one inner list per page);
    # flatten defensively.
    flat: list = []
    for item in details:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    for el in flat:
        if not isinstance(el, dict):
            continue
        bbox = _as_bbox(el.get("bbox_2d") or el.get("bbox") or el.get("box"))
        if bbox is None:
            continue
        elements.append(
            LayoutElement(
                label=str(el.get("label") or el.get("type") or "text"),
                bbox_2d=bbox,
                content=el.get("content") or el.get("text"),
            )
        )
    return OCRResult(markdown=markdown, elements=elements, raw=payload)


# --------------------------------------------------------------------------- #
# Real GLM backend
# --------------------------------------------------------------------------- #
# Real GLM backend
# --------------------------------------------------------------------------- #
class GLMClient:
    def __init__(self, config: Config):
        config.validate()
        self.config = config
        self.url = f"{config.base_url}/layout_parsing"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            }
        )
        if config.ca_bundle:
            self.session.verify = config.ca_bundle

    def parse_page(self, image: Image.Image, *, page_index: int) -> OCRResult:
        last_detail = ""
        for fmt in ("PNG", "JPEG"):
            body = {
                "model": self.config.model,
                "file": image_to_data_url(image, fmt=fmt),
            }
            resp = self.session.post(
                self.url,
                json=body,
                timeout=self.config.timeout_s,
            )
            if resp.status_code < 400:
                return normalize_response(resp.json())
            # Surface the server's error body; retry once with JPEG if the
            # PNG payload is rejected (size limit / decode issue).
            try:
                err = resp.json().get("error", {})
                detail = err.get("message", "") or resp.text[:300]
            except Exception:
                detail = resp.text[:300]
            print(
                f"[glm] {fmt} rejected [{resp.status_code}]: {detail!r}",
                file=sys.stderr,
            )
            last_detail = detail
        raise RuntimeError(f"GLM layout_parsing failed: {last_detail}")



# --------------------------------------------------------------------------- #
# Mock backend (offline, no key) — for development & tests
# --------------------------------------------------------------------------- #
# A handler receives the page image and returns an OCRResult. Tests/scripts
# supply their own; the default returns an empty page.
MockHandler = Callable[[Image.Image, int], OCRResult]


def _default_handler(image: Image.Image, page_index: int) -> OCRResult:
    return OCRResult(markdown="", elements=[], raw={"mock": True})


class MockClient:
    """Offline stand-in. Supply a handler to script realistic responses."""

    def __init__(self, handler: MockHandler | None = None):
        self.handler = handler or _default_handler

    def parse_page(self, image: Image.Image, *, page_index: int) -> OCRResult:
        return self.handler(image, page_index)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def make_client(config: Config, mock_handler: MockHandler | None = None) -> OCRClient:
    if config.backend == "mock":
        return MockClient(mock_handler)
    return GLMClient(config)
