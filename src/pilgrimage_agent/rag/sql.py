"""PostgreSQL/pgvector persistence and exact hybrid retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pilgrimage_agent.persistence import KnowledgeChunkRecord, KnowledgeRecord
from pilgrimage_agent.rag.bm25 import PersistentBm25Index
from pilgrimage_agent.rag.embedding import EmbeddingProvider
from pilgrimage_agent.rag.retrieval import allowed_namespaces, detect_conflicts, rrf_fuse
from pilgrimage_agent.rag.schemas import (
    IngestedDocument,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeQuery,
    KnowledgeSearchResult,
    RetrievedEvidence,
)
from pilgrimage_agent.rag.text import lexical_tokens


def _document(record: KnowledgeRecord) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=record.id,
        namespace=record.namespace,
        owner_user_id=record.owner_user_id,
        trip_id=record.trip_id,
        title=record.title,
        source_url=record.source_url,
        source_type=record.source_type,
        authority_level=record.authority_level,
        author=record.author,
        language=record.language,
        published_at=record.published_at,
        accessed_at=record.accessed_at,
        valid_from=record.valid_from,
        valid_until=record.valid_until,
        subject_ids=tuple(record.subject_ids),
        location_tags=tuple(record.location_tags),
        point_ids=tuple(record.point_ids),
        content_sha256=record.content_sha256,
        status=record.status,
        extraction_warning=record.extraction_warning,
        metadata=record.document_metadata,
    )


def _chunk(record: KnowledgeChunkRecord) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=record.id,
        document_id=record.document_id,
        ordinal=record.ordinal,
        section_path=record.section_path,
        page_start=record.page_start,
        page_end=record.page_end,
        text=record.text,
        token_count=record.token_count,
        lexical_tokens=tuple(record.lexical_tokens),
        embedding=tuple(float(value) for value in record.embedding),
        metadata=record.chunk_metadata,
    )


class SqlRagRepository:
    """All personal reads are filtered by server-derived namespaces in SQL."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        embedder: EmbeddingProvider,
        *,
        bm25_root: Path = Path(".cache/rag-bm25"),
    ) -> None:
        self.sessions = sessions
        self.embedder = embedder
        self.bm25 = PersistentBm25Index(bm25_root)

    async def save(self, ingested: IngestedDocument) -> IngestedDocument:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.namespace == ingested.document.namespace,
                    KnowledgeRecord.content_sha256 == ingested.document.content_sha256,
                )
            )
            if existing is not None:
                records = (
                    await session.scalars(
                        select(KnowledgeChunkRecord)
                        .where(KnowledgeChunkRecord.document_id == existing.id)
                        .order_by(KnowledgeChunkRecord.ordinal)
                    )
                ).all()
                return IngestedDocument(
                    document=_document(existing),
                    chunks=tuple(_chunk(record) for record in records),
                    duplicate=True,
                )
            document = ingested.document
            session.add(
                KnowledgeRecord(
                    id=document.document_id,
                    owner_user_id=document.owner_user_id,
                    namespace=document.namespace,
                    trip_id=document.trip_id,
                    title=document.title,
                    source_url=str(document.source_url) if document.source_url else None,
                    source_type=document.source_type,
                    authority_level=document.authority_level,
                    author=document.author,
                    language=document.language,
                    published_at=document.published_at,
                    accessed_at=document.accessed_at,
                    valid_from=document.valid_from,
                    valid_until=document.valid_until,
                    subject_ids=list(document.subject_ids),
                    location_tags=list(document.location_tags),
                    point_ids=list(document.point_ids),
                    content_sha256=document.content_sha256,
                    status=document.status,
                    extraction_warning=document.extraction_warning,
                    document_metadata=document.metadata,
                )
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeChunkRecord(
                        id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        ordinal=chunk.ordinal,
                        section_path=chunk.section_path,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        text=chunk.text,
                        token_count=chunk.token_count,
                        lexical_tokens=list(chunk.lexical_tokens),
                        embedding=list(chunk.embedding),
                        chunk_metadata=chunk.metadata,
                    )
                    for chunk in ingested.chunks
                ]
            )
        return ingested

    async def list_documents(
        self, owner_user_id: str, trip_id: UUID | None
    ) -> Sequence[KnowledgeDocument]:
        namespaces = allowed_namespaces(owner_user_id, trip_id)
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(KnowledgeRecord)
                    .where(KnowledgeRecord.namespace.in_(namespaces))
                    .order_by(KnowledgeRecord.created_at.desc())
                )
            ).all()
        return tuple(_document(record) for record in records)

    async def get_document(
        self, owner_user_id: str, trip_id: UUID | None, document_id: UUID
    ) -> KnowledgeDocument | None:
        namespaces = allowed_namespaces(owner_user_id, trip_id)
        async with self.sessions() as session:
            record = await session.scalar(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.id == document_id,
                    KnowledgeRecord.namespace.in_(namespaces),
                )
            )
        return None if record is None else _document(record)

    async def delete_document(
        self, owner_user_id: str, trip_id: UUID | None, document_id: UUID
    ) -> bool:
        writable = {f"user:{owner_user_id}"}
        if trip_id is not None:
            writable.add(f"trip:{trip_id}")
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.id == document_id,
                    KnowledgeRecord.namespace.in_(writable),
                )
            )
            if record is None:
                return False
            await session.execute(delete(KnowledgeRecord).where(KnowledgeRecord.id == document_id))
        return True

    async def search(self, query: KnowledgeQuery) -> KnowledgeSearchResult:
        namespaces = allowed_namespaces(query.owner_user_id, query.trip_id)
        async with self.sessions() as session:
            conditions = [
                KnowledgeRecord.namespace.in_(namespaces),
                KnowledgeRecord.status == "active",
            ]
            if query.travel_date:
                conditions.extend(
                    [
                        or_(
                            KnowledgeRecord.valid_until.is_(None),
                            KnowledgeRecord.valid_until >= query.travel_date,
                        ),
                        or_(
                            KnowledgeRecord.valid_from.is_(None),
                            KnowledgeRecord.valid_from <= query.travel_date,
                        ),
                    ]
                )
            rows = (
                await session.execute(
                    select(KnowledgeChunkRecord, KnowledgeRecord)
                    .join(KnowledgeRecord, KnowledgeRecord.id == KnowledgeChunkRecord.document_id)
                    .where(*conditions)
                )
            ).all()
            pairs = [
                (_chunk(chunk_record), _document(document_record))
                for chunk_record, document_record in rows
                if self._metadata_matches(query, document_record)
            ]
            if not pairs:
                return KnowledgeSearchResult(status="insufficient_evidence", evidence=())
            expanded = " ".join((query.question, *query.aliases, *query.location_tags))
            query_tokens = set(lexical_tokens(expanded))
            query_vector = self.embedder.embed_query(expanded)
            eligible_ids = [chunk.chunk_id for chunk, _document_item in pairs]
            dense_records = (
                await session.scalars(
                    select(KnowledgeChunkRecord.id)
                    .where(KnowledgeChunkRecord.id.in_(eligible_ids))
                    .order_by(KnowledgeChunkRecord.embedding.cosine_distance(list(query_vector)))
                    .limit(30)
                )
            ).all()

        chunks = [chunk for chunk, _document_item in pairs]
        documents = {document.document_id: document for _chunk_item, document in pairs}
        chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
        dense_ids = list(dense_records)
        bm25_ids = [
            chunk_id
            for chunk_id in self.bm25.search(chunks, tuple(sorted(query_tokens)))
            if query_tokens.intersection(chunk_map[chunk_id].lexical_tokens)
        ]
        fused = rrf_fuse(dense_ids, bm25_ids)
        ranked = sorted(fused, key=lambda chunk_id: fused[chunk_id][0], reverse=True)
        evidence: list[RetrievedEvidence] = []
        per_document: dict[UUID, int] = defaultdict(int)
        for chunk_id in ranked:
            chunk = chunk_map[chunk_id]
            document = documents[chunk.document_id]
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
        conflicts = detect_conflicts(evidence, documents)
        return KnowledgeSearchResult(
            status="sufficient_evidence" if evidence else "insufficient_evidence",
            evidence=tuple(evidence),
            conflicts=conflicts,
        )

    @staticmethod
    def _metadata_matches(query: KnowledgeQuery, document: KnowledgeRecord) -> bool:
        if query.knowledge_types and document.source_type not in query.knowledge_types:
            return False
        for requested, stored in (
            (query.subject_ids, document.subject_ids),
            (query.location_tags, document.location_tags),
            (query.point_ids, document.point_ids),
        ):
            if requested and stored and not set(requested).intersection(stored):
                return False
        return True
