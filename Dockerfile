# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# fp-assessment-rag-inbox — candidate container
# Base: Python 3.12 slim. Two non-root users (candidate, checkpoint) for
# UID separation (RNF-06). Real LLM key is ONLY ever injected into the
# separate `llm-proxy` service — never into the candidate environment
# (RNF-05).
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy \
    PATH="/home/candidate/.local/bin:/root/.local/bin:${PATH}"

# ---------------------------------------------------------------------------
# System deps: build toolchain for native wheels, libpq for asyncpg, git for
# checkpoints, postgres client for the readiness wait loop, tini as init.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      git \
      libpq-dev \
      postgresql-client \
      curl \
      ca-certificates \
      tini \
    && rm -rf /var/lib/apt/lists/*

# uv (fast Python package manager + lockfile) and pre-commit.
RUN pip install --no-cache-dir "uv>=0.4.0" "pre-commit>=3.8.0"

# ---------------------------------------------------------------------------
# Users — RNF-06: checkpoint daemon writes /artifacts as a separate UID so
# the candidate can only read artefacts, not tamper with them.
# ---------------------------------------------------------------------------
RUN groupadd --gid 1000 candidate \
    && useradd --uid 1000 --gid candidate --shell /bin/bash --create-home candidate \
    && groupadd --gid 2000 checkpoint \
    && useradd --uid 2000 --gid checkpoint --shell /bin/bash --create-home checkpoint

WORKDIR /work

# ---------------------------------------------------------------------------
# Dependency layer — copy only the manifests first so `uv sync` is cached
# and rebuilds are fast. If uv.lock is absent, uv will generate it at build
# time (see pyproject.toml NOTE).
# ---------------------------------------------------------------------------
COPY --chown=candidate:candidate pyproject.toml ./
COPY --chown=candidate:candidate uv.lock* ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra dev 2>/dev/null \
    || uv sync --extra dev

# ---------------------------------------------------------------------------
# Project source.
# ---------------------------------------------------------------------------
COPY --chown=candidate:candidate . /work

# /artifacts — owned by `checkpoint`, world-readable, write only by checkpoint.
RUN mkdir -p /artifacts /artifacts/llm-trace \
    && chown -R checkpoint:checkpoint /artifacts \
    && chmod 755 /artifacts /artifacts/llm-trace

# Ensure candidate owns /work (but not /artifacts).
RUN chown -R candidate:candidate /work

# Entrypoint script handles Postgres readiness + service dispatch.
COPY --chown=root:root scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000 8001

# Candidate is the default user. The `llm-proxy` and `checkpoint` services
# override this in docker-compose to run as their respective UIDs.
USER candidate

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["app"]
