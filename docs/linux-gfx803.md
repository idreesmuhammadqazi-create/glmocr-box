# Linux (fresh SSD) setup guide — RX 570 / gfx803

Target machine: AMD RX 570 8GB + i7-2nd gen + 16GB RAM, fresh Linux SSD.
Goal: self-hosted GLM-OCR, same API as Z.ai (`POST /paas/v4/layout_parsing`),
in two upgrade phases.

Disk budget: Phase 1 needs ~10GB. Phase 2 (ROCm builds) needs ~60GB free on
the Linux disk. 16GB RAM is enough for the builds (they need exactly that).

---

## Phase 0 — Install Linux

1. On any other PC: download **Ubuntu 24.04 LTS** ISO and write it to a USB
   stick with Rufus/Etcher.
2. Boot the RX 570 box from USB, install Ubuntu (minimal is fine, full disk).
3. After install:
   ```bash
   sudo apt update && sudo apt -y upgrade
   sudo apt install -y git curl docker.io docker-compose-v2 vulkan-tools mesa-vulkan-drivers
   sudo usermod -aG docker,video,render $USER
   ```
4. Log out/in (for group changes), then verify the GPU:
   ```bash
   vulkaninfo --summary | grep -i "polaris\|RX"
   ```
   Must show `AMD RADV POLARIS10`. If not: `sudo modprobe amdgpu` and reboot.

## Phase 1 — Working baseline (Vulkan, ~30 min)

```bash
git clone https://github.com/idreesmuhammadqazi-create/glmocr-box
cd glmocr-box
cp .env.example .env      # set OCR_API_KEY
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

First `up` downloads models (~2.2GB) + builds. Then:

```bash
curl http://localhost:8000/health     # {"status":"ok","upstream":"ok"}
```

This is your fallback: full quality, same speed profile as the Windows setup.

## Phase 2 — ROCm/HIP llama.cpp (the fast path)

Community stack: https://github.com/robertrosenbusch/gfx803_rocm
(ROCm 6.4 rebuilt for gfx803, includes a llama.cpp HIP build.)

```bash
cd ~
git clone https://github.com/robertrosenbusch/gfx803_rocm
cd gfx803_rocm
docker build -f Dockerfile_rocm64_base . -t rocm6_gfx803_base:6.4
# ~30-60 min, ~40GB disk
docker build -f Dockerfile_rocm64_llamacpp . -t rocm64_gfx803_llamacpp:latest
# builds llama.cpp master from source -> includes GLM-OCR support
```

Run the ROCm llama-server (note: models dir shared with the repo clone):

```bash
docker run -d --name llama-hip \
  --device=/dev/kfd --device=/dev/dri \
  --group-add=video --group-add=render \
  --ipc=host --security-opt seccomp=unconfined \
  -p 8080:8080 \
  -v ~/glmocr-box/models:/models:ro \
  rocm64_gfx803_llamacpp:latest \
  llama-server \
    -m /models/GLM-OCR-Q8_0.gguf \
    --mmproj /models/mmproj-GLM-OCR-Q8_0.gguf \
    --host 0.0.0.0 --port 8080 \
    -c 8192 -ngl 99 --alias glm-ocr \
    --flash-attn off -fit off --threads 8
```

If the image's entrypoint differs, check `docker logs llama-hip`; the goal is
`llama-server ... listening on 0.0.0.0:8080` with HIP backend in the log.

Sanity check that vision ops now run on GPU: the load log should show
`graph splits = 1` (or few) for the CLIP graph and no/short CPU compute
buffer line. Compare a direct OCR request timing against Phase 1.

## Phase 2b — Switch the pipeline stack to use it

The bundled compose container starts its own llama-server; disable that and
point it at the ROCm one:

```bash
cd ~/glmocr-box
git pull
# in .env add:  SKIP_LLAMA=1
docker compose -f docker-compose.yml up -d --build
```

With `SKIP_LLAMA=1` the container only runs the glmocr pipeline + shim, and
`ocr_api` in config.yaml already points at `127.0.0.1:8080` where the ROCm
container listens. Rollback = remove `SKIP_LLAMA=1` and use the gpu compose
override again.

Alternative (no docker for glmocr/shim): run them in a host venv:

```bash
cd ~/glmocr-box
python3 -m venv .venv && . .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install "glmocr[selfhosted,server]" fastapi "uvicorn[standard]" httpx pymupdf pillow
python -m glmocr.server --config config.yaml &
python -m uvicorn shim.app:app --host 0.0.0.0 --port 8000
```

## Phase 3 — Optional: layout model on GPU

The gfx803_rocm repo also builds **PyTorch 2.6 for gfx803**
(`Dockerfile_rocm64_pytorch`, wheel lands in the container at `/pytorch/dist`).
The glmocr SDK pins `torch>=2.10`, so wiring this in means either building a
newer torch for gfx803 or installing the wheel with `--no-deps` and testing.
Only worth it if layout CPU time (~10-20s/page) still bothers you AFTER
Phase 2 — the vision encoder is the expensive part and it will already be on
GPU by then.

## Troubleshooting

- `docker: permission denied` → re-login after `usermod -aG docker`
- ROCm container can't see GPU → `ls /dev/kfd /dev/dri` must exist;
  `groups` must include video/render; never run with `--user` override
- MIOpen warnings spam → `MIOPEN_LOG_LEVEL=3` env in the container
- llama HIP build complains about gfx803 → make sure the build used the
  repo's base image (it carries the patched rocBLAS); rebuild base first
- HIP out-of-memory → 8GB is tight with big regions; try
  `MODEL_QUANT=Q4_K_M` (models dir keeps both)
- Pipeline returns empty results → check `docker logs llama-hip` for the
  POST arriving; if silent, the OCR server isn't reachable at :8080
