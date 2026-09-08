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

## Use

```bash
# OCR a folder of PDFs -> out/*.json + assets/*.png
python -m ocrqp ocr samples/ --out out --assets assets

# Build a custom paper from selected questions
python -m ocrqp build --json-dir out \
  --select 0580/41:1(a) 0580/41:2 \
  --out out/custom.md --html out/custom.html --title "Week 3 practice"
```

## Offline demo (no key)

```bash
python examples/demo_mock.py     # synthetic PDF -> JSON -> custom paper
python -m pytest tests/ -q       # test suite (mock backend)
```

## Tuning (once real docs/key are in)

These are the spots designed to be adjusted against real GLM output:

- `client.normalize_response` — confirm the exact `layout_parsing` JSON schema.
- `segment.py` regexes — question/part/marks detection for your paper format.
- `segment.attach_diagrams` — diagram→question attachment heuristic.
- `json_out.document_to_dataset` — the markscheme `answer`/`working`/`notes` split.

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
  caches.py    on-disk OCR result cache
examples/demo_mock.py
tests/test_pipeline.py
```
