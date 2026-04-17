# Task

## User story

As a support engineer, I want to query our ticket inbox in natural language
and get a grounded answer with citations, so I can resolve incidents faster
without reading every thread by hand.

## What is already done

- A FastAPI skeleton with `POST /ingest`, `POST /query`, and `GET /health`.
- Async SQLAlchemy wired to Postgres with the `pgvector` extension.
- A PydanticAI agent that orchestrates retrieval and generation.
- A local `sentence-transformers/all-MiniLM-L6-v2` embedder.
- A seed fixture of 60 synthetic support tickets in
  `tests/fixtures/tickets.json`.
- 17 pre-existing tests in `tests/`. Not all of them pass as-is.

## Acceptance criteria

See `docs/SPEC.md` for the full contract. All six must hold:

- **AC-1**: `POST /query` returns `{answer, citations}` with `ticket_id`,
  `snippet`, and `score` per citation. Matched queries return ≥2 citations.
- **AC-2**: Every returned `ticket_id` exists in the database.
- **AC-3**: `POST /query` p95 < 1.5s on the 60-ticket seed.
- **AC-4**: `POST /ingest` splits a 2000-char ticket into ≥3 chunks with the
  configured overlap.
- **AC-5**: Adversarial inputs do not alter the agent's system behavior.
- **AC-6**: `pytest tests/` passes 100%. Coverage on files you touch ≥70%.

## Constraints

- No external network beyond the LLM proxy already in the container.
- Do not add new Python packages unless strongly justified and offline.
- Time-box: 60–90 min. Commit often; small named commits score better.
- If you change a test, explain why in the commit message.

## Tips

- Read `docs/SPEC.md` and compare it to the behavior you observe.
- Run `make test` early to see the baseline.
- Run `make score-l1` before the walkthrough — it is what the evaluator sees.
