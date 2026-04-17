"""POST /query — semantic search + generation over ticket inbox."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.ticket import QueryRequest, QueryResponse
from src.services.generator import get_generator
from src.services.retriever import get_retriever

log = structlog.get_logger(__name__)
router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def run_query(
    payload: QueryRequest,
    session: AsyncSession = Depends(get_session),
) -> QueryResponse:
    retriever = get_retriever()
    generator = get_generator()

    chunks = await retriever.retrieve(session, payload.query, top_k=payload.top_k)
    response = await generator.generate(payload.query, chunks)
    log.info(
        "query.ok",
        query_len=len(payload.query),
        chunks=len(chunks),
        citations=len(response.citations),
    )
    return response
