import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .client import OcrClient
from .config import Settings
from .pipeline import PageCache, process_pdf


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ocrpdf",
        description="OCR PDFs to Markdown with GLM-OCR via Z.ai, with table rescue for formula-dense tables.",
    )
    parser.add_argument("inputs", nargs="+", help="PDF file(s) or directory of PDFs")
    parser.add_argument("-o", "--out", help="Output .md file (single PDF) or directory")
    parser.add_argument("--dpi", type=int, default=None, help="Page render DPI (default 200)")
    parser.add_argument("--table-dpi", type=int, default=None, help="Table crop render DPI (default 300)")
    parser.add_argument("--model", default=None, help="OCR model name (default from env, glm-ocr)")
    parser.add_argument("--workers", type=int, default=None, help="Concurrent page OCR calls (default 3)")
    parser.add_argument("--no-cache", action="store_true", help="Ignore/overwrite cached page results")
    parser.add_argument("--cache-dir", default=".ocrpdf-cache", help="Cache directory (default .ocrpdf-cache)")
    parser.add_argument("--dry-run", action="store_true", help="Render + table detection only, no API calls")
    parser.add_argument("--verify", action="store_true", help="After writing output, verify all math with KaTeX and fail on errors")
    parser.add_argument("--no-katex-repair", action="store_true", help="Skip the KaTeX-driven math repair pass")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    pdfs: list[Path] = []
    for raw in args.inputs:
        p = Path(raw)
        if p.is_dir():
            found = sorted(p.glob("*.pdf")) + sorted(p.glob("*.PDF"))
            if not found:
                logging.error("No PDFs found in %s", p)
                return 1
            pdfs.extend(found)
        elif p.is_file() and p.suffix.lower() == ".pdf":
            pdfs.append(p)
        else:
            logging.error("Not a PDF or directory: %s", p)
            return 1
    if not pdfs:
        logging.error("No input PDFs")
        return 1

    try:
        settings = Settings.from_env()
    except SystemExit as e:
        if not args.dry_run:
            print(e, file=sys.stderr)
            return 1
        settings = Settings(api_key="dry-run")

    if args.dpi:
        settings.page_dpi = args.dpi
    if args.table_dpi:
        settings.table_dpi = args.table_dpi
    if args.model:
        settings.model = args.model
    if args.workers:
        settings.workers = args.workers

    out = Path(args.out) if args.out else None
    if len(pdfs) == 1 and out and out.suffix.lower() == ".md":
        jobs = [(pdfs[0], out)]
    else:
        out_dir = out or Path("out")
        jobs = [(pdf, out_dir / (pdf.stem + ".md")) for pdf in pdfs]

    async def run():
        client = OcrClient(settings)
        try:
            cache = PageCache(Path(args.cache_dir), enabled=not args.no_cache)
            results = []
            for pdf, md_path in jobs:
                r = await process_pdf(pdf, md_path, settings, client, cache, dry_run=args.dry_run,
                                      repair=not args.no_katex_repair)
                results.append(r)
            return results
        finally:
            await client.close()

    results = asyncio.run(run())
    for r in results:
        print(r["out"])
        k = r.get("katex") or {}
        if k.get("checked"):
            print(f"  katex: {k['checked']} segments, {k['repaired']} repaired, {k['failed']} failed")

    if args.verify:
        from .katex_repair import KatexRepairer
        rep = KatexRepairer()
        if not rep.available:
            print(f"verification unavailable: {rep.disabled_reason}", file=sys.stderr)
            return 1
        bad = 0
        for r in results:
            md = Path(r["out"]).read_text(encoding="utf-8")
            failures = asyncio.run(rep.verify_markdown(md))
            for tex, e in failures:
                bad += 1
                print(f"VERIFY FAIL {r['out']}: {e[:120]}\n  tex: {tex[:120]}", file=sys.stderr)
        if bad:
            print(f"verification FAILED: {bad} bad segment(s)", file=sys.stderr)
            return 1
        print("verification PASSED: all math renders with KaTeX")
    return 0


if __name__ == "__main__":
    sys.exit(main())
