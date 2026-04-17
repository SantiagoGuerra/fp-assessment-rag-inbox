"""Shared pytest fixtures.

These tests do not connect to a real Postgres instance or a real LLM. The
retriever is substituted with an in-memory stub and the generator's model
layer is replaced with a deterministic fake. HTTP calls that do leak out are
intercepted by ``respx``.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def tickets() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "tickets.json").read_text())


@pytest.fixture(scope="session")
def llm_responses() -> dict[str, Any]:
    return json.loads((FIXTURES / "llm_responses.json").read_text())


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """A fresh respx router per test."""
    with respx.mock(assert_all_called=False) as router:
        yield router


# ---------------------------------------------------------------------------
# Patched services
# ---------------------------------------------------------------------------


class FakeEmbedder:
    """Deterministic embedder for tests — no torch dependency."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self._cache: dict[str, list[float]] = {}

    def _key(self, text: str) -> str:
        import hashlib

        return hashlib.sha256(text.encode()).hexdigest()

    def _vector_for(self, text: str) -> list[float]:
        import hashlib
        import struct

        digest = hashlib.sha256(text.encode()).digest()
        # Expand digest to ``dim`` floats via repeated hashing.
        out: list[float] = []
        seed = digest
        while len(out) < self.dim:
            seed = hashlib.sha256(seed).digest()
            for i in range(0, len(seed), 4):
                if len(out) >= self.dim:
                    break
                (val,) = struct.unpack(">I", seed[i : i + 4])
                out.append((val / 0xFFFFFFFF) * 2 - 1)
        # L2-normalise to mimic sentence-transformers normalize_embeddings=True.
        norm = sum(x * x for x in out) ** 0.5 or 1.0
        return [x / norm for x in out]

    def embed(self, text: str) -> list[float]:
        key = self._key(text)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        vec = self._vector_for(text)
        self._cache[key] = vec
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


class StubRetrievedChunk:
    def __init__(
        self,
        ticket_id: str,
        chunk_index: int,
        content: str,
        score: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.ticket_id = ticket_id
        self.chunk_index = chunk_index
        self.content = content
        self.score = score
        self.metadata = metadata or {}


@pytest.fixture
def stub_chunks() -> list[StubRetrievedChunk]:
    return [
        StubRetrievedChunk("TKT-0001", 0, "login issue excerpt", 0.12),
        StubRetrievedChunk("TKT-0002", 0, "billing double-charge excerpt", 0.18),
    ]


class FakeGenerator:
    """Pretend to call an LLM. Returns whatever ``canned`` is set to."""

    def __init__(self, canned: dict[str, Any]) -> None:
        self.canned = canned

    async def generate(self, query: str, chunks: list[Any]):  # noqa: ANN401
        from src.models.ticket import Citation, QueryResponse

        citations = [Citation(**c) for c in self.canned.get("citations", [])]
        return QueryResponse(answer=self.canned.get("answer", ""), citations=citations)


@pytest_asyncio.fixture
async def app_client(
    monkeypatch: pytest.MonkeyPatch,
    fake_embedder: FakeEmbedder,
    llm_responses: dict[str, Any],
) -> AsyncIterator[AsyncClient]:
    """An ASGI-transport httpx client against a test-wired FastAPI app.

    The session dependency is overridden to a no-op async generator because
    routes that actually touch the DB substitute their own retriever/generator.
    """
    import src.services.embedder as embedder_mod
    import src.services.generator as generator_mod
    import src.services.retriever as retriever_mod

    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: fake_embedder)

    async def _fake_retrieve(session, query, top_k=5):  # noqa: ARG001
        return [
            StubRetrievedChunk("TKT-0001", 0, "login issue excerpt", 0.12),
            StubRetrievedChunk("TKT-0002", 0, "billing double-charge excerpt", 0.18),
        ][:top_k]

    class _R:
        embedder = fake_embedder

        async def retrieve(self, session, query, top_k=5):
            return await _fake_retrieve(session, query, top_k)

    monkeypatch.setattr(retriever_mod, "get_retriever", lambda: _R())

    fake_gen = FakeGenerator(llm_responses["structured_response"])
    monkeypatch.setattr(generator_mod, "get_generator", lambda: fake_gen)

    from src.db import session as session_mod
    from src.main import create_app

    async def _noop_session():
        yield None  # type: ignore[misc]

    app = create_app()
    app.dependency_overrides[session_mod.get_session] = _noop_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
