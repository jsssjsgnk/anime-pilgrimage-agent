"""Real multilingual E5 and deterministic fixture embedding boundaries."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from importlib import import_module
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from pilgrimage_agent.rag.text import lexical_tokens


class EmbeddingProvider(Protocol):
    dimension: int
    model_revision: str

    def embed_query(self, text: str) -> tuple[float, ...]: ...

    def embed_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...

    def token_count(self, text: str) -> int: ...


class FixtureE5Embedder:
    """Stable 384-d normalized test double with E5 prefix semantics."""

    dimension = 384
    model_revision = "fixture-e5-hash-v1"

    def _embed(self, prefixed_text: str) -> tuple[float, ...]:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in lexical_tokens(prefixed_text):
            digest = sha256(token.encode()).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimension
            vector[index] += 1.0 if digest[2] % 2 else -1.0
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            vector[0] = 1.0
            norm = 1.0
        return tuple(float(value) for value in vector / norm)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._embed(f"query: {text}")

    def embed_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed(f"passage: {text}") for text in texts)

    def token_count(self, text: str) -> int:
        return max(1, len(lexical_tokens(text)))


class SentenceTransformerE5Embedder:
    """Lazy real implementation of intfloat/multilingual-e5-small."""

    dimension = 384
    model_revision = "intfloat/multilingual-e5-small"

    def __init__(self) -> None:
        module = import_module("sentence_transformers")
        model_type = cast(Any, module).SentenceTransformer
        models = cast(Any, module).models
        transformer = models.Transformer(self.model_revision)
        pooling = models.Pooling(
            transformer.get_word_embedding_dimension(), pooling_mode_mean_tokens=True
        )
        self.model = model_type(modules=[transformer, pooling])

    def _encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        vectors = cast(
            NDArray[np.float32],
            self.model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True),
        )
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.shape[1] != self.dimension:
            raise RuntimeError("multilingual E5 returned an unexpected dimension")
        return tuple(tuple(float(value) for value in row) for row in vectors)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._encode((f"query: {text}",))[0]

    def embed_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return self._encode(tuple(f"passage: {text}" for text in texts))

    def token_count(self, text: str) -> int:
        encoded = self.model.tokenizer(text, add_special_tokens=True, truncation=False)
        return len(cast(dict[str, list[int]], encoded)["input_ids"])
