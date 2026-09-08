"""Probe the real GLM layout_parsing API and dump the raw response schema."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocrqp.client import GLMClient
from ocrqp.config import Config
from ocrqp.render import Renderer


def shape(o, depth=0):
    if isinstance(o, dict):
        return {k: shape(v, depth + 1) for k, v in o.items()}
    if isinstance(o, list):
        return [shape(o[0], depth + 1)] if o else []
    if isinstance(o, str):
        return f"<str len={len(o)}>"
    return type(o).__name__


def main() -> int:
    cfg = Config.from_env()
    print(f"gateway: {cfg.base_url}  ca_bundle: {cfg.ca_bundle}")
    client = GLMClient(cfg)
    with Renderer("samples/0580_w25_ms_41.pdf") as r:
        page = r.render_page(0, cfg.page_dpi)
    print(f"page image: {page.width}x{page.height}")

    try:
        result = client.parse_page(page.image, page_index=0)
    except Exception as e:
        print("ERROR:", repr(e))
        return 1

    print("\n=== normalized ===")
    print("markdown length:", len(result.markdown))
    print("num elements:", len(result.elements))
    from collections import Counter
    print("element labels:", Counter(e.label for e in result.elements))

    print("\n=== raw response shape ===")
    print(json.dumps(shape(result.raw), indent=2)[:3000])
    Path("/tmp/glm_response.json").write_text(json.dumps(result.raw))
    print("\nfull raw payload -> /tmp/glm_response.json")

    print("\n=== markdown head ===")
    print(result.markdown[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
