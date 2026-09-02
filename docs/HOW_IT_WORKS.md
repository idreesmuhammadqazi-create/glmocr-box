# GLM-OCR Box — How it works & how to use it

A practical guide for anyone picking this project up. No prior context needed.

## What this is

**GLM-OCR** (by Z.ai) is a small (0.9B) document-parsing model. You give it a
PDF or image; it gives you back:

- **markdown** — the document as clean text (headings, tables, formulas as LaTeX)
- **layout JSON** — every detected block (text / table / formula / image) with
  its position on the page and its content

There are two ways to get this, with the **same quality**:

| way | what runs where | cost |
|---|---|---|
| **Z.ai API** (hosted) | Z.ai's servers | $0.03 per 1M tokens ≈ **10,000 pages per $1** |
| **Self-hosted** (this repo) | your GPU (even an old RX 570) | electricity only |

This repo contains the self-hosted stack, plus a small **shim** that wraps
either backend behind one identical API.

## The API contract (one endpoint, one call)

```
POST /paas/v4/layout_parsing
Authorization: Bearer <key>
{ "model": "glm-ocr", "file": "<url OR data:application/pdf;base64,...>" }
```

Response:

```jsonc
{
  "md_results": "# Doc title\n...",            // the full markdown
  "layout_details": [ [ {                      // per page, per block:
      "index": 1,
      "label": "text | image | formula | table",
      "bbox_2d": [0.1, 0.1, 0.5, 0.3],         // where it is on the page
      "content": "text / table HTML / LaTeX"
  } ] ],
  "data_info": { "num_pages": 5, "pages": [{ "width": 600, "height": 800 }] },
  "usage": { "prompt_tokens": 1234, "completion_tokens": 5678, "total_tokens": 6912 },
  "request_id": "req_..."
}
```

Optional request flags:

- `"return_crop_images": true` — also returns the actual figures/tables as
  image files (`crop_images`). No extra tokens; they're cut from your PDF.
- `"need_layout_visualization": true` — returns page snapshots with the
  detected boxes drawn on them. Great for debugging.
- `"start_page_id"` / `"end_page_id"` — parse only a page range.

Limits (hosted): PDF ≤ 50MB, up to ~100 pages, single image ≤ 10MB.

**Important:** the markdown and the layout JSON are two views of the same
result, assembled independently — neither is derived from the other. The
exact markdown exists only as the `md_results` string; you cannot rebuild it
from the JSON blocks without losing formatting.

## Quickstart: the `zai()` helper (hosted API, any Linux/Mac)

One-time setup — put your key in an env var and install the helper:

```bash
export ZAI_API_KEY=your-key          # from https://z.ai/manage-apikey/apikey-list
echo 'export ZAI_API_KEY=your-key' >> ~/.bashrc
```

Paste this to install the function (it sends the PDF via a temp file, so PDFs
of any size work — never pass base64 as a direct curl argument, Linux caps
arguments at ~128KB):

```bash
zai() { python3 -c "import base64,json,sys;print(json.dumps({'model':'glm-ocr','file':'data:application/pdf;base64,'+base64.b64encode(open(sys.argv[1],'rb').read()).decode()}))" "$1" > /tmp/zai_req.json && curl -s https://api.z.ai/api/paas/v4/layout_parsing -H "Authorization: Bearer $ZAI_API_KEY" -H "Content-Type: application/json" -d @/tmp/zai_req.json -o /tmp/zai_resp.json -w "elapsed: %{time_total}s\n" && python3 -c "import json;r=json.load(open('/tmp/zai_resp.json'));json.dump(r,open('out.json','w'),ensure_ascii=False,indent=2);print('saved out.json |',len(r.get('md_results','')),'md chars')"; }
```

Add the same `zai() { ... }` line to `~/.bashrc` to make it permanent.

Usage — results (`out.json`) land in the directory you run it from:

```bash
zai path/to/paper.pdf
# view the markdown:
python3 -c "import json;print(json.load(open('out.json'))['md_results'])"
# save it as a file:
python3 -c "import json;open('out.md','w').write(json.load(open('out.json'))['md_results'])"
```

**Key hygiene:** never commit or paste your key anywhere. If a key leaks,
rotate it at https://z.ai/manage-apikey/apikey-list (old key stops working
immediately). Check spend on the same page.

## Deployment options in this repo

| mode | what it is | use when |
|---|---|---|
| `zai()` helper | direct curl to Z.ai | testing, one-off parsing |
| **shim on a VPS** (`UPSTREAM_MODE=zai`) | tiny always-on gateway: client auth, local-file/URL input, page slicing, image embedding — forwards to Z.ai | you want a stable 24/7 API for apps, no GPU anywhere. Runs on a $3-5/mo VM |
| **Colab notebook** (`colab/glmocr_batch.ipynb`) | free T4 batch worker: drop PDFs in Drive inbox, get markdown out | bulk jobs, zero cost, no server |
| **self-host GPU** (compose) | full pipeline on your own NVIDIA/AMD GPU | privacy, no per-page billing, works offline |
| **self-host ROCm/HIP** (`docs/linux-gfx803.md`) | community-ROCm build for old AMD cards (RX 570/580) — vision encoder fully on GPU | self-hosted *and* fast |

The shim is the glue: same request/response shape no matter the backend.

```bash
# shim against Z.ai (no GPU needed anywhere):
export UPSTREAM_MODE=zai ZAI_API_KEY=zai-key OCR_API_KEY=your-client-key
python -m uvicorn shim.app:app --host 0.0.0.0 --port 8000
# then: POST http://localhost:8000/paas/v4/layout_parsing (Bearer your-client-key)
```

The shim also reads a `.env` file in its directory, so config survives restarts.

## How the pipeline works (self-hosted)

```
PDF ──> render pages to images (pymupdf, ~200 DPI)
    ──> layout model (PP-DocLayoutV3)  → text/table/formula/image regions
    ──> each region ──> GLM-OCR model  → text / LaTeX / table HTML
    ──> assemble markdown + layout JSON
```

- The layout model runs via PyTorch → **CPU or NVIDIA CUDA only** (no AMD).
- The OCR model runs via llama.cpp (GGUF) → CUDA, Metal, **Vulkan (any AMD/Intel GPU)**, or CPU.
- On Windows + AMD: vision encoding partially falls back to CPU (llama.cpp
  Vulkan gap on old cards) → big regions get slow. Quality is unaffected.

## Troubleshooting quick list

| symptom | cause / fix |
|---|---|
| `Argument list too long` | base64 passed as a curl argument; use a temp file (`-d @file`) |
| markdown result is empty | the "PDF" you sent was actually an HTML page (check `type test.pdf` starts with `%PDF-`); re-download with a browser User-Agent |
| `401` / invalid key | wrong or leaked-and-rotated key; check env var actually set in that shell |
| first self-hosted request takes minutes | one-time model load + shader compile; later requests are fast |
| images missing from markdown | add `return_crop_images: true`; for offline docs, embed crops as base64 (shim does this with `EMBED_IMAGES=true`) |
| math formulas look wrong | try higher DPI (`PDF_DPI=200+`) or the Q8_0 quant (don't use the pixel-cap patch for quality-critical work) |
