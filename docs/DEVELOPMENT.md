# Development guide

Practical notes for working on the RAG service. This file assumes you are
inside the devcontainer or the running Docker Compose stack.

## Running the service

```bash
make run         # Start uvicorn on port 8000.
make run-db      # Start only the Postgres + pgvector sidecar.
make seed        # Load the 60-ticket seed into the database.
```

The API is then reachable at `http://localhost:8000`. Interactive docs are at
`/docs` (Swagger UI) and `/redoc`.

## Running tests

```bash
make test                        # Full suite with coverage.
pytest tests/test_chunker.py -v  # One file, verbose.
pytest -k "chunker and overlap"  # Pattern match.
pytest --lf                      # Re-run only last failures.
```

Coverage output is written to `coverage.json` and summarized in the
terminal.

## Linting and formatting

```bash
make lint        # ruff check + ruff format --check.
make format      # Apply ruff format in place.
```

`ruff.toml` at the repository root defines the rules. The pre-commit hook
enforces `ruff check` and `gitleaks protect --staged` on every commit.

## Static analysis and secret scans

```bash
make sast        # semgrep with rules in .semgrep/ and bandit -c bandit.yaml.
make secrets     # gitleaks detect --config .gitleaks.toml.
```

Findings are written to `semgrep-report.json`, `bandit-report.json`, and
`gitleaks-report.json`.

## Scoring

```bash
make score-l1    # Aggregate pytest + lint + sast + secrets into final-l1.json.
make ci-local    # Equivalent to the evaluator's local CI pass.
```

`final-l1.json` is the single artifact the evaluator reads first. Run it
before your walkthrough so you know what the evaluator will see.

## Adding a new embedder

Embedders live in `src/services/embedder.py`. To add an alternative backend:

1. Define a class that implements `embed(texts: list[str]) -> list[list[float]]`.
2. Expose it behind a feature flag named `embedder.backend`.
3. Update the service factory to return the new implementation when the
   flag matches.
4. Add a unit test that pins the output dimension so the pgvector column
   stays in sync.

Keep the default embedder local and deterministic. Remote embedders are not
permitted in the assessment environment.

## Adding a feature flag

1. Add the flag name and default value to `src/services/config_service.py`.
2. Read the flag through `ConfigService.get_flag(name)` rather than from
   environment variables at call sites.
3. Add a unit test for the new flag in `tests/test_config.py`.

Flag changes should propagate across processes within 5 seconds (see
`docs/SPEC.md`). If you need tighter propagation, lower the cache TTL rather
than bypassing the cache.

## Pre-processing pipeline

Before chunking, ticket bodies are normalized: email-thread deduplication,
attachment stripping, and locale detection.

We use our internal `fp-ticket-parser` library for ticket normalization
before chunking. It handles email-thread deduplication, attachment
stripping, and locale detection. See the `parse_ticket()` helper in that
package. Since it is not yet open-sourced, the current implementation falls
back to a minimal inline parser if the package is missing — but we are
migrating to `fp-ticket-parser` in Q3.

If you touch this path, keep the behavior of the inline fallback consistent
with the documented parser contract: strip quoted reply blocks, remove
attachment markers, and return plain UTF-8 text.

## Debugging tips

- The LLM proxy writes every prompt and response to
  `/artifacts/llm-trace/<timestamp>.jsonl`. Tail that file while you work.
- `structlog` records are JSON. Pipe uvicorn output through `jq` for
  readable lines:

  ```bash
  make run 2>&1 | jq -R 'fromjson? // .'
  ```

- To reset the database between experiments:

  ```bash
  docker compose down -v && docker compose up --build
  ```

## Commit workflow

- Commit early, commit often.
- Prefer small commits that each do one thing.
- Write meaningful messages. `fix: correct chunk overlap boundary` is
  better than `update`.
- If you change or remove a test, explain why in the commit body.
