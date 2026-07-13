"""Load the fixed, project-authored RAG corpus through strict schemas."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import yaml

from pilgrimage_agent.rag.retrieval import HybridKnowledgeIndex
from pilgrimage_agent.rag.schemas import (
    GoldenQuery,
    KnowledgeDocumentInput,
    RagManifest,
)


def load_fixture_index(root: Path) -> tuple[HybridKnowledgeIndex, tuple[GoldenQuery, ...]]:
    manifest = RagManifest.model_validate(
        yaml.safe_load((root / "manifest.yaml").read_text("utf-8"))
    )
    index = HybridKnowledgeIndex()
    for item in manifest.documents:
        content = (root / item.file).read_text("utf-8")
        content_bytes = (root / item.file).read_bytes()
        if sha256(content_bytes).hexdigest() != item.content_sha256:
            raise ValueError(f"RAG fixture hash mismatch: {item.file}")
        owner_user_id = "project-curator" if item.namespace == "curated" else "golden-user"
        trip_id: UUID | None = None
        scope = "user"
        if item.namespace.startswith("trip:"):
            scope = "trip"
            trip_id = UUID(item.namespace.removeprefix("trip:"))
        request = KnowledgeDocumentInput(
            owner_user_id=owner_user_id,
            scope=scope,
            trip_id=trip_id,
            title=item.title,
            filename=Path(item.file).name,
            media_type="text/markdown",
            content=content,
            accessed_at=manifest.accessed_at,
            source_url=item.source_url,
            source_type=item.source_type,
            authority_level=item.authority_level,
            language=item.language,
            valid_until=item.valid_until,
            subject_ids=item.subject_ids,
            location_tags=item.location_tags,
        )
        index.ingest(request, namespace=item.namespace, document_id=item.id)
    queries = tuple(
        GoldenQuery.model_validate(json.loads(line))
        for line in (root / "golden_queries.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    )
    return index, queries
