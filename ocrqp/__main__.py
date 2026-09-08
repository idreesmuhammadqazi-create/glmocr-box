"""Command-line interface.

Usage:
  python -m ocrqp ocr <pdfs...> [--out DIR] [--assets DIR] [--upload]
  python -m ocrqp md <file.json> [--out file.md]
  python -m ocrqp upload <files...> [--collection]
  python -m ocrqp build --json-dir DIR --select PAPER:ID [...] --out paper.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import make_client
from .config import Config
from .json_out import document_to_dataset, write_dataset
from .json_to_md import convert, dataset_to_markdown
from .health import format_report, validate_dataset
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


def _write_md(dataset: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / (Path(dataset["source_pdf"]).stem + ".md")
    path.write_text(dataset_to_markdown(dataset), encoding="utf-8")
    return path


def _make_storage(config: Config):
    from .storage import StorageClient

    storage = StorageClient.from_config(config)
    if not storage.health():
        print("warning: storage.to health check failed", file=sys.stderr)
    return storage


def cmd_ocr(args: argparse.Namespace) -> int:
    config = Config.from_env()
    if args.backend:
        config.backend = args.backend
    client = make_client(config)
    storage = _make_storage(config) if args.upload else None

    pdfs = _iter_pdfs(args.pdfs)
    if not pdfs:
        print("no PDFs found", file=sys.stderr)
        return 1

    for pdf in pdfs:
        print(f"[ocr] {pdf.name} ...", file=sys.stderr)
        doc = process_pdf(pdf, client, config, args.assets)
        dataset = document_to_dataset(doc)
        jpath = write_dataset(dataset, args.out)
        mpath = _write_md(dataset, args.out)
        print(f"  -> {jpath}  ({len(dataset['questions'])} questions)", file=sys.stderr)
        print(f"  -> {mpath}", file=sys.stderr)
        rep = validate_dataset(dataset)
        print("  " + format_report(rep).replace("\n", "\n  "), file=sys.stderr)

        if storage:
            coll = storage.create_collection(expected_file_count=2)
            cid = coll["collection"]["id"]
            for f in (jpath, mpath):
                info = storage.upload_file(f, collection_id=cid)
                print(f"  uploaded {Path(f).name}: {info['file']['url']}", file=sys.stderr)
            print(f"  collection: {coll['collection']['url']}", file=sys.stderr)
    return 0


def cmd_md(args: argparse.Namespace) -> int:
    out = convert(args.json, args.out)
    print(f"-> {out}", file=sys.stderr)
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    config = Config.from_env()
    storage = _make_storage(config)
    cid = None
    if args.collection:
        coll = storage.create_collection(expected_file_count=len(args.files))
        cid = coll["collection"]["id"]
        print(f"collection: {coll['collection']['url']}", file=sys.stderr)
    for f in args.files:
        info = storage.upload_file(f, collection_id=cid)
        print(f"{Path(f).name}: {info['file']['url']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    import json
    worst = 0
    for jf in sorted(Path(args.json_dir).glob("*.json")):
        try:
            ds = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[FAIL] {jf.name}: unreadable ({e})", file=sys.stderr)
            worst = max(worst, 2)
            continue
        rep = validate_dataset(ds, validate_katex_flag=not args.no_katex)
        print(format_report(rep))
        worst = max(worst, {"PASS": 0, "WARN": 1, "FAIL": 2}[rep["verdict"]])
    return 0 if worst < 2 else 1


def cmd_build(args: argparse.Namespace) -> int:
    from .builder import build_custom_paper

    selections = []
    for s in args.select:
        if ":" not in s:
            print(f"bad --select (want PAPER:ID): {s}", file=sys.stderr)
            return 2
        paper, qid = s.split(":", 1)
        selections.append((paper, qid))
    summary = build_custom_paper(args.json_dir, selections, args.out, args.html, title=args.title)
    print(f"built {summary['count']} questions, {summary['total_marks']} marks", file=sys.stderr)
    if summary["missing"]:
        print(f"missing: {summary['missing']}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ocrqp", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("ocr", help="OCR PDFs into per-question JSON + MD")
    o.add_argument("pdfs", nargs="+", help="PDF files or directories")
    o.add_argument("--out", default="out", help="output dir for JSON/MD")
    o.add_argument("--assets", default="assets", help="output dir for diagram PNGs")
    o.add_argument("--backend", choices=["glm", "mock"], default=None)
    o.add_argument("--upload", action="store_true", help="upload JSON+MD to storage.to")
    o.set_defaults(fn=cmd_ocr)

    m = sub.add_parser("md", help="render a dataset JSON to Markdown")
    m.add_argument("json", help="input dataset JSON")
    m.add_argument("--out", required=True, help="output markdown path")
    m.set_defaults(fn=cmd_md)

    u = sub.add_parser("upload", help="upload files to storage.to")
    u.add_argument("files", nargs="+", help="files to upload")
    u.add_argument("--collection", action="store_true", help="group into one collection URL")
    u.set_defaults(fn=cmd_upload)

    r = sub.add_parser("report", help="health-check dataset JSON files")
    r.add_argument("--json-dir", default="out")
    r.add_argument("--no-katex", action="store_true", help="skip KaTeX validation")
    r.set_defaults(fn=cmd_report)

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
