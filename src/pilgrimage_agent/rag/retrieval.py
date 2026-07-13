"""Namespace-filtered dense + bm25s retrieval with reciprocal rank fusion."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from hashlib import sha256
from typing import cast
from uuid import UUID

import bm25s  # type: ignore[import-untyped]
import numpy as np
from numpy.typing import NDArray

from pilgrimage_agent.rag.embedding import EmbeddingProvider, FixtureE5Embedder
from pilgrimage_agent.rag.ingestion import ingest_document
from pilgrimage_agent.rag.schemas import (
    EvidenceConflict,
    IngestedDocument,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentInput,
    KnowledgeQuery,
    KnowledgeSearchResult,
    RetrievedEvidence,
)
from pilgrimage_agent.rag.text import lexical_tokens


def allowed_namespaces(owner_user_id: str, trip_id: UUID | None) -> frozenset[str]:
    namespaces = {"curated", f"user:{owner_user_id}"}
    if trip_id is not None:
        namespaces.add(f"trip:{trip_id}")
    return frozenset(namespaces)


def rrf_fuse(
    dense_ids: Iterable[UUID], bm25_ids: Iterable[UUID], *, k: int = 60
) -> dict[UUID, tuple[float, int | None, int | None]]:
    if k != 60:
        raise ValueError("the project RRF constant is fixed at 60")
    scores: dict[UUID, float] = defaultdict(float)
    dense_ranks: dict[UUID, int] = {}
    bm25_ranks: dict[UUID, int] = {}
    for rank, chunk_id in enumerate(dense_ids, start=1):
        scores[chunk_id] += 1 / (k + rank)
        dense_ranks[chunk_id] = rank
    for rank, chunk_id in enumerate(bm25_ids, start=1):
        scores[chunk_id] += 1 / (k + rank)
        bm25_ranks[chunk_id] = rank
    return {
        chunk_id: (score, dense_ranks.get(chunk_id), bm25_ranks.get(chunk_id))
        for chunk_id, score in scores.items()
    }


class HybridKnowledgeIndex:
    """Small-corpus reference implementation used by fixtures and evaluation."""

    def __init__(self, embedder: EmbeddingProvider | None = None) -> None:
        self.embedder = embedder or FixtureE5Embedder()
        self.documents: dict[UUID, KnowledgeDocument] = {}
        self.chunks: dict[UUID, KnowledgeChunk] = {}
        self._dedupe: dict[tuple[str, str], UUID] = {}

    def ingest(
        self,
        request: KnowledgeDocumentInput,
        *,
        namespace: str | None = None,
        document_id: UUID | None = None,
    ) -> IngestedDocument:
        ingested = ingest_document(
            request, self.embedder, namespace=namespace, document_id=document_id
        )
        key = (ingested.document.namespace, ingested.document.content_sha256)
        existing_id = self._dedupe.get(key)
        if existing_id is not None:
            existing = self.documents[existing_id]
            chunks = tuple(
                chunk for chunk in self.chunks.values() if chunk.document_id == existing_id
            )
            return IngestedDocument(document=existing, chunks=chunks, duplicate=True)
        self.documents[ingested.document.document_id] = ingested.document
        self._dedupe[key] = ingested.document.document_id
        self.chunks.update({chunk.chunk_id: chunk for chunk in ingested.chunks})
        return ingested

    def delete(self, owner_user_id: str, document_id: UUID) -> bool:
        document = self.documents.get(document_id)
        if document is None or document.namespace not in allowed_namespaces(owner_user_id, None):
            return False
        del self.documents[document_id]
        self._dedupe.pop((document.namespace, document.content_sha256), None)
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id != document_id
        }
        return True

    def _eligible(self, query: KnowledgeQuery) -> tuple[KnowledgeChunk, ...]:
        namespaces = allowed_namespaces(query.owner_user_id, query.trip_id)
        eligible: list[KnowledgeChunk] = []
        for chunk in self.chunks.values():
            document = self.documents.get(chunk.document_id)
            if document is None or document.status != "active":
                continue
            if document.namespace not in namespaces:
                continue
            if (
                query.travel_date
                and document.valid_until
                and document.valid_until < query.travel_date
            ):
                continue
            if (
                query.travel_date
                and document.valid_from
                and document.valid_from > query.travel_date
            ):
                continue
            if query.knowledge_types and document.source_type not in query.knowledge_types:
                continue
            if query.subject_ids and document.subject_ids:
                if not set(query.subject_ids).intersection(document.subject_ids):
                    continue
            if query.location_tags and document.location_tags:
                if not set(query.location_tags).intersection(document.location_tags):
                    continue
            if query.point_ids and document.point_ids:
                if not set(query.point_ids).intersection(document.point_ids):
                    continue
            eligible.append(chunk)
        return tuple(eligible)

    def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        chunks = self._eligible(query)
        if not chunks:
            return KnowledgeSearchResult(status="insufficient_evidence", evidence=())
        expanded_query = " ".join((query.question, *query.aliases, *query.location_tags))
        query_token_set = set(lexical_tokens(expanded_query))
        query_vector = np.asarray(self.embedder.embed_query(expanded_query), dtype=np.float32)
        dense_threshold = 1.1 if isinstance(self.embedder, FixtureE5Embedder) else 0.55
        dense_scored: list[tuple[float, UUID]] = []
        for chunk in chunks:
            score = float(np.dot(query_vector, np.asarray(chunk.embedding, dtype=np.float32)))
            lexical_overlap = len(query_token_set.intersection(chunk.lexical_tokens))
            if score > dense_threshold or lexical_overlap >= 2:
                dense_scored.append((score, chunk.chunk_id))
        dense_ids = [chunk_id for _score, chunk_id in sorted(dense_scored, reverse=True)[:30]]

        corpus = [" ".join(chunk.lexical_tokens) for chunk in chunks]
        retriever = bm25s.BM25()
        retriever.index(bm25s.tokenize(corpus, stopwords=[]), show_progress=False)
        query_text = " ".join(lexical_tokens(expanded_query))
        results, scores = retriever.retrieve(
            bm25s.tokenize((query_text,), stopwords=[]),
            k=min(30, len(chunks)),
            show_progress=False,
        )
        result_ids = cast(NDArray[np.int64], results)[0]
        result_scores = cast(NDArray[np.float32], scores)[0]
        bm25_ids = [
            chunks[int(index)].chunk_id
            for index, score in zip(result_ids, result_scores, strict=True)
            if float(score) > 0
            and len(query_token_set.intersection(chunks[int(index)].lexical_tokens)) >= 2
        ]
        fused = rrf_fuse(dense_ids, bm25_ids)
        if not fused:
            return KnowledgeSearchResult(status="insufficient_evidence", evidence=())
        ranked = sorted(
            fused,
            key=lambda chunk_id: (
                fused[chunk_id][0],
                self.documents[self.chunks[chunk_id].document_id].authority_level * 1e-6,
            ),
            reverse=True,
        )
        per_document: dict[UUID, int] = defaultdict(int)
        evidence: list[RetrievedEvidence] = []
        for chunk_id in ranked:
            chunk = self.chunks[chunk_id]
            document = self.documents[chunk.document_id]
            if per_document[document.document_id] >= 2:
                continue
            score, dense_rank, bm25_rank = fused[chunk_id]
            evidence.append(
                RetrievedEvidence(
                    evidence_id=f"K-{chunk.chunk_id.hex[:12]}",
                    chunk_id=chunk.chunk_id,
                    document_id=document.document_id,
                    excerpt=chunk.text[:800],
                    title=document.title,
                    source_url=document.source_url,
                    source_type=document.source_type,
                    authority_level=document.authority_level,
                    published_at=document.published_at,
                    accessed_at=document.accessed_at,
                    section_path=chunk.section_path,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    dense_rank=dense_rank,
                    bm25_rank=bm25_rank,
                    rrf_score=score,
                    freshness="current" if document.valid_until else "unknown",
                )
            )
            per_document[document.document_id] += 1
            if len(evidence) == query.top_k:
                break
        conflicts = detect_conflicts(evidence, self.documents)
        return KnowledgeSearchResult(
            status="sufficient_evidence" if evidence else "insufficient_evidence",
            evidence=tuple(evidence),
            conflicts=conflicts,
        )

    def corpus_sha256(self) -> str:
        values = sorted(
            f"{document.namespace}:{document.content_sha256}"
            for document in self.documents.values()
        )
        return sha256("|".join(values).encode()).hexdigest()


def detect_conflicts(
    evidence: Iterable[RetrievedEvidence], documents: dict[UUID, KnowledgeDocument]
) -> tuple[EvidenceConflict, ...]:
    claims: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for item in evidence:
        metadata = documents[item.document_id].metadata
        key = metadata.get("claim_key")
        value = metadata.get("claim_value")
        if isinstance(key, str) and isinstance(value, str):
            claims[key][value].append(item.evidence_id)
    return tuple(
        EvidenceConflict(
            claim_key=key,
            evidence_ids=tuple(evidence_id for ids in values.values() for evidence_id in ids),
            explanation="Sources disagree; the application does not choose silently.",
        )
        for key, values in claims.items()
        if len(values) > 1
    )


def untrusted_evidence_blocks(result: KnowledgeSearchResult) -> str:
    return "\n".join(
        f'<untrusted_evidence id="{item.evidence_id}">{item.excerpt}</untrusted_evidence>'
        for item in result.evidence
    )


def validate_citations(citation_ids: Iterable[str], result: KnowledgeSearchResult) -> bool:
    allowed = {evidence.evidence_id for evidence in result.evidence}
    return set(citation_ids).issubset(allowed)
