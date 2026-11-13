FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:81a1340fea1e72ad4a8e9a016128b0c61041cf182ea49fd788023e52842bc147

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core tesseract-ocr tesseract-ocr-ukr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

# ROOT-relative assets the app reads at runtime: ordered schema migrations and
# the curated (non-private) reference library.
COPY migrations ./migrations
COPY data/reference_library.json ./data/reference_library.json
COPY src ./src
RUN uv sync --locked --no-dev

# The server runs as this unprivileged account (see docker-entrypoint.sh).
# /app/tmp is the OCR scratch directory the application writes to at runtime;
# everything else under /app stays read-only to it.
RUN groupadd --system --gid 10001 anamna \
    && useradd --system --uid 10001 --gid anamna --home-dir /app --no-create-home --shell /usr/sbin/nologin anamna \
    && mkdir -p /app/tmp /data \
    && chown anamna:anamna /app/tmp /data \
    && /app/.venv/bin/python -m compileall -q /app/src

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

# Private state lives on a volume; the image itself carries no health data.
ENV ANAMNA_DB=/data/anamna.sqlite3 \
    ANAMNA_SOURCES=/data/sources
VOLUME /data
EXPOSE 8000

# Python rather than curl: the slim image has no curl, and a healthcheck that
# cannot run reports "unhealthy" for a perfectly good server.
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=8).status == 200 else 1)"]

# The entrypoint starts as root only to make the data volume writable, then
# drops to `anamna`. The venv's uvicorn is run directly: `uv run` would want a
# writable cache directory the unprivileged account does not have.
ENTRYPOINT ["docker-entrypoint.sh"]
# The access log would print guest-link secrets (/t/<secret>) and search text into the container log.
CMD ["/app/.venv/bin/uvicorn", "anamna.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
