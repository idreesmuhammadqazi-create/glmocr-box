# ocrpdf — PDF → Markdown OCR pipeline for marking schemes

OCR pipeline that turns PDFs into Markdown using **GLM-OCR** via the Z.ai API, built for marking schemes where **formulas live inside tables** — the case where normal document-parsing routes fall apart.

## How it works

```
PDF ──▶ render page @200 DPI ──▶ pass 1: full-page OCR (glm-ocr)
  │
  ├──▶ detect table regions (PyMuPDF rules, OpenCV line fallback)
  │
  └──▶ render each table crop @300 DPI ──▶ pass 2: per-table OCR
                                            (table + LaTeX prompt)
       ──▶ splice rescued tables back into the page Markdown ──▶ final .md
```

- **Pass 1** transcribes the whole page with a prompt that forces LaTeX for every formula and `<!--TABLE-->` markers before each table.
- **Table detection** finds ruled tables geometrically: PyMuPDF's `find_tables` for born-digital PDFs, OpenCV line-detection for scanned pages.
- **Pass 2** re-OCRs each table crop at higher DPI with a dedicated prompt: every row/column kept, every formula in LaTeX.
- **Splice** replaces the (often mangled) pass-1 tables with the pass-2 rescues. If replacement positions can't be matched, rescued tables are appended with a marker comment instead of lost.
- Page results are cached, so re-runs only pay for pages that failed or changed.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then add your Z.ai API key
```

`.env` options:

| Var | Default | Notes |
|---|---|---|
| `ZAI_API_KEY` | — | required |
| `ZAI_BASE_URL` | `https://api.z.ai/api/paas/v4` | any OpenAI-compatible endpoint works |
| `GLM_OCR_MODEL` | `glm-ocr` | model name |

## Usage

```bash
# single PDF → sample.md
python -m ocrpdf scheme.pdf -o scheme.md

# whole folder → out/*.md
python -m ocrpdf pdfs/ -o out/

# tuning
python -m ocrpdf scheme.pdf --dpi 250 --table-dpi 350 --workers 4

# no API calls: just render + show detected table regions
python -m ocrpdf scheme.pdf --dry-run

# ignore cache and re-OCR everything
python -m ocrpdf scheme.pdf --no-cache
```

Or install as a command: `pip install -e .` then use `ocrpdf` instead of `python -m ocrpdf`.

## Output format

One `.md` per PDF. Pages are separated by `---` and `<!-- ===== Page N ===== -->` comments. Tables inside pages are Markdown pipe tables (or HTML `<table>` when merged cells demand it); formulas are LaTeX (`$...$` / `$$...$$`).

## Tests

```bash
python tests/smoke_test.py
```

Covers splice logic, table-region detection, and a full pipeline run against a mocked OCR client.

## Troubleshooting

- **429 / rate limits** — lower `--workers` (default 3). Retries with exponential backoff are built in.
- **Tables not detected on scans** — check `--dry-run`; if regions are missed, the pages still get pass-1 OCR and pass-1 tables are kept. Detection thresholds live in `ocrpdf/render.py`.
- **Model ignores `<!--TABLE-->` markers** — splice falls back to locating pipe/HTML table blocks in order; worst case rescued tables are appended at the end of the page with a marker comment.
