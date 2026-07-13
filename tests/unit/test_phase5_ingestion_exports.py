"""Phase 5 PDF, conflict, persistent lexical index, and export contracts."""

from __future__ import annotations

import base64
import io
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter

from pilgrimage_agent.domain.planning import RouteBRequest
from pilgrimage_agent.exports import (
    GeoJsonExport,
    PlanExport,
    StandaloneHtmlExport,
)
from pilgrimage_agent.planning.demo import fixture_route_a, plan_demo_route_b
from pilgrimage_agent.rag.bm25 import PersistentBm25Index
from pilgrimage_agent.rag.embedding import FixtureE5Embedder
from pilgrimage_agent.rag.ingestion import authorized_namespace, ingest_document
from pilgrimage_agent.rag.retrieval import HybridKnowledgeIndex
from pilgrimage_agent.rag.schemas import KnowledgeDocumentInput, KnowledgeQuery
from pilgrimage_agent.rag.text import extract_text_content


def _request(content: str, *, metadata: dict[str, object] | None = None) -> KnowledgeDocumentInput:
    return KnowledgeDocumentInput(
        owner_user_id="fixture-user",
        scope="user",
        title="Fixture knowledge",
        filename="fixture.txt",
        media_type="text/plain",
        content=content,
        accessed_at=date(2026, 7, 14),
        metadata=metadata or {},
    )


def test_blank_pdf_is_needs_ocr_and_has_no_chunks() -> None:
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(stream)
    request = KnowledgeDocumentInput(
        owner_user_id="fixture-user",
        scope="user",
        title="Scanned note",
        filename="scan.pdf",
        media_type="application/pdf",
        content=base64.b64encode(stream.getvalue()).decode(),
        content_is_base64=True,
        accessed_at=date(2026, 7, 14),
    )
    result = ingest_document(request, FixtureE5Embedder())
    assert result.document.status == "needs_ocr"
    assert result.document.extraction_warning
    assert result.chunks == ()


def test_ingestion_scope_chunking_and_invalid_pdf_paths() -> None:
    user_request = _request("short station note")
    assert authorized_namespace(user_request) == "user:fixture-user"
    trip_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    trip_request = user_request.model_copy(update={"scope": "trip", "trip_id": trip_id})
    assert authorized_namespace(trip_request) == f"trip:{trip_id}"
    paragraphs = "\n".join(
        f"paragraph {index} violet elevator north gate detail" for index in range(180)
    )
    chunked = ingest_document(_request(paragraphs), FixtureE5Embedder())
    assert len(chunked.chunks) >= 2
    assert all(chunk.token_count <= 600 for chunk in chunked.chunks)
    with pytest.raises(ValueError, match="valid base64"):
        extract_text_content(
            "not-base64!", media_type="application/pdf", content_is_base64=True
        )


def test_conflicting_hard_claims_are_returned_together() -> None:
    index = HybridKnowledgeIndex()
    for value, wording in (
        ("allowed", "violet gate photography policy permits photos"),
        ("prohibited", "violet gate photography policy prohibits photos"),
    ):
        index.ingest(
            _request(
                wording,
                metadata={"claim_key": "violet_gate_photography", "claim_value": value},
            )
        )
    result = index.search(
        KnowledgeQuery(
            owner_user_id="fixture-user", question="violet gate photography policy"
        )
    )
    assert len(result.evidence) == 2
    assert len(result.conflicts) == 1
    assert set(result.conflicts[0].evidence_ids) == {
        evidence.evidence_id for evidence in result.evidence
    }


def test_bm25_index_persists_reloads_and_rebuilds_after_deletion(tmp_path: Path) -> None:
    embedder = FixtureE5Embedder()
    first = ingest_document(_request("violet elevator north gate"), embedder).chunks[0]
    second = ingest_document(_request("orange stairs south gate"), embedder).chunks[0]
    chunks = [first, second]
    persistent = PersistentBm25Index(tmp_path)
    assert persistent.search(chunks, ("violet", "elevator"))[0] == first.chunk_id
    assert any(tmp_path.iterdir())
    reloaded = PersistentBm25Index(tmp_path)
    assert reloaded.search(chunks, ("orange", "stairs"))[0] == second.chunk_id
    assert first.chunk_id not in reloaded.search([second], ("violet", "elevator"))


@pytest.mark.asyncio
async def test_json_geojson_and_standalone_html_boundaries() -> None:
    route_a = await fixture_route_a("328609")
    plan = await plan_demo_route_b(
        route_a,
        RouteBRequest(
            inbound_option_id="train-kyoto-tokyo-early",
            outbound_option_id="train-tokyo-kyoto-evening",
            base_id="shimokitazawa",
            max_walking_meters_per_day=5_000,
        ),
        today=lambda: date(2026, 7, 14),
    )
    exported = PlanExport(
        schema_version="1",
        plan_version=1,
        subject_id="328609",
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
        route_a_point_ids=tuple(point.id for point in route_a.points),
        route_b=plan,
        evidence_ids=(),
        reconfirm_before_departure=("transport",),
    )
    assert PlanExport.model_validate_json(exported.model_dump_json()) == exported
    geojson = GeoJsonExport.model_validate(
        {
            "type": "FeatureCollection",
            "schema_version": "1",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.66, 35.66]},
                    "properties": {
                        "id": str(route_a.points[0].id),
                        "name": route_a.points[0].name,
                        "source_url": str(route_a.points[0].provenance.source_url),
                    },
                }
            ],
        }
    )
    assert geojson.features[0].geometry.type == "Point"
    StandaloneHtmlExport(content="<!doctype html><html><body>safe</body></html>")
    with pytest.raises(ValidationError):
        StandaloneHtmlExport(content="<!doctype html><script>alert(1)</script>")
    with pytest.raises(ValidationError):
        StandaloneHtmlExport(content="<html><body>missing doctype</body></html>")
    with pytest.raises(ValidationError):
        GeoJsonExport.model_validate(
            {
                "type": "FeatureCollection",
                "schema_version": "1",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [500, 35.66]},
                        "properties": {
                            "id": str(route_a.points[0].id),
                            "name": "Invalid point",
                            "source_url": "https://example.test/source",
                        },
                    }
                ],
            }
        )
