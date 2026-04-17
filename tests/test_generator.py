"""Tests for :mod:`src.services.generator`.

The PydanticAI agent is swapped for a stub so we can exercise the
:meth:`Generator.generate` path without any HTTP traffic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.models.ticket import Citation, QueryResponse
from src.services.generator import Generator
from src.services.retriever import RetrievedChunk


@dataclass
class _FakeRunResult:
    output: QueryResponse


class _FakeAgent:
    def __init__(self, canned: QueryResponse) -> None:
        self.canned = canned
        self.calls: list[dict[str, Any]] = []

    async def run(self, prompt: str, deps: Any) -> _FakeRunResult:  # noqa: ANN401
        self.calls.append({"prompt": prompt, "deps": deps})
        return _FakeRunResult(output=self.canned)


@pytest.fixture
def sample_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk("TKT-0001", 0, "login issue", 0.10, {}),
        RetrievedChunk("TKT-0002", 0, "billing charge", 0.15, {}),
    ]


async def test_generator_returns_query_response(
    sample_chunks: list[RetrievedChunk], llm_responses: dict[str, Any]
) -> None:
    gen = Generator.__new__(Generator)
    canned = QueryResponse(
        answer=llm_responses["structured_response"]["answer"],
        citations=[Citation(**c) for c in llm_responses["structured_response"]["citations"]],
    )
    gen._agent = _FakeAgent(canned)  # type: ignore[attr-defined]
    result = await gen.generate("why double charge?", sample_chunks)
    assert isinstance(result, QueryResponse)
    assert len(result.citations) == 2
    assert result.citations[0].ticket_id.startswith("TKT-")


async def test_generator_prompt_includes_excerpts(
    sample_chunks: list[RetrievedChunk], llm_responses: dict[str, Any]
) -> None:
    gen = Generator.__new__(Generator)
    canned = QueryResponse(
        answer="ok",
        citations=[Citation(**c) for c in llm_responses["structured_response"]["citations"]],
    )
    agent = _FakeAgent(canned)
    gen._agent = agent  # type: ignore[attr-defined]
    await gen.generate("billing question", sample_chunks)
    prompt = agent.calls[0]["prompt"]
    # Excerpts should be referenced by ticket_id in the prompt body.
    assert "TKT-0001" in prompt
    assert "TKT-0002" in prompt


async def test_generator_passes_chunks_via_deps(
    sample_chunks: list[RetrievedChunk], llm_responses: dict[str, Any]
) -> None:
    gen = Generator.__new__(Generator)
    canned = QueryResponse(
        answer="ok",
        citations=[Citation(**c) for c in llm_responses["structured_response"]["citations"]],
    )
    agent = _FakeAgent(canned)
    gen._agent = agent  # type: ignore[attr-defined]
    await gen.generate("q", sample_chunks)
    deps = agent.calls[0]["deps"]
    assert hasattr(deps, "chunks")
    assert [c.ticket_id for c in deps.chunks] == ["TKT-0001", "TKT-0002"]

