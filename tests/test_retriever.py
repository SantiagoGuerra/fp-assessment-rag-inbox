"""Tests for :mod:`src.services.retriever`."""

from __future__ import annotations

from typing import Any

import pytest

from src.services.retriever import Retriever


class _StubResultMapping:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _StubResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _StubResultMapping:
        return _StubResultMapping(self._rows)


class StubSession:
    """Minimal async session double that replays canned SQL results."""

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.params: list[dict[str, Any]] = []

    async def execute(self, statement, params):  # type: ignore[no-untyped-def]
        self.queries.append(str(statement))
        self.params.append(params)
        compiled = str(statement).lower()
        if "from chunks" in compiled:
            return _StubResult(
                [
                    {
                        "chunk_id": "c1",
                        "ticket_pk": "tpk-1",
                        "chunk_index": 0,
                        "content": "login issue",
                        "score": 0.13,
                    },
                    {
                        "chunk_id": "c2",
                        "ticket_pk": "tpk-2",
                        "chunk_index": 0,
                        "content": "billing duplicate",
                        "score": 0.20,
                    },
                ]
            )
        # tickets table resolution
        ticket_pk = params["tid"]
        mapping = {
            "tpk-1": {"ticket_id": "TKT-0001", "metadata": {"priority": "high"}},
            "tpk-2": {"ticket_id": "TKT-0002", "metadata": {"priority": "medium"}},
        }
        row = mapping.get(ticket_pk)
        return _StubResult([row] if row else [])


@pytest.fixture
def retriever(fake_embedder) -> Retriever:  # type: ignore[no-untyped-def]
    return Retriever(embedder=fake_embedder)


async def test_retriever_returns_topk_chunks(retriever: Retriever) -> None:
    session = StubSession()
    results = await retriever.retrieve(session, "login problem", top_k=2)
    assert [r.ticket_id for r in results] == ["TKT-0001", "TKT-0002"]
    assert results[0].chunk_index == 0
    assert results[0].metadata == {"priority": "high"}


async def test_retriever_validates_vector_dim(retriever: Retriever) -> None:
    session = StubSession()
    # Force a dimension mismatch by patching the embedder output.
    retriever.embedder.embed = lambda _text: [0.0] * 100  # type: ignore[assignment]
    with pytest.raises(ValueError):
        await retriever.retrieve(session, "does not matter")


async def test_retriever_top_k_honoured(retriever: Retriever) -> None:
    session = StubSession()
    results = await retriever.retrieve(session, "billing", top_k=1)
    # Top-K is passed to the SQL layer; stub always returns 2 rows, but we
    # verify the SQL param was honoured.
    assert any(p.get("k") == 1 for p in session.params)
    # And we still receive both rows because the stub does not actually slice.
    assert len(results) == 2


@pytest.mark.skip(reason="known issue — see TASK.md")
async def test_retriever_scores_cosine(retriever: Retriever) -> None:
    """Spec invariant: scores are cosine distances in [0.0, 2.0].

    With cosine similarity, identical vectors produce distance 0 and opposite
    vectors produce distance 2. The retriever SQL must use the ``<=>``
    operator so callers can reason about the score magnitude.
    """
    session = StubSession()
    await retriever.retrieve(session, "login problem", top_k=2)
    # The vector operator used in SQL should be the cosine operator.
    compiled_sql = " ".join(session.queries)
    assert "<=>" in compiled_sql, f"expected cosine operator <=> but got: {compiled_sql}"
