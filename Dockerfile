# Codelith in one container: the API, the studio it serves, and the database.
#
# One image rather than two plus a proxy, because the thing somebody wants is an
# address to open. The studio is built here and served by FastAPI from the same origin,
# so there is one port and no CORS between them.
#
# **The model is not in here, and cannot be.** Analysis needs one, it runs on your
# machine, and inside a container `localhost` is the container. Reach the host with
# `host.docker.internal` — the compose file sets that up, and the studio says so where
# you configure a model.

# ── The studio ───────────────────────────────────────────────────────────────
FROM node:20-slim AS studio

WORKDIR /ui

RUN corepack enable

# Manifest first, so a source-only change does not reinstall the world.
COPY ui/package.json ui/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY ui/ ./

# Empty on purpose: `api.ts` reads VITE_API_URL and falls back to localhost:8000, which
# is right for two dev servers and wrong here. An empty value makes every request
# same-origin, which is what being served by the API means.
ENV VITE_API_URL=""

# `pnpm build` is typecheck, then two render checks that stand up a Vite server and
# assert what the markdown and highlighting pipelines actually produce, then the
# bundle. If any of them fail the image build fails, which is the point: shipping an
# unbuilt studio would be discovered by a person opening a blank page.
RUN pnpm build


# ── The application ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # The database, the artefacts and the clones all live here. Mount a volume on it
    # or a knowledge base does not survive `docker compose down`.
    CODELITH_HOME=/data

WORKDIR /app

# git is not a build tool here — it is how repositories get cloned at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, from the manifest alone, so the layer survives a code change.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install .

COPY codelith/ ./codelith/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY scripts/ ./scripts/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Into the package, which is where `core/studio.py` looks first and what a wheel
# would carry.
COPY --from=studio /ui/dist/ ./codelith/studio/

# Installed again now the source is present, so the console script and the package
# metadata match what is actually here.
RUN pip install --no-deps -e .

RUN useradd --create-home --uid 10001 codelith \
    && mkdir -p /data \
    && chown -R codelith:codelith /data /app
USER codelith

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "codelith.main:app", "--host", "0.0.0.0", "--port", "8000"]
