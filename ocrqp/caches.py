"""On-disk cache for OCR results so re-runs only pay for unfinished work."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .client import LayoutElement, OCRResult


def _key(*parts: object) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class ResultCache:
    def __init__(self, cache_dir: str | Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, *parts: object) -> OCRResult | None:
        key = _key(*parts)
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        elements = [
            LayoutElement(label=e["label"], bbox_2d=tuple(e["bbox_2d"]), content=e.get("content"))
            for e in data.get("elements", [])
        ]
        return OCRResult(markdown=data.get("markdown", ""), elements=elements, raw=data.get("raw", {}))

    def set(self, result: OCRResult, *parts: object) -> None:
        key = _key(*parts)
        payload = {
            "markdown": result.markdown,
            "elements": [
                {"label": e.label, "bbox_2d": list(e.bbox_2d), "content": e.content}
                for e in result.elements
            ],
            "raw": result.raw,
        }
        self._path(key).write_text(json.dumps(payload), encoding="utf-8")
