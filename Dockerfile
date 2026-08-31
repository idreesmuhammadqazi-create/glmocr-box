FROM ghcr.io/ggml-org/llama.cpp:server-vulkan AS llama

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libvulkan1 mesa-vulkan-drivers vulkan-tools libgomp1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=llama /app/ /app/llama/
ENV LD_LIBRARY_PATH=/app/llama

ENV HF_HOME=/cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

COPY shim/requirements.txt /app/shim/requirements.txt
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /app/shim/requirements.txt \
    && pip install --no-cache-dir "glmocr[selfhosted,server]==0.1.5"

COPY config.yaml /app/config.yaml
COPY shim/ /app/shim/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN useradd -m ocr -u 1000 && mkdir -p /models /cache && chown -R ocr:ocr /app /cache
USER ocr

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
