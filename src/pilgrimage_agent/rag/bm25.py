"""Application-layer persistent bm25s indexes with deterministic rebuilds."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

import bm25s  # type: ignore[import-untyped]
import numpy as np
from numpy.typing import NDArray

from pilgrimage_agent.rag.schemas import KnowledgeChunk


class PersistentBm25Index:
    """Persist one immutable index per exact eligible chunk corpus."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _key(chunks: list[KnowledgeChunk]) -> str:
        material = "|".join(
            f"{chunk.chunk_id}:{' '.join(chunk.lexical_tokens)}"
            for chunk in sorted(chunks, key=lambda item: item.chunk_id.hex)
        )
        return sha256(material.encode()).hexdigest()

    def search(
        self, chunks: list[KnowledgeChunk], query_tokens: tuple[str, ...], *, limit: int = 30
    ) -> list[UUID]:
        if not chunks or not query_tokens:
            return []
        index_dir = self.root / self._key(chunks)
        ids_path = index_dir / "chunk_ids.json"
        if not ids_path.exists():
            index_dir.mkdir(parents=True, exist_ok=True)
            corpus = [" ".join(chunk.lexical_tokens) for chunk in chunks]
            retriever = bm25s.BM25()
            retriever.index(bm25s.tokenize(corpus, stopwords=[]), show_progress=False)
            retriever.save(index_dir, show_progress=False)
            ids_path.write_text(
                json.dumps([str(chunk.chunk_id) for chunk in chunks]), encoding="utf-8"
            )
        else:
            retriever = bm25s.BM25.load(index_dir, load_corpus=False)
        persisted_ids = tuple(
            UUID(value) for value in cast(list[str], json.loads(ids_path.read_text("utf-8")))
        )
        results, scores = retriever.retrieve(
            bm25s.tokenize((" ".join(query_tokens),), stopwords=[]),
            k=min(limit, len(chunks)),
            show_progress=False,
        )
        result_ids = cast(NDArray[np.int64], results)[0]
        result_scores = cast(NDArray[np.float32], scores)[0]
        return [
            persisted_ids[int(index)]
            for index, score in zip(result_ids, result_scores, strict=True)
            if float(score) > 0
        ]
