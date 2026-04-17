"""Async SQLAlchemy engine + session factory.

The engine is lazily constructed from ``DATABASE_URL`` so the module can be
imported in unit tests without touching a real database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag"


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return a singleton async engine driven by ``DATABASE_URL``."""
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return create_async_engine(url, pool_pre_ping=True, future=True)


AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=None,  # late-bound via _ensure_bound
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def _ensure_bound() -> None:
    if AsyncSessionLocal.kw.get("bind") is None:
        AsyncSessionLocal.configure(bind=get_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a transactional session."""
    _ensure_bound()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
