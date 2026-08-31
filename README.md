# glmocr-box

Self-hosted GLM-OCR as a single Docker container with the **same API as Z.ai's
`ocr.z.ai` / `layout_parsing` endpoint** — swap the base URL and key in your
client code and you're done.

One image, runs everywhere Docker runs:

| host | command | speed |
|---|---|---|
| Linux + any GPU (AMD/Intel, `/dev/dri`) | `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build` | GPU-fast |
| Windows / macOS Docker Desktop, or Linux without GPU | `docker compose up -d --build` | CPU-only (slow: ~1-3 min/page on old CPUs) |

Windows Docker Desktop **cannot see AMD GPUs** in containers — GPU mode
requires a Linux host (the RX 570 works there via Vulkan/RADV, no ROCm).

## Stack (all inside one container)

```
your code ──> shim :8000  POST /paas/v4/layout_parsing   (Bearer auth, page ranges,
                │                                         embeds images into MD)
                ▼
             glmocr SDK server :5002  (PP-DocLayoutV3 layout analysis on CPU,
                │                      markdown + JSON formatting)
                ▼
             llama-server :8080  (GLM-OCR GGUF on your GPU via Vulkan)
```

## One command

```bash
cp .env.example .env      # set your API key, then:
# Linux with GPU:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
# CPU-only (Windows/macOS/no-GPU Linux):
docker compose up -d --build
```

First start downloads the GGUF models (~2.2GB) into `./models` and the layout
model into the `glmocr-cache` volume — needs internet once. After that it runs
fully offline.

Check readiness: `curl http://localhost:8000/health` → `{"status":"ok","upstream":"ok"}`

## Use it (identical to Z.ai's layout_parsing)

```bash
curl -X POST http://localhost:8000/paas/v4/layout_parsing \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"glm-ocr\", \"file\": \"data:application/pdf;base64,$(base64 -w0 doc.pdf)\"}"
```

Response (same field names as Z.ai):

- `md_results` — full document as Markdown (images embedded as base64 data
  URIs by default, so the file renders offline)
- `layout_details` — per-page JSON blocks: `{index, label, bbox_2d, content}`
- `data_info`, `usage`, `id`, `created`, `request_id`
- `crop_images` — array of extracted image crops as data URIs (extra field)

Or run the provided client: `python3 client_example.py http://localhost:8000 YOUR_KEY doc.pdf`
(writes `out.md` + `out.json`).

Switching between this and Z.ai's cloud = change base URL + key only.

## Request fields

| field | notes |
|---|---|
| `file` | URL, `data:<mime>;base64,...` URI, or raw base64. PDF/JPG/PNG, ≤80MB (configurable) |
| `start_page_id`, `end_page_id` | 1-indexed page range (PDF) — sliced before OCR |
| `model` | ignored, always `glm-ocr` |
| `request_id` | echoed back, generated if absent |

`EMBED_IMAGES=false` disables base64 image embedding (markdown keeps raw refs,
`crop_images` is still populated).

## Reuse GGUFs you already downloaded (LM Studio / llama.cpp)

If LM Studio already pulled GLM-OCR GGUFs, copy them instead of re-downloading:

```bash
cp ~/.lmstudio/models/<...>/GLM-OCR-Q8_0.gguf models/
cp ~/.lmstudio/models/<...>/mmproj-GLM-OCR-Q8_0.gguf models/
```

Other quants work too: `MODEL_QUANT=Q4_K_M` (needs `GLM-OCR-Q4_K_M.gguf` +
`mmproj-GLM-OCR-Q4_1.gguf` from ggml-org/GLM-OCR-GGUF).

## Tuning (`.env`)

| var | default | notes |
|---|---|---|
| `OCR_API_KEY` | changeme-please | Bearer key your clients must send |
| `MODEL_QUANT` | Q8_0 | Q8_0 recommended for OCR accuracy |
| `CONTEXT` | 8192 | llama-server context; raise for very dense pages |
| `THREADS` | 4 | CPU threads |
| `PDF_DPI` | 200 | page render DPI (layout + image crops) |
| `EMBED_IMAGES` | true | inline crops into `md_results` |

## Host requirements

- **CPU mode** (Windows/macOS/no-GPU): just Docker. For best CPU speed use a
  quant with `MODEL_QUANT=Q4_K_M`; raise `THREADS` to your core count
- **GPU mode** (Linux only): `amdgpu` (AMD) or `i915/xe` (Intel) kernel driver,
  `/dev/dri` present, user in `video`/`render` groups handled by the compose
  override. The RX 570 works via Vulkan/RADV — you do **not** need ROCm
- RAM: 16GB is fine; the layout model always runs on CPU

## Windows native (no Docker) — guaranteed GPU

Native Windows is the **guaranteed** GPU path on Windows:

1. Install Python 3.10-3.12 from python.org (check "Add to PATH")
2. Double-click `setup.bat` (one time: venv + packages + llama.cpp Vulkan
   build + GGUF models, ~3 GB)
3. Double-click `start.bat` — API on `http://127.0.0.1:8000/paas/v4/layout_parsing`

Same API, same response format as the Docker mode. Edit `.env` for key/quant/
threads (e.g. `MODEL_QUANT=Q4_K_M`, `THREADS=8`).

## Windows + GPU via Docker? (experimental)

Docker Desktop Windows runs containers in WSL2; AMD GPUs are only visible if
WSL2 GPU paravirtualization exposes them:

1. PowerShell (admin): `wsl --update` then `wsl -e ls /dev/dri`
2. If `renderD128` appears, try the GPU override:
   `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`
3. Verify with `docker compose exec glm-ocr vulkaninfo --summary` — a
   "Microsoft Direct3D12" device means llama.cpp uses the GPU (Vulkan→D3D12).
   Otherwise it silently falls back to CPU.

For older AMD cards this often fails at step 1 — then the only guaranteed GPU
options are a Linux host or the native Windows path above.

## Troubleshooting

- `docker compose logs -f glm-ocr` — all three services log here
- **GPU mode**: `docker compose exec glm-ocr vulkaninfo --summary` (vulkan-tools
  installed in image) — must list your GPU as a device (RADV for AMD). If not:
  `sudo usermod -aG video,render $USER` on the host and re-login
- On CPU-only hosts llama.cpp logs "no Vulkan devices found" and falls back to
  CPU automatically — that is expected
- First OCR request is slow (layout model loads into RAM); subsequent ones are fast
- If OCR output is garbled, make sure the GGUF + mmproj pair came from the same
  release of ggml-org/GLM-OCR-GGUF
