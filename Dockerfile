# syntax=docker/dockerfile:1.7
# Acretia application image (S7.5b). Multi-stage: SPA build -> Python runtime.
# Base images are pinned by digest; bump both tag and digest together.
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

# ---------------------------------------------------------------- stage 1: frontend
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm --mount=type=secret,id=cabundle,required=false \
    if [ -s /run/secrets/cabundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/cabundle; fi \
 && npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- stage 2: runtime
FROM ${PYTHON_IMAGE} AS runtime
# 1 = install requirements-extras.txt (docling + CPU torch, duckdb, formulon); 0 = core only (smaller, faster).
ARG WITH_EXTRAS=1
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System tools run only as subprocesses (GPL/MPL isolation, D-S1-01): soffice, pdftotext, pdftoppm, tesseract.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-calc libreoffice-impress poppler-utils \
      tesseract-ocr tesseract-ocr-ara \
      fonts-dejavu-core fonts-crosextra-carlito fonts-noto-core \
      ca-certificates tini \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

WORKDIR /app
# Dependencies first so code edits do not bust the layer cache.
COPY requirements.txt requirements-extras.txt ./
# Optional BuildKit secret `cabundle` (never stored in a layer): extra CA certificates for builds behind a TLS-inspecting proxy.
#   docker build --secret id=cabundle,src=/path/ca-bundle.crt .
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=secret,id=cabundle,required=false \
    if [ -s /run/secrets/cabundle ]; then export PIP_CERT=/run/secrets/cabundle SSL_CERT_FILE=/run/secrets/cabundle; fi \
 && pip install -r requirements.txt \
 && if [ "$WITH_EXTRAS" = "1" ]; then \
      if grep -qi '^docling' requirements-extras.txt; then \
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
      fi; \
      sed 's/#.*//' requirements-extras.txt | grep -v '^[[:space:]]*$' > /tmp/extras.txt \
      && pip install -r /tmp/extras.txt && rm /tmp/extras.txt; \
    fi

# Unprivileged user; writable state lives only in /data and /tmp (the root filesystem can be read-only).
RUN groupadd --gid 10001 acretia \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin acretia \
 && mkdir -p /data/storage /data/raw /data/cache \
 && chown -R 10001:10001 /data

COPY open_multiples.py ./
COPY om ./om
COPY src ./src
COPY --from=frontend /build/frontend/dist ./frontend/dist
# Relative paths used by the engines resolve into the data volume.
RUN ln -s /data/storage /app/storage && ln -s /data/raw /app/data

ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HOME=/data/cache/hf \
    ACRETIA_FRONTEND_DIST=/app/frontend/dist \
    ACRETIA_BLOB_ROOT=/data/storage/blobs \
    ACRETIA_KV_PATH=/data/storage/kv.sqlite \
    ACRETIA_DB=/data/storage/acretia.sqlite \
    ACRETIA_PORT=8791

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8791

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import os,urllib.request as u;u.urlopen('http://127.0.0.1:'+os.environ.get('ACRETIA_PORT','8791')+'/api/v1/healthz',timeout=4).read()" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
# ACRETIA_ALLOWED_HOSTS is mandatory when binding 0.0.0.0 (set by docker-compose.yml).
CMD ["sh", "-c", "exec python -m om.api serve --host 0.0.0.0 --port \"${ACRETIA_PORT}\" --data /data/app"]
