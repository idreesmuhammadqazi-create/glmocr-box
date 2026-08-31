# glmocr-box

Self-hosted GLM-OCR as a single Docker container with the **same API as Z.ai's
`ocr.z.ai` / `layout_parsing` endpoint** — swap the base URL and key in your
client code and you're done. Runs on AMD GPUs (RX 570 8GB tested class) via
llama.cpp's Vulkan backend. No NVIDIA, no ROCm required.

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

- Linux with the `amdgpu` kernel driver (any recent distro/Mesa — the RX 570
  works through Vulkan/RADV; you do **not** need ROCm)
- `/dev/dri` present (default everywhere)
- 32GB RAM is plenty; layout model runs on CPU
- Docker + docker compose plugin

## Troubleshooting

- `docker compose logs -f glm-ocr` — all three services log here
- `docker compose exec glm-ocr vulkaninfo --summary` — must list your RX 570
  as a RADV device. If not: `usermod -aG video,render $USER` on the host and
  re-login
- First OCR request is slow (layout model loads into RAM); subsequent ones are fast
- If OCR output is garbled, make sure the GGUF + mmproj pair came from the same
  release of ggml-org/GLM-OCR-GGUF
