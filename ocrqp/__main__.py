"""Command-line interface.

Usage:
  python -m ocrqp ocr <pdfs...> [--out DIR] [--assets DIR] [--backend glm|mock]
  python -m ocrqp build --json-dir DIR --select PAPER:ID [...] --out paper.md [--html paper.html]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import make_client
from .config import Config
from .json_out import document_to_dataset, write_dataset
from .ocr import process_pdf


def _iter_pdfs(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            out.extend(sorted(pp.glob("*.pdf")))
        elif pp.suffix.lower() == ".pdf":
            out.append(pp)
        else:
            print(f"skip (not a pdf): {p}", file=sys.stderr)
    return out


def cmd_ocr(args: argparse.Namespace) -> int:
    config = Config.from_env()
    if args.backend:
        config.backend = args.backend
    client = make_client(config)

    pdfs = _iter_pdfs(args.pdfs)
    if not pdfs:
        print("no PDFs found", file=sys.stderr)
        return 1

    for pdf in pdfs:
        print(f"[ocr] {pdf.name} ...", file=sys.stderr)
        doc = process_pdf(pdf, client, config, args.assets)
        dataset = document_to_dataset(doc)
        out = write_dataset(dataset, args.out)
        print(f"  -> {out}  ({len(dataset['questions'])} questions)", file=sys.stderr)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .builder import build_custom_paper

    selections = []
    for s in args.select:
        if ":" not in s:
            print(f"bad --select (want PAPER:ID): {s}", file=sys.stderr)
            return 2
        paper, qid = s.split(":", 1)
        selections.append((paper, qid))

    summary = build_custom_paper(
        args.json_dir, selections, args.out, args.html, title=args.title
    )
    print(f"built {summary['count']} questions, {summary['total_marks']} marks", file=sys.stderr)
    if summary["missing"]:
        print(f"missing: {summary['missing']}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ocrqp", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("ocr", help="OCR PDFs into per-question JSON")
    o.add_argument("pdfs", nargs="+", help="PDF files or directories")
    o.add_argument("--out", default="out", help="output dir for JSON")
    o.add_argument("--assets", default="assets", help="output dir for diagram PNGs")
    o.add_argument("--backend", choices=["glm", "mock"], default=None)
    o.set_defaults(fn=cmd_ocr)

    b = sub.add_parser("build", help="build a custom paper from selected questions")
    b.add_argument("--json-dir", default="out")
    b.add_argument("--select", nargs="+", required=True, help="PAPER:ID ...")
    b.add_argument("--out", required=True, help="output markdown path")
    b.add_argument("--html", default=None, help="optional output HTML path")
    b.add_argument("--title", default="Custom Paper")
    b.set_defaults(fn=cmd_build)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
