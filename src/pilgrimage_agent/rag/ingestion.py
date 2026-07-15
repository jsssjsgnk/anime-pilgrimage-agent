"""Deterministic document ingestion and semantic chunk construction."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from pilgrimage_agent.rag.embedding import EmbeddingProvider
from pilgrimage_agent.rag.schemas import (
    IngestedDocument,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentInput,
)
from pilgrimage_agent.rag.text import extract_text_content, lexical_tokens


def authorized_namespace(request: KnowledgeDocumentInput) -> str:
    if request.scope == "user":
        return f"user:{request.owner_user_id}"
    assert request.trip_id is not None
    return f"trip:{request.trip_id}"


def _paragraph_chunks(text: str, embedder: EmbeddingProvider) -> tuple[str, ...]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n") if paragraph.strip()]
    if not paragraphs:
        return ()
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph_tokens = embedder.token_count(paragraph)
        if current and current_tokens + paragraph_tokens > 600:
            chunks.append("\n".join(current))
            overlap: list[str] = []
            overlap_tokens = 0
            for previous in reversed(current):
                overlap.insert(0, previous)
                overlap_tokens += embedder.token_count(previous)
                if overlap_tokens >= 80:
                    break
            current = overlap
            current_tokens = overlap_tokens
        current.append(paragraph)
        current_tokens += paragraph_tokens
        if current_tokens >= 450:
            chunks.append("\n".join(current))
            current = []
            current_tokens = 0
    if current:
        tail = "\n".join(current)
        if chunks and embedder.token_count(tail) < 80:
            chunks[-1] = f"{chunks[-1]}\n{tail}"
        else:
            chunks.append(tail)
    return tuple(chunks)


def ingest_document(
    request: KnowledgeDocumentInput,
    embedder: EmbeddingProvider,
    *,
    namespace: str | None = None,
    document_id: UUID | None = None,
) -> IngestedDocument:
    extracted = extract_text_content(
        request.content,
        media_type=request.media_type,
        content_is_base64=request.content_is_base64,
    )
    content_hash = sha256(extracted.text.encode()).hexdigest()
    resolved_namespace = namespace or authorized_namespace(request)
    document = KnowledgeDocument(
        document_id=document_id
        or UUID(
            bytes=sha256(f"{resolved_namespace}:{content_hash}".encode()).digest()[:16]
        ),
        namespace=resolved_namespace,
        owner_user_id=request.owner_user_id,
        trip_id=request.trip_id,
        title=request.title,
        source_url=request.source_url,
        source_type=request.source_type,
        authority_level=request.authority_level,
        author=request.author,
        language=request.language,
        published_at=request.published_at,
        accessed_at=request.accessed_at,
        valid_from=request.valid_from,
        valid_until=request.valid_until,
        subject_ids=request.subject_ids,
        location_tags=request.location_tags,
        point_ids=request.point_ids,
        content_sha256=content_hash,
        status=extracted.status,
        extraction_warning=extracted.warning,
        metadata=request.metadata,
    )
    if extracted.status == "needs_ocr":
        return IngestedDocument(document=document, chunks=())
    texts = _paragraph_chunks(extracted.text, embedder)
    embeddings = embedder.embed_passages(texts)
    chunks = tuple(
        KnowledgeChunk(
            chunk_id=UUID(bytes=sha256(f"{document.document_id}:{ordinal}".encode()).digest()[:16]),
            document_id=document.document_id,
            ordinal=ordinal,
            section_path=None,
            page_start=1 if extracted.page_count else None,
            page_end=extracted.page_count,
            text=text,
            token_count=embedder.token_count(text),
            lexical_tokens=lexical_tokens(text),
            embedding=embedding,
        )
        for ordinal, (text, embedding) in enumerate(zip(texts, embeddings, strict=True))
    )
    return IngestedDocument(document=document, chunks=chunks)
