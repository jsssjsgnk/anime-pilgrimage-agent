"""Strict ingestion, retrieval, evidence, and evaluation boundaries."""

from datetime import date
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, HttpUrl, model_validator

from pilgrimage_agent.domain.models import StrictModel

SourceType = Literal[
    "official_notice",
    "official_guide",
    "transport_operator",
    "curated_community",
    "user_note",
    "synthetic_test",
]


class KnowledgeDocumentInput(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    scope: Literal["user", "trip"]
    trip_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    filename: str = Field(min_length=1, max_length=255)
    media_type: Literal["text/markdown", "text/plain", "application/pdf"]
    content: str = Field(min_length=1, max_length=14_000_000)
    content_is_base64: bool = False
    source_url: HttpUrl | None = None
    source_type: SourceType = "user_note"
    authority_level: int = Field(default=1, ge=0, le=5)
    author: str | None = Field(default=None, max_length=200)
    language: str = Field(default="und", pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)?$|^und$")
    published_at: date | None = None
    accessed_at: date
    valid_from: date | None = None
    valid_until: date | None = None
    subject_ids: tuple[str, ...] = ()
    location_tags: tuple[str, ...] = ()
    point_ids: tuple[str, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scope_and_format_are_consistent(self) -> "KnowledgeDocumentInput":
        if self.scope == "trip" and self.trip_id is None:
            raise ValueError("trip scope requires trip_id")
        if self.scope == "user" and self.trip_id is not None:
            raise ValueError("user scope cannot carry trip_id")
        if self.media_type == "application/pdf" and not self.content_is_base64:
            raise ValueError("PDF content must be base64 encoded")
        if self.media_type != "application/pdf" and self.content_is_base64:
            raise ValueError("text content must not be base64 encoded")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not precede valid_from")
        return self


class KnowledgeDocument(StrictModel):
    document_id: UUID = Field(default_factory=uuid4)
    namespace: str
    owner_user_id: str
    trip_id: UUID | None = None
    title: str
    source_url: HttpUrl | None = None
    source_type: SourceType
    authority_level: int = Field(ge=0, le=5)
    author: str | None = None
    language: str
    published_at: date | None = None
    accessed_at: date
    valid_from: date | None = None
    valid_until: date | None = None
    subject_ids: tuple[str, ...] = ()
    location_tags: tuple[str, ...] = ()
    point_ids: tuple[str, ...] = ()
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["active", "needs_ocr", "deleted"]
    extraction_warning: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class KnowledgeChunk(StrictModel):
    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    ordinal: int = Field(ge=0)
    section_path: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1, max_length=20_000)
    token_count: int = Field(ge=1, le=1000)
    lexical_tokens: tuple[str, ...]
    embedding: tuple[float, ...] = Field(min_length=384, max_length=384)
    metadata: dict[str, object] = Field(default_factory=dict)


class IngestedDocument(StrictModel):
    document: KnowledgeDocument
    chunks: tuple[KnowledgeChunk, ...]
    duplicate: bool = False


class KnowledgeDeleteResponse(StrictModel):
    deleted: bool


class KnowledgeQuery(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    trip_id: UUID | None = None
    question: str = Field(min_length=2, max_length=1000)
    subject_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    location_tags: tuple[str, ...] = ()
    point_ids: tuple[str, ...] = ()
    knowledge_types: tuple[SourceType, ...] = ()
    travel_date: date | None = None
    top_k: int = Field(default=6, ge=1, le=6)


class RetrievedEvidence(StrictModel):
    evidence_id: str = Field(pattern=r"^K-[A-Fa-f0-9]{12}$")
    chunk_id: UUID
    document_id: UUID
    excerpt: str = Field(min_length=1, max_length=800)
    title: str
    source_url: HttpUrl | None = None
    source_type: SourceType
    authority_level: int = Field(ge=0, le=5)
    published_at: date | None = None
    accessed_at: date
    section_path: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    dense_rank: int | None = Field(default=None, ge=1)
    bm25_rank: int | None = Field(default=None, ge=1)
    rrf_score: float = Field(ge=0)
    freshness: Literal["current", "unknown"]


class EvidenceConflict(StrictModel):
    claim_key: str
    evidence_ids: tuple[str, ...] = Field(min_length=2)
    explanation: str


class KnowledgeSearchResult(StrictModel):
    status: Literal["sufficient_evidence", "insufficient_evidence"]
    evidence: tuple[RetrievedEvidence, ...]
    conflicts: tuple[EvidenceConflict, ...] = ()
    tool_calls_triggered: Literal[0] = 0


class GoldenQuery(StrictModel):
    query_id: str
    question: str
    owner_user_id: str = "golden-user"
    trip_id: UUID | None = None
    aliases: tuple[str, ...] = ()
    location_tags: tuple[str, ...] = ()
    travel_date: date | None = None
    expected_document_ids: frozenset[UUID]
    expected_empty: bool = False


class RagEvaluationReport(StrictModel):
    model_revision: str
    corpus_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_count: int = Field(ge=24)
    recall_at_6: float = Field(ge=0, le=1)
    mrr_at_10: float = Field(ge=0, le=1)
    citation_precision: float = Field(ge=0, le=1)
    namespace_leaks: int = Field(ge=0)
    malicious_tool_calls: int = Field(ge=0)
    deleted_result_residues: int = Field(ge=0)
    unsupported_answer_rate: float = Field(ge=0, le=1)
    failed_query_ids: tuple[str, ...] = ()


class RagManifestDocument(StrictModel):
    id: UUID
    file: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    namespace: str
    title: str
    source_url: HttpUrl | None = None
    source_type: SourceType
    authority_level: int = Field(ge=0, le=5)
    language: str
    location_tags: tuple[str, ...] = ()
    subject_ids: tuple[str, ...] = ()
    valid_until: date | None = None
    usage: str


class RagManifest(StrictModel):
    schema_version: Literal["1"]
    accessed_at: date
    summary_policy: str
    documents: tuple[RagManifestDocument, ...]
