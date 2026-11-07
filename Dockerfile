FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core tesseract-ocr tesseract-ocr-ukr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

# ROOT-relative assets the app reads at runtime: ordered schema migrations and
# the curated (non-private) reference library.
COPY migrations ./migrations
COPY data/reference_library.json ./data/reference_library.json
COPY src ./src
RUN uv sync --locked --no-dev

# Private state lives on a volume; the image itself carries no health data.
ENV ANAMNA_DB=/data/anamna.sqlite3 \
    ANAMNA_SOURCES=/data/sources
VOLUME /data
EXPOSE 8000

# Python rather than curl: the slim image has no curl, and a healthcheck that
# cannot run reports "unhealthy" for a perfectly good server.
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3     CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=8).status == 200 else 1)"]

CMD ["uv", "run", "--no-sync", "uvicorn", "anamna.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
