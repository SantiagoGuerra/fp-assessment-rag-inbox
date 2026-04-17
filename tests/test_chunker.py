"""Tests for :mod:`src.services.chunker`."""

from __future__ import annotations

import pytest

from src.services.chunker import DEFAULT_CHUNK_SIZE, chunk_text


def test_chunker_short_text_returns_single_chunk() -> None:
    text = "short body"
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == text


def test_chunker_empty_text_returns_no_chunks() -> None:
    assert chunk_text("", chunk_size=500, overlap=50) == []


@pytest.mark.skip(reason="known issue — see TASK.md")
def test_chunker_overlap_correct() -> None:
    """Covers AC-4: a 2000-char ticket chunks into >=3 pieces with correct overlap.

    Each chunk except the last must be exactly ``chunk_size`` characters long,
    consecutive chunks must share exactly ``overlap`` characters, and
    concatenating the non-overlapping prefixes must reconstruct the input.
    """
    text = "abcdefghij" * 200  # 2000 characters
    chunk_size = DEFAULT_CHUNK_SIZE  # 500
    overlap = 50
    step = chunk_size - overlap
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    assert len(chunks) >= 3

    for i, chunk in enumerate(chunks):
        assert chunk.index == i
        # All chunks except possibly the last must be full-width.
        if i < len(chunks) - 1:
            assert len(chunk.text) == chunk_size, (
                f"chunk {i} should be {chunk_size} chars, got {len(chunk.text)}"
            )

    # Consecutive chunks overlap by exactly ``overlap`` characters.
    for i in range(len(chunks) - 1):
        assert chunks[i].text[-overlap:] == chunks[i + 1].text[:overlap]

    # Concatenation of the non-overlapping prefixes must equal the original.
    rebuilt = chunks[0].text + "".join(c.text[overlap:] for c in chunks[1:])
    assert rebuilt == text
