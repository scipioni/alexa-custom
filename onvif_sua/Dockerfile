FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    # uv installs into this project venv; put it on PATH so `onvif-sua` is runnable.
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# uv drives the frozen, reproducible dependency install (same tool + lockfile as
# the native path, so Docker and native resolve to identical versions).
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy the packaging inputs first for better layer caching, then the package.
COPY pyproject.toml uv.lock ./
COPY onvif_sua ./onvif_sua
COPY settings.yaml ./

# Install the frozen deps AND the project EDITABLE into /app/.venv. Editable is
# deliberate: docker-compose bind-mounts the host ./onvif_sua over /app/onvif_sua,
# so after the first build a code edit + `docker compose restart` is served with
# NO rebuild (the running package is the mounted source). A non-editable
# `pip install .` would copy into site-packages and defeat that loop.
RUN uv sync --frozen

RUN mkdir -p /data

# --frozen: never re-resolve the lockfile at runtime; use /app/.venv as-is.
CMD ["uv", "run", "--frozen", "onvif-sua"]
