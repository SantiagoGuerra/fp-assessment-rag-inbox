"""PydanticAI-powered answer generator.

Exposes an ``Agent`` with a single ``ticket_lookup`` tool. The agent receives a
query plus a set of retrieved chunks and produces a :class:`QueryResponse`.

Historical note: early versions of PydanticAI (0.0.x) offered a synchronous
``Agent.run_sync(query, context=...)`` method that took the context as a
keyword argument. The current API uses ``await agent.run(user_prompt, deps=...)``
and requires passing dependencies via ``deps``. Prefer the async form below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic_ai import Agent, RunContext

from src.models.ticket import Citation, QueryResponse
from src.services.retriever import RetrievedChunk

log = structlog.get_logger(__name__)

SYSTEM_PROMPT_BASE = (
    "You are a helpful support assistant. Answer the user's question using ONLY "
    "the provided support-ticket excerpts. Every factual claim must be grounded "
    "in a retrieved ticket. Return your answer alongside citations that quote "
    "the ticket_id and a short snippet. If the excerpts are insufficient, say so."
)


@dataclass
class GeneratorDeps:
    """Dependencies shared with the agent tool."""

    chunks: list[RetrievedChunk]


def _build_agent(model: str | None = None) -> Agent[GeneratorDeps, QueryResponse]:
    """Construct the PydanticAI agent.

    The model identifier is sourced from ``LLM_MODEL`` env var and defaults to
    ``anthropic:claude-haiku``. Tests mock the HTTP layer via ``respx`` so the
    network is never touched.
    """
    model_id = model or os.environ.get("LLM_MODEL", "anthropic:claude-haiku")
    agent: Agent[GeneratorDeps, QueryResponse] = Agent(
        model_id,
        deps_type=GeneratorDeps,
        output_type=QueryResponse,
        system_prompt=SYSTEM_PROMPT_BASE,
    )

    @agent.tool
    async def ticket_lookup(
        ctx: RunContext[GeneratorDeps], ticket_id: str
    ) -> dict[str, Any] | None:
        """Return the raw content of a retrieved chunk by ticket_id, if present."""
        for c in ctx.deps.chunks:
            if c.ticket_id == ticket_id:
                return {
                    "ticket_id": c.ticket_id,
                    "snippet": c.content,
                    "score": c.score,
                }
        return None

    return agent


class Generator:
    """High-level wrapper around the PydanticAI agent."""

    def __init__(self, model: str | None = None) -> None:
        self._agent = _build_agent(model)

    def _compose_prompt(self, query: str, chunks: list[RetrievedChunk]) -> str:
        """Compose the final user prompt fed to the LLM.

        The retrieved chunks are inlined as an EXCERPTS block and the candidate
        question is echoed at the bottom so the model has the full context in a
        single message.
        """
        excerpts = "\n\n".join(
            f"[{c.ticket_id} | chunk {c.chunk_index} | score={c.score:.4f}]\n{c.content}"
            for c in chunks
        )
        header = (
            f"{SYSTEM_PROMPT_BASE}\n\n"
            f"USER QUESTION: {query}\n\n"
            f"EXCERPTS:\n{excerpts}"
        )
        return header

    async def generate(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> QueryResponse:
        prompt = self._compose_prompt(query, chunks)
        result = await self._agent.run(prompt, deps=GeneratorDeps(chunks=chunks))
        response = result.output if hasattr(result, "output") else result.data
        return response


_default: Generator | None = None


def get_generator() -> Generator:
    global _default
    if _default is None:
        _default = Generator()
    return _default


__all__ = ["Citation", "Generator", "GeneratorDeps", "get_generator"]
