# ---------------------------------------------------------------------------
# fp-assessment-rag-inbox — Makefile
# Satisfies RF-010. All targets must work from a clean clone after
# `uv sync --extra dev` or inside the container (which pre-syncs).
# ---------------------------------------------------------------------------

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON       ?= python
UV           ?= uv
PYTEST_ARGS  ?= -v --tb=short
COV_ARGS     ?= --cov=src --cov-report=json:coverage.json --cov-report=term
SEMGREP_OUT  ?= semgrep-report.json
BANDIT_OUT   ?= bandit-report.json
GITLEAKS_OUT ?= gitleaks-report.json
L1_OUT       ?= final-l1.json

.PHONY: help setup run run-db seed test lint format sast secrets score-l1 ci-local checkpoint clean

help:  ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

setup:  ## Install deps, hooks, and bootstrap the DB with seed tickets (RF-010)
	$(UV) sync --extra dev
	$(UV) run pre-commit install || true
	@if [ -f scripts/bootstrap_db.py ]; then \
		$(UV) run python scripts/bootstrap_db.py ; \
	else \
		echo "[make setup] scripts/bootstrap_db.py not found — skipping DB bootstrap" ; \
	fi

run:  ## Start the FastAPI server with reload (RF-010)
	$(UV) run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

run-db:  ## Start only the Postgres + pgvector sidecar
	docker compose up -d db

seed:  ## Load the 60-ticket seed fixture into the database
	$(UV) run python scripts/bootstrap_db.py

test:  ## Run pytest with coverage (writes coverage.json)
	$(UV) run pytest tests/ $(PYTEST_ARGS) $(COV_ARGS)

lint:  ## ruff check + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:  ## Apply ruff format in place
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

sast:  ## semgrep + bandit (non-fatal — exit codes captured inside reports)
	@echo "[sast] running semgrep..."
	-$(UV) run semgrep --config .semgrep/custom-rules.yml --config auto src/ --json -o $(SEMGREP_OUT) || true
	@echo "[sast] running bandit..."
	-$(UV) run bandit -r src/ -f json -o $(BANDIT_OUT) -c bandit.yaml || true

secrets:  ## gitleaks scan (no-git mode: scans the working tree)
	-gitleaks detect --no-git --source . --report-format json --report-path $(GITLEAKS_OUT) || true

score-l1:  ## Aggregate all reports into final-l1.json (RF-201..207)
	$(UV) run python scripts/score_l1.py --output $(L1_OUT)

ci-local:  ## Full local CI — lint + test + sast + secrets + score (RF-010)
	bash scripts/ci_local.sh

checkpoint:  ## One-shot checkpoint (RF-301..305)
	bash scripts/checkpoint.sh

clean:  ## Remove caches and report artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ .coverage coverage.json \
		$(SEMGREP_OUT) $(BANDIT_OUT) $(GITLEAKS_OUT) $(L1_OUT)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
