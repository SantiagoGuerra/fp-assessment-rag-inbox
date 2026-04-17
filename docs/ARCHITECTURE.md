# Architecture

## Overview

The service is a thin FastAPI layer around a local RAG pipeline. Data flows
through two primary paths: ingest and query.

## Diagram

```
                     ┌──────────────────────────┐
                     │   FastAPI (src/main.py)  │
                     └──────────┬───────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
        POST /ingest      POST /query        GET /health
              │                 │                 │
              ▼                 ▼                 ▼
       ┌───────────┐     ┌────────────┐     ┌──────────┐
       │  Chunker  │     │ Sanitizer  │     │  Status  │
       └─────┬─────┘     └──────┬─────┘     └──────────┘
             │                  │
             ▼                  ▼
       ┌───────────┐     ┌────────────┐
       │  Embedder │     │  Retriever │◄────┐
       └─────┬─────┘     └──────┬─────┘     │
             │                  │           │
             ▼                  ▼           │
       ┌───────────────────────────┐        │
       │  Postgres + pgvector      │        │
       │  (tickets, chunks)        │        │
       └───────────────────────────┘        │
                                 │          │
                                 ▼          │
                          ┌────────────┐    │
                          │ Generator  │────┘
                          │ (PydanticAI│
                          │  Agent)    │
                          └─────┬──────┘
                                │
                                ▼
                          ┌────────────┐
                          │ LLM proxy  │
                          │ (litellm)  │
                          └─────┬──────┘
                                │
                                ▼
                          ┌────────────┐
                          │ Anthropic  │
                          └────────────┘
```

## Ingest flow

1. Request hits `src/routes/ingest.py`.
2. The chunker (`src/services/chunker.py`) splits the ticket body.
3. The embedder (`src/services/embedder.py`) produces a 384-dim vector per
   chunk, caching by content hash.
4. Chunks and vectors are persisted atomically via the async SQLAlchemy
   session in `src/db/session.py`.
5. The route returns `{ticket_id, chunks}`.

## Query flow

1. Request hits `src/routes/query.py`.
2. The user query is sanitized.
3. The retriever (`src/services/retriever.py`) runs a cosine similarity
   search over `pgvector` and joins ticket metadata in a single SQL query.
4. The generator (`src/services/generator.py`) composes a PydanticAI agent
   call with the retrieved chunks as context.
5. The agent returns an answer plus citations. The generator validates each
   `ticket_id` against the database.
6. The route returns `{answer, citations}`.

## Module map

```
src/
├── main.py                 # FastAPI app factory and router wiring.
├── models/
│   └── ticket.py           # SQLAlchemy ORM + Pydantic schemas.
├── routes/
│   ├── ingest.py           # POST /ingest
│   ├── query.py            # POST /query
│   └── health.py           # GET /health
├── services/
│   ├── chunker.py          # Body-to-chunks splitting.
│   ├── embedder.py         # Local sentence-transformers + cache.
│   ├── retriever.py        # pgvector similarity search.
│   ├── generator.py        # PydanticAI agent orchestration.
│   └── config_service.py   # Feature flag loader and cache.
└── db/
    └── session.py          # Async engine, session maker, migrations hook.
```

## Deployment

The assessment runs entirely inside a Docker Compose stack:

| Service        | Image                           | Purpose                                   |
|----------------|---------------------------------|-------------------------------------------|
| `app`          | Project Dockerfile (Python 3.12)| FastAPI application.                      |
| `db`           | `pgvector/pgvector:pg16`        | Postgres with the `pgvector` extension.   |
| `llm-proxy`    | Shared base image               | Local proxy to the LLM provider.          |
| `checkpoint`   | Shared base image               | Writes a checkpoint every 20 minutes.     |

All services share a single Docker network. Only the LLM proxy has outbound
network access; the `app` container reaches the LLM provider through the
proxy.

## Data model

- `tickets(id UUID PK, ticket_id TEXT UNIQUE, title TEXT, body TEXT, metadata JSONB, created_at, updated_at)`
- `chunks(id UUID PK, ticket_fk UUID FK, ordinal INT, text TEXT, embedding VECTOR(384), created_at)`

Indexes:

- `CREATE INDEX chunks_embedding_idx ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);`
- `CREATE UNIQUE INDEX tickets_ticket_id_idx ON tickets(ticket_id);`

## Configuration

Runtime configuration is sourced from environment variables and feature
flags. Environment variables are read at startup. Feature flags are read on
every request through a cache (see `config_service.py`).
