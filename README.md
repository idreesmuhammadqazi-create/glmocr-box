# ocrqp — IGCSE papers/markschemes → per-question JSON

Turn IGCSE PDFs (question papers **and** marking schemes) into a dataset of
**individual questions** you can render one-by-one, let a user pick from, and
assemble into a **custom paper**. Built for maths, where the hard case is a
**markscheme table with equations inside it** — the thing that breaks a
single-shot OCR pass.

## Why two passes

glm-ocr's single-pass `layout_parsing` mangles formulas that live **inside
tables**. So:

```
PDF → render pages @ page DPI
  pass 1: glm-ocr layout_parsing → markdown + layout_details (table/image bboxes)
  → crop diagrams (image elements) → save PNG assets
  → detect table regions (model bboxes; OpenCV ruled-line fallback)
  → re-render each table crop @ table DPI
  pass 2: glm-ocr each table crop → clean LaTeX
  → splice rescued tables over pass-1 tables
  → segment into questions by number → per-question JSON
```

## Output shape

One JSON per PDF, keyed by question part. Diagrams are cropped PNG files in
`assets/`, referenced by path. Text/equations are Markdown + LaTeX.

```json
{
  "paper": "0580/41", "series": "Oct/Nov 2025", "kind": "question_paper",
  "pages": 16,
  "questions": [
    { "id": "1(b)", "marks": 3, "page": 2,
      "text": "Solve $3x + 2 = 17$.",
      "diagrams": ["assets/0580_w25_qp_41_p2_fig1.png"] }
  ]
}
```

For `kind: "marking_scheme"`, each question also carries `answer` / `working` /
`notes` (best-effort split — see *Tuning* below).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add your ZAI_API_KEY, pick a gateway
```

`.env`:

| Var | Default | Notes |
|---|---|---|
| `ZAI_API_KEY` | — | required for real OCR |
| `ZAI_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | or `https://api.z.ai/api/paas/v4` |
| `GLM_OCR_MODEL` | `glm-ocr` | |
| `OCRQP_BACKEND` | `glm` | `glm` (real) or `mock` (offline) |
| `OCRQP_PAGE_DPI` / `OCRQP_TABLE_DPI` | `200` / `300` | render resolutions |
| Var | Default | Notes |
|---|---|---|
| `ZAI_API_KEY` | — | required for real OCR |
| `ZAI_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | or `https://api.z.ai/api/paas/v4` |
| `GLM_OCR_MODEL` | `glm-ocr` | |
| `OCRQP_BACKEND` | `glm` | `glm` (real) or `mock` (offline) |
| `OCRQP_PAGE_DPI` / `OCRQP_TABLE_DPI` | `200` / `300` | render resolutions |
| `OCRQP_TABLE_RESCUE` | `true` | pass-2 re-OCR of table crops |
| `OCRQP_RESCUE_MAX_AREA` | `0.5` | skip rescue for tables > this page fraction |
| `OCRQP_MIN_FIGURE_AREA` | `0.015` | drop image elements < this page fraction (filters logos) |

## Use

```bash
# OCR a folder of PDFs -> out/*.json + out/*.md + assets/*.png
python -m ocrqp ocr samples/ --out out --assets assets

# ... and upload the JSON+MD to storage.to (one collection URL per PDF)
python -m ocrqp ocr samples/ --out out --assets assets --upload

# Render an existing dataset JSON to Markdown
python -m ocrqp md out/0580_w25_ms_41.json --out out/0580_w25_ms_41.md

# Upload arbitrary files to storage.to
python -m ocrqp upload out/0580_w25_ms_41.json out/0580_w25_ms_41.md --collection

# Build a custom paper from selected questions
python -m ocrqp build --json-dir out \
  --select 0580/41:1(a) 0580/41:2 \
  --out out/custom.md --html out/custom.html --title "Week 3 practice"
```

## Upload to storage.to

`ocr --upload` (and the `upload` command) push files to
[storage.to](https://storage.to/docs/api) using its presigned-R2 REST API
(`init -> PUT bytes -> confirm`). JSON and MD are produced per PDF and grouped
into a **collection** so you get one share URL with both.

- **Anonymous** works out of the box: a random `X-Visitor-Token` is generated
  once and persisted at `.ocrqp-cache/.visitor_token`. Files expire in 3 days.
- Set `STORAGE_TO_TOKEN=<bearer>` for an authenticated account (no expiry/caps).
- `STORAGE_TO_BASE_URL` overrides the API base (default `https://storage.to/api`).

## LaTeX / KaTeX validity

Every math segment is repaired (unicode->LaTeX, dropped `$`, unbalanced `{}`)
and then **validated by rendering with real KaTeX in strict mode**
(`tools/katex_check.js`). Anything still invalid is wrapped in `\text{}` so the
document always renders, and logged under `latex_repairs`. Requires
`cd tools && npm install` (node); without it, structural repair still runs.

## Offline demo (no key)

```bash
python examples/demo_mock.py     # synthetic PDF -> JSON -> custom paper
python -m pytest tests/ -q       # test suite (mock backend)
```

## Status: validated on real markschemes + question papers

Markschemes (all PASS, totals match official maxima, KaTeX 100% valid):

| Paper | Kind | Questions | Marks | KaTeX |
|---|---|---|---|---|
| `0580/41` IGCSE Maths P4 (w25) | mark scheme | 46 | 100 / 100 | 347/347 |
| `9709/22` A-Level Pure 2 (s26) | mark scheme | 12 | 50 / 50 | 230/230 |
| `9709/42` A-Level Mechanics (s26) | mark scheme | 14 | 50 / 50 | 475/475 |
| `9709/61` A-Level Prob & Stats 1 (s26) | mark scheme | 17 | 50 / 50 | 207/207 |
Question papers (validated against the matching mark scheme's ground truth):

| Paper | Result |
|---|---|
| `9709/22` qp (Pure) | 11 of 12 parts, per-part marks **all exactly correct** (46/50). Miss: 5(a), content the OCR dropped entirely. |
| `9709/42` qp (Mechanics) | 13 of 14 parts **PASS**, per-part marks all correct (47/50), 0 LaTeX fallbacks. Miss: 3(b). |
| `0580/42` qp (IGCSE.Ext) | 35 questions, 87/100 marks; 32/39 per-part marks exactly match the ms, 3 off-by-one band boundaries, 4 missing. 12 LaTeX fallbacks. |
Diagrams: 16 figure crops extracted across the qps and attached to the correct
questions (`Q3` log graph, `Q8(a)` geometry, `Q19(b)` stats chart, ...).

### How the qp path recovers what glm-ocr drops

glm-ocr has three systematic failure modes on question papers, all patched
via *digital-PDF text-layer fallbacks* (`ocrqp/pdftext.py`):

1. **Isolated margin elements** — question numbers ("3") and marks brackets
   ("[4]") are separate tiny text boxes that get dropped; re-injected from
   the text layer (numbers before segmentation, marks after, banded per
   question by y-position).
2. **Sparse pages return only header markers** — answer-space-only
   continuation pages come back empty; the full page is rebuilt from the
   text layer.
3. **Dropped content blocks** (e.g. a sketch question) — unrecoverable in
   OCR only; the marks band still records it, so the total reports short.

## Tuning (remaining)

- `9709/22` 5(a) and `9709/42` 3(b): content blocks glm-ocr dropped entirely.
  The marks bands still report them, so totals flag short; a text-layer
  content-rebuild fallback could recover the text.
- `0580/42` 17(a)/8(a)/8(b): three off-by-one marks-band assignments where
  brackets sit close to question-number y-positions (needs band tolerance).
- Pass-2 PNG payloads are sometimes rejected by the gateway (large image
  payloads); the client retries with JPEG automatically.
- `client.normalize_response` — confirmed against the official
  [layout-parsing spec](https://docs.z.ai/api-reference/tools/layout-parsing)
  (fields: `md_results`, `layout_details[].label/bbox_2d/content`). Note: the
  docs describe `bbox_2d` as normalized [0,1] but live responses return pixels;
  `layout.denormalize_bboxes` handles both.

## Layout

```
ocrqp/
  config.py    env/.env config
  render.py    PDF -> page images + high-DPI clip rendering
  client.py    GLM layout_parsing client + offline mock backend
  layout.py    table region detection (model + OpenCV fallback)
  splice.py    merge rescued tables into pass-1 markdown
  segment.py   markdown -> per-question parts + diagram attachment
  ocr.py       pipeline orchestration (two-pass)
  json_out.py  dataset assembly + Cambridge filename parsing
  builder.py   custom paper builder (Markdown + self-contained HTML)
  latex.py     LaTeX repair + KaTeX strict validation
  storage.py   storage.to upload client (presigned R2)
  json_to_md.py dataset JSON -> Markdown
  caches.py    on-disk OCR result cache
examples/demo_mock.py
tests/test_pipeline.py
```
