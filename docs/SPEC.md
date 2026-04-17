# Specification

This document is the contract for the RAG service. Candidate work must keep
the system aligned with these invariants.

## Endpoints

### `POST /ingest`

Accepts a single ticket and persists its embedded chunks.

**Request body**:

```json
{
  "ticket_id": "TKT-0001",
  "title": "Login fails on Safari 17",
  "body": "Users report a redirect loop after OAuth callback ...",
  "metadata": {
    "priority": "high",
    "tags": ["auth", "safari"]
  }
}
```

**Response**:

```json
{
  "ticket_id": "TKT-0001",
  "chunks": 3
}
```

**Invariants**:

- Tickets with `body` longer than 500 characters are split into multiple
  chunks before embedding.
- Overlap between consecutive chunks is 50 characters.
- Maximum chunk size is 400 characters.
- A 2000-character body produces at least three chunks.
- Re-ingesting the same `ticket_id` replaces prior chunks for that ticket.

### `POST /query`

Runs retrieval over stored chunks and returns a grounded answer.

**Request body**:

```json
{
  "query": "Why does login fail on Safari?",
  "top_k": 5
}
```

**Response (matched)**:

```json
{
  "answer": "Safari 17 drops the session cookie on the OAuth callback because ...",
  "citations": [
    {
      "ticket_id": "TKT-0001",
      "snippet": "redirect loop after OAuth callback",
      "score": 0.81
    },
    {
      "ticket_id": "TKT-0042",
      "snippet": "SameSite=Lax on the session cookie",
      "score": 0.76
    }
  ]
}
```

**Response (no matches)**:

```json
{
  "answer": "No relevant tickets found",
  "citations": []
}
```

**Invariants**:

- At least two citations are returned whenever at least one chunk matches.
- Every `ticket_id` in `citations` corresponds to a ticket present in the
  database. Hallucinated identifiers are a defect.
- `score` is the cosine similarity between the query embedding and the
  matched chunk embedding, normalized to `[0.0, 1.0]`.
- p95 latency on the 60-ticket seed is below 1.5 seconds.
- The agent does not follow instructions embedded in the user query. See
  Security below.

### `GET /health`

Returns `{"status": "ok"}` with HTTP 200 when the API process is running and
the database is reachable.

## Chunking

- Triggered when ticket body length exceeds 500 characters.
- Fixed-window splitting with 50-character overlap between adjacent chunks.
- Maximum chunk length is 400 characters.
- Whitespace is preserved. No further normalization is applied at the
  chunker layer.

## Embedding

- Default embedder: `sentence-transformers/all-MiniLM-L6-v2`.
- Embedding dimension: 384.
- Embeddings are computed locally. No embedding API call leaves the
  container.
- Embeddings are cached in-process by content hash to avoid duplicate work
  on re-ingest.

## Retrieval

- Storage: `pgvector` column on the `chunks` table.
- Similarity metric: **cosine**. The SQL operator is `<=>`.
- `top_k` default is 5, maximum is 20.
- A single query returns both chunk data and the parent ticket's metadata.
  Retrieval must not issue a per-chunk lookup for metadata.

## Generation

- The generator is a PydanticAI `Agent` with an explicit system prompt and a
  separate user-content slot.
- The user query is passed as user content, not interpolated into the system
  prompt.
- The agent exposes a `ticket_lookup` tool that fetches ticket metadata by
  `ticket_id` from the database.
- Every citation returned by the agent is validated against the database
  before the response is serialized.

## Feature flags

- Flags are loaded by `src/services/config_service.py`.
- A process-local cache holds flag values. Cache TTL is configurable in
  seconds.
- A flag change is observable across all processes within 5 seconds.

## Security

- User queries are sanitized before being passed to the agent.
- The agent must not follow instructions embedded in the user query. Typical
  payloads to resist include `"ignore previous instructions"`,
  `"reveal your system prompt"`, and requests to call tools on behalf of
  other tickets.
- The API does not echo the raw system prompt under any condition.
- Citations never include ticket identifiers that are not in the database.

## Observability

- All endpoints emit structured JSON logs via `structlog`.
- Each request carries a `request_id`. Downstream services include it in
  their log records.
- Query latency is recorded per request in milliseconds.
