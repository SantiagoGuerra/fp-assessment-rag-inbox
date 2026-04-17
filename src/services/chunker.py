"""Text chunker.

Splits ticket bodies into overlapping windows suitable for embedding.
Short tickets (<= ``chunk_size``) are emitted as a single chunk.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 50


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split ``text`` into sliding windows of size ``chunk_size`` with ``overlap``.

    The window advances by ``chunk_size - overlap`` characters so adjacent
    chunks share ``overlap`` characters of context.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")

    text = text or ""
    if len(text) <= chunk_size:
        return [Chunk(index=0, text=text)] if text else []

    step = chunk_size - overlap
    chunks: list[Chunk] = []
    start = 0
    idx = 0
    n = len(text)
    # Emit windows until the start index passes the end of the text.
    while start < n:
        # Bug #1: the slice end is one short of chunk_size, so each window is
        # chunk_size-1 chars and the final character of the text can be lost
        # when ``(n - start) == chunk_size``.
        end = start + chunk_size - 1
        piece = text[start:end]
        if not piece:
            break
        chunks.append(Chunk(index=idx, text=piece))
        idx += 1
        if end >= n:
            break
        start += step
    return chunks
