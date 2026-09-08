"""Probe one content page: dump markdown + layout elements."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocrqp.client import GLMClient
from ocrqp.config import Config
from ocrqp.render import Renderer

PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def main() -> int:
    cfg = Config.from_env()
    client = GLMClient(cfg)
    with Renderer("samples/0580_w25_ms_41.pdf") as r:
        page = r.render_page(PAGE, cfg.page_dpi)
    res = client.parse_page(page.image, page_index=PAGE)
    print(f"page index {PAGE}  image {page.width}x{page.height}")
    print("labels:", Counter(e.label for e in res.elements))
    print("\n=== ELEMENTS ===")
    for e in res.elements:
        print(f"  {e.label:8} bbox={[round(v) for v in e.bbox_2d]}")
    print("\n=== MARKDOWN ===")
    print(res.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
