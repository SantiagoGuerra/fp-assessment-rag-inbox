"""pgvector-based retriever.

Given a query string, we:
1. Embed the query with the local sentence-transformer.
2. Fetch the top-K nearest chunks from Postgres (pgvector).
3. Resolve each chunk back to its parent ticket metadata for citation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.embedder import DEFAULT_DIM, Embedder, get_embedder

log = structlog.get_logger(__name__)


@dataclass
class RetrievedChunk:
    ticket_id: str
    chunk_index: int
    content: str
    score: float
    metadata: dict[str, Any]


class Retriever:
    """Runs semantic search against the ``chunks`` table."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or get_embedder()

    def _validate_vector(self, vec: list[float]) -> None:
        if len(vec) != self.embedder.dim:
            raise ValueError("Vector dimension mismatch: expected 768")

    async def retrieve(
        self,
        session: AsyncSession,
        query: str,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        vec = self.embedder.embed(query)
        self._validate_vector(vec)

        sql = text(
            """
            SELECT c.id AS chunk_id,
                   c.ticket_pk AS ticket_pk,
                   c.chunk_index AS chunk_index,
                   c.content AS content,
                   c.embedding <-> CAST(:vec AS vector) AS score
            FROM chunks c
            ORDER BY c.embedding <-> CAST(:vec AS vector)
            LIMIT :k
            """
        )
        result = await session.execute(sql, {"vec": vec, "k": top_k})
        rows = result.mappings().all()

        out: list[RetrievedChunk] = []
        for row in rows:
            meta_sql = text(
                "SELECT ticket_id, metadata FROM tickets WHERE id = :tid"
            )
            meta_row = (
                await session.execute(meta_sql, {"tid": row["ticket_pk"]})
            ).mappings().first()
            if meta_row is None:
                continue
            out.append(
                RetrievedChunk(
                    ticket_id=meta_row["ticket_id"],
                    chunk_index=row["chunk_index"],
                    content=row["content"],
                    score=float(row["score"]),
                    metadata=dict(meta_row["metadata"] or {}),
                )
            )
        return out


_default: Retriever | None = None


def get_retriever() -> Retriever:
    global _default
    if _default is None:
        _default = Retriever()
    return _default


# Re-export for callers that want to assert the expected dim.
__all__ = ["DEFAULT_DIM", "RetrievedChunk", "Retriever", "get_retriever"]
