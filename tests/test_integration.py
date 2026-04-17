"""End-to-end tests that exercise the FastAPI app with stubbed services."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient


async def test_health_endpoint(app_client: AsyncClient) -> None:
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_query_endpoint_shape(app_client: AsyncClient) -> None:
    resp = await app_client.post(
        "/query",
        json={"query": "duplicate stripe charge", "top_k": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "answer" in body and "citations" in body
    for c in body["citations"]:
        assert "ticket_id" in c
        assert "snippet" in c
        assert "score" in c


async def test_query_endpoint_rejects_invalid_payload(app_client: AsyncClient) -> None:
    resp = await app_client.post("/query", json={"query": ""})
    assert resp.status_code == 422


async def test_happy_path(app_client: AsyncClient) -> None:
    """Happy-path smoke: /query returns a well-formed response."""
    resp = await app_client.post(
        "/query",
        json={"query": "duplicate stripe charge", "top_k": 2},
    )
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    # NOTE: baseline asserts exactly one citation is returned. See TASK.md and
    # docs/SPEC.md for the full acceptance criteria.
    assert len(body["citations"]) == 1
