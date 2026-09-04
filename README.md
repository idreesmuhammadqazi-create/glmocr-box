# ocrpdf — PDF → Markdown OCR pipeline for marking schemes

OCR pipeline that turns PDFs into Markdown using **GLM-OCR**, built for marking schemes where **formulas live inside tables** — the case where the normal single-shot document-parsing route mangles the output.

## How it works

```
PDF ──▶ render each page @200 DPI
  │
  ├─ pass 1: page image ──▶ glm-ocr layout_parsing
  │       returns md_results + layout_details
  │       (element labels + bbox_2d per table)
  │
  ├─ table regions: model bboxes (fallback: PyMuPDF rules / OpenCV lines)
  │
  ├─ pass 2: each table crop re-rendered @300 DPI ──▶ glm-ocr again
  │
  └─ splice rescued tables back over the pass-1 tables ──▶ final .md
```

- Pass 1 gives the page Markdown plus element-level layout data; every element labelled `table` comes with a bounding box in page coordinates.
- Pass 2 re-OCRs each table crop at higher resolution, so formulas inside dense tables (fractions, indices, roots, trig, matrices) survive as LaTeX.
- Splice replaces the pass-1 tables in order with the pass-2 rescues. If positions can't be matched, rescues are appended with a marker comment instead of dropped.
- Geometric table detection (PyMuPDF `find_tables`, OpenCV line fallback for scans) kicks in whenever the model reports no table bboxes.
- Page and table results are cached on disk, so re-runs only pay for work that didn't complete.

Output: one `.md` per PDF, pages separated by `<!-- ===== Page N ===== -->` comments. All tables are GFM pipe tables (`rowspan` cells are expanded by repeating content, `colspan` padded), and a math-cleanup pass converts HTML entities (`&lt;` → `<`), unicode symbols (`≤` → `\le`, `×` → `\times`, …) and repairs unbalanced braces inside `$...$` — so every formula renders with KaTeX/MathJax in GitHub, VS Code, Obsidian, etc.

## Math validation

The OCR model occasionally emits structurally broken LaTeX (a dropped brace changes `\frac{a}{b}` into a one-argument `\frac`). Check any output file against real KaTeX:

```bash
npm install katex
node tools/validate_math.js output.md
```

It extracts every `$...$` / `$$...$$` segment, renders it with `throwOnError: true`, and reports failures with positions.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then add your API key
```

`.env` options:

| Var | Default | Notes |
|---|---|---|
| `ZAI_API_KEY` | — | required (Z.ai and bigmodel.cn keys both work) |
| `ZAI_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | gateway for the `layout_parsing` endpoint |
| `GLM_OCR_MODEL` | `glm-ocr` | |

Gateways: `https://api.z.ai/api/paas/v4` (international) and `https://open.bigmodel.cn/api/paas/v4` (CN) expose the same API with the same key format. If one is unreachable or WAF-blocked from your network, switch `ZAI_BASE_URL` to the other.

Notes from the field:
- `glm-ocr` is served through `POST {base}/layout_parsing` only — it is not a chat-completions model.
- `file` must be a **data URL** (`data:image/png;base64,...`); bare base64 is rejected with error 1214.
- Images ≤ 10 MB, PDFs ≤ 50 MB / ≤ 100 pages.

## Usage

```bash
# single PDF → 0580_w25_ms_41.md
python -m ocrpdf pdfs/0580_w25_ms_41.pdf -o 0580_w25_ms_41.md

# whole folder → out/*.md
python -m ocrpdf pdfs/ -o out/

# tuning
python -m ocrpdf scheme.pdf --dpi 250 --table-dpi 350 --workers 2

# no API calls: render + geometric table detection only
python -m ocrpdf scheme.pdf --dry-run

# ignore cache and re-OCR everything
python -m ocrpdf scheme.pdf --no-cache
```

Or install as a command: `pip install -e .` then use `ocrpdf` instead of `python -m ocrpdf`.

## Tests

```bash
python tests/smoke_test.py
```

Covers splice logic, table-region detection, and a full pipeline run against a mocked OCR client.

## Troubleshooting

- **429s in the log** — expected under concurrency; retries with exponential backoff handle them. Lower `--workers` (default 3) if they get noisy.
- **Tables not detected** — check `--dry-run`. Model bboxes are preferred; the geometric fallback catches pages where the model skips table labelling (e.g. cover pages).
- **`only 0/N rescued tables spliced`** — pass 1 didn't emit the expected `<table>` blocks, so rescues were appended under `<!-- rescued tables (position uncertain) -->`. Content is still there.
