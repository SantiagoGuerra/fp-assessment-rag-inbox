"""Ticket ORM model + Pydantic v2 request/response schemas.

The embedding column uses pgvector's ``Vector`` type. The embedding dimension
for ``sentence-transformers/all-MiniLM-L6-v2`` is **384**.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", lazy="selectin"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_pk: Mapped[UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_ticket_pk_chunk_index", "ticket_pk", "chunk_index", unique=True),
    )


# ---------------------------------------------------------------------------
# Pydantic v2 schemas (request / response)
# ---------------------------------------------------------------------------


class TicketMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    created_at: str | None = None
    priority: str | None = None
    tags: list[str] = Field(default_factory=list)


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1)
    metadata: TicketMetadata = Field(default_factory=TicketMetadata)


class IngestResponse(BaseModel):
    ticket_id: str
    chunks: int


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2048)
    top_k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    ticket_id: str
    snippet: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
