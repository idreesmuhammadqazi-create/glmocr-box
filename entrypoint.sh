#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/models}"
QUANT="${MODEL_QUANT:-Q8_0}"
MODEL_FILE="$MODEL_DIR/GLM-OCR-$QUANT.gguf"
MMPROJ_FILE="$MODEL_DIR/mmproj-GLM-OCR-$QUANT.gguf"
HF_BASE="https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/main"

download() {
  local dest="$1" url="$2"
  echo "[entrypoint] Downloading $(basename "$dest") ..."
  curl -fL --retry 3 --retry-delay 2 -o "$dest.part" "$url"
  mv "$dest.part" "$dest"
}

if [ ! -f "$MODEL_FILE" ]; then
  download "$MODEL_FILE" "$HF_BASE/GLM-OCR-$QUANT.gguf"
fi
if [ ! -f "$MMPROJ_FILE" ]; then
  download "$MMPROJ_FILE" "$HF_BASE/mmproj-GLM-OCR-$QUANT.gguf"
fi

echo "[entrypoint] Starting llama-server (Vulkan) on :8080 ..."
/app/llama/llama-server \
  -m "$MODEL_FILE" \
  --mmproj "$MMPROJ_FILE" \
  --host 127.0.0.1 --port 8080 \
  -c "${CONTEXT:-8192}" \
  -ngl "${N_GPU_LAYERS:-99}" \
  --alias glm-ocr \
  --flash-attn off -fit off \
  --threads "${THREADS:-4}" \
  > /tmp/llama-server.log 2>&1 &

for i in $(seq 1 120); do
  if curl -sf http://127.0.0.1:8080/health > /dev/null 2>&1; then
    echo "[entrypoint] llama-server is up"
    break
  fi
  if ! kill -0 $! 2> /dev/null; then
    echo "[entrypoint] llama-server failed to start:"
    tail -30 /tmp/llama-server.log
    exit 1
  fi
  sleep 2
done

echo "[entrypoint] Starting glmocr pipeline server on :5002 ..."
python -m glmocr.server --config /app/config.yaml > /tmp/glmocr-server.log 2>&1 &

for i in $(seq 1 120); do
  if curl -sf http://127.0.0.1:5002/health > /dev/null 2>&1; then
    echo "[entrypoint] glmocr server is up"
    break
  fi
  if ! kill -0 $! 2> /dev/null; then
    echo "[entrypoint] glmocr server failed to start:"
    tail -30 /tmp/glmocr-server.log
    exit 1
  fi
  sleep 2
done

echo "[entrypoint] API listening on 0.0.0.0:${PORT:-8000} at /paas/v4/layout_parsing"
exec python -m uvicorn shim.app:app --host 0.0.0.0 --port "${PORT:-8000}"
