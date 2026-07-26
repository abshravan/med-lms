# Multi-stage build for the FastAPI domain API.
#
# `base` holds the runtime dependencies, `development` adds dev tooling and hot
# reload, `production` is the lean, non-root default.

# ── base ─────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# `curl` is here for container healthchecks; nothing else is installed to keep
# the attack surface small.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer is separate from source so a code change does not invalidate
# the (slow) dependency install.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install "uv>=0.5" && uv pip install --system -e .

# ── development ──────────────────────────────────────────────────────────────
FROM base AS development

RUN uv pip install --system -e ".[dev]"
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── production ───────────────────────────────────────────────────────────────
FROM base AS production

# Never run as root: a container escape should not start with uid 0.
RUN useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Worker count is set by the orchestrator via UVICORN_WORKERS; the default of 2
# suits a small container. CPU-bound work belongs in the worker service, not here.
ENV UVICORN_WORKERS=2
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]
