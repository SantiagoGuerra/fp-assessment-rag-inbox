"""Embedding service backed by sentence-transformers.

The default model is ``sentence-transformers/all-MiniLM-L6-v2`` which produces
384-dimensional vectors. We lazily load the model on first use so tests that
do not exercise embeddings don't pay the import cost.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer

log = structlog.get_logger(__name__)
_silent = logging.getLogger("sentence_transformers")
_silent.setLevel(logging.WARNING)

DEFAULT_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
DEFAULT_DIM = 384


class Embedder:
    """Thin wrapper around a sentence-transformers model with a memoisation cache."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, dim: int = DEFAULT_DIM) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model: SentenceTransformer | None = None
        # Bug #7: the cache is a plain dict with no eviction policy. Long-running
        # processes accumulate every text ever embedded and eventually OOM.
        self._cache: dict[str, list[float]] = {}

    # -- lazy model loader ---------------------------------------------------

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # local import

            log.info("embedder.load", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    # -- public API ----------------------------------------------------------

    def _key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed(self, text: str) -> list[float]:
        """Return the embedding for ``text``. Results are memoised by SHA-256."""
        key = self._key(text)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        model = self._load()
        vec = model.encode(text, normalize_embeddings=True).tolist()
        self._cache[key] = vec
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, caching each individually."""
        model = self._load()
        out: list[list[float]] = []
        pending: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            key = self._key(t)
            hit = self._cache.get(key)
            if hit is not None:
                out.append(hit)
            else:
                out.append([])  # placeholder
                pending.append((i, t))

        if pending:
            vectors = model.encode(
                [t for _, t in pending], normalize_embeddings=True
            ).tolist()
            for (i, t), vec in zip(pending, vectors, strict=True):
                out[i] = vec
                self._cache[self._key(t)] = vec
        return out


_default: Embedder | None = None


def get_embedder() -> Embedder:
    """Return a process-wide default :class:`Embedder`."""
    global _default
    if _default is None:
        _default = Embedder()
    return _default
