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

## What you need to deliver

Your submission must satisfy all six acceptance criteria:

- **AC-1**: `POST /query` responds with `{answer, citations}` where each
  citation has `ticket_id`, `snippet`, and `score`. Matched queries return at
  least two citations. No matches returns an empty citation list and the
  answer string `"No relevant tickets found"`.
- **AC-2**: Every `ticket_id` returned in a citation exists in the database.
- **AC-3**: `POST /query` has a p95 latency under 1.5 seconds on the
  60-ticket seed dataset.
- **AC-4**: `POST /ingest` splits a 2000-character ticket into at least three
  chunks with the correct configured overlap.
- **AC-5**: Adversarial inputs in the user query do not change the agent's
  system behavior.
- **AC-6**: `pytest tests/` passes at 100 percent. Coverage on files you
  touch is at least 70 percent.

## Constraints

- No external network services beyond the LLM proxy that already runs in the
  container.
- Do not add new Python packages outside the existing `uv.lock` unless the
  addition is strongly justified and the package is available offline.
- Time-box: 60 to 90 minutes of focused build time.
- Commit often. Small, well-named commits score better than one large dump.
- Keep the tests green as you go. If you change a test, explain why in the
  commit message.

## Tips

- Read `docs/SPEC.md` carefully and compare the documented contract to the
  behavior you observe. Any discrepancy is worth investigating.
- Run `make test` early to see the current baseline.
- Run `make score-l1` before the walkthrough to see what the evaluator will
  see.
