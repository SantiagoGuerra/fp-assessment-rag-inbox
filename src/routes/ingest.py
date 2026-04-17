"""POST /ingest — persist a ticket plus its chunk embeddings."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.ticket import Chunk as ChunkORM
from src.models.ticket import IngestRequest, IngestResponse, Ticket
from src.services.chunker import chunk_text
from src.services.embedder import get_embedder

log = structlog.get_logger(__name__)
router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_ticket(
    payload: IngestRequest,
    session: AsyncSession = Depends(get_session),
) -> IngestResponse:
    existing = await session.scalar(
        select(Ticket).where(Ticket.ticket_id == payload.ticket_id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"ticket_id {payload.ticket_id!r} already ingested",
        )

    ticket = Ticket(
        ticket_id=payload.ticket_id,
        title=payload.title,
        body=payload.body,
        meta=payload.metadata.model_dump(),
    )
    session.add(ticket)
    await session.flush()  # need ticket.id

    pieces = chunk_text(f"{payload.title}\n\n{payload.body}")
    embedder = get_embedder()
    vectors = embedder.embed_batch([p.text for p in pieces]) if pieces else []

    for piece, vec in zip(pieces, vectors, strict=True):
        session.add(
            ChunkORM(
                ticket_pk=ticket.id,
                chunk_index=piece.index,
                content=piece.text,
                embedding=vec,
            )
        )
    await session.commit()

    log.info("ingest.ok", ticket_id=payload.ticket_id, chunks=len(pieces))
    return IngestResponse(ticket_id=payload.ticket_id, chunks=len(pieces))
