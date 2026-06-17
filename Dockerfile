FROM python:3.12-slim

# FP-stability for Silero VAD (see KNOWN_ISSUES.md).
ENV OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_DYNAMIC=FALSE \
    PYTHONUNBUFFERED=1 \
    VAD_PROXY_MODEL_PATH=/app/models/silero_vad.onnx

WORKDIR /app

# onnxruntime needs libgomp on Debian slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src/ src/
COPY scripts/ scripts/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN python scripts/download_models.py

RUN mkdir -p /app/logs /app/data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"

CMD ["vad-proxy", "serve"]
