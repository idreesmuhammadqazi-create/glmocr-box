"""Inspect cached pass-1 markdown for a PDF (debugging aid)."""
from pathlib import Path

from ocrqp.caches import ResultCache
from ocrqp.config import Config
from ocrqp.render import Renderer


def main() -> int:
    import sys

    pdf_path = Path(sys.argv[1])
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    cfg = Config.from_env()
    cache = ResultCache(cfg.cache_dir)
    mt = pdf_path.stat().st_mtime
    with Renderer(pdf_path) as r:
        n = min(pages, r.page_count)
        for i in range(n):
            ck = (str(pdf_path), mt, i + 1, "pass1", cfg.page_dpi)
            res = cache.get(*ck)
            print(f"===== PAGE {i+1} =====")
            print((res.markdown if res else "NOT-CACHED")[:2000])
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())