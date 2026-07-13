"""Phase 5 ingestion, hybrid retrieval, isolation, and injection tests."""

from datetime import date
from pathlib import Path
from uuid import UUID

from pilgrimage_agent.rag.evaluation import evaluate
from pilgrimage_agent.rag.fixtures import load_fixture_index
from pilgrimage_agent.rag.retrieval import (
    HybridKnowledgeIndex,
    untrusted_evidence_blocks,
    validate_citations,
)
from pilgrimage_agent.rag.schemas import KnowledgeDocumentInput, KnowledgeQuery
from pilgrimage_agent.rag.text import lexical_tokens, normalize_text

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "rag"


def test_normalization_and_cjk_bigrams_are_deterministic() -> None:
    assert normalize_text("\uff21\uff22\uff23\t  京都\n\n駅") == "ABC 京都\n駅"
    tokens = lexical_tokens("Tokyo 東京駅")
    assert "tokyo" in tokens
    assert "東京" in tokens
    assert "京駅" in tokens


def test_golden_hybrid_metrics_clear_all_thresholds() -> None:
    index, queries = load_fixture_index(FIXTURES)
    report = evaluate(index, queries)
    assert report.query_count == 24
    assert report.recall_at_6 >= 0.80
    assert report.mrr_at_10 >= 0.70
    assert report.citation_precision >= 0.90
    assert report.namespace_leaks == 0
    assert report.malicious_tool_calls == 0
    assert report.deleted_result_residues == 0
    assert report.unsupported_answer_rate <= 0.10


def test_private_and_trip_namespaces_are_server_derived() -> None:
    index, _queries = load_fixture_index(FIXTURES)
    hidden = index.search(
        KnowledgeQuery(owner_user_id="another-user", question="private low-walking preference")
    )
    assert UUID("66666666-6666-4666-8666-666666666666") not in {
        item.document_id for item in hidden.evidence
    }
    trip_id = UUID("77777777-aaaa-4aaa-8aaa-777777777777")
    visible = index.search(
        KnowledgeQuery(
            owner_user_id="golden-user",
            trip_id=trip_id,
            question="large suitcase for this trip",
        )
    )
    assert visible.evidence[0].document_id == UUID("77777777-7777-4777-8777-777777777777")


def test_malicious_document_remains_quoted_data_and_citations_are_bounded() -> None:
    index, _queries = load_fixture_index(FIXTURES)
    result = index.search(
        KnowledgeQuery(
            owner_user_id="golden-user",
            question="Which malicious note asks to reveal credentials and book?",
        )
    )
    blocks = untrusted_evidence_blocks(result)
    assert "<untrusted_evidence" in blocks
    assert "book a ticket" in blocks
    assert result.tool_calls_triggered == 0
    assert validate_citations((result.evidence[0].evidence_id,), result)
    assert not validate_citations(("K-deadbeef0000",), result)


def test_duplicate_ingestion_and_delete_remove_all_results() -> None:
    index = HybridKnowledgeIndex()
    request = KnowledgeDocumentInput(
        owner_user_id="user-a",
        scope="user",
        title="Private station note",
        filename="note.txt",
        media_type="text/plain",
        content="A unique violet elevator is beside the north gate.",
        accessed_at=date(2026, 7, 14),
        language="en",
    )
    first = index.ingest(request)
    second = index.ingest(request)
    assert second.duplicate is True
    assert second.document.document_id == first.document.document_id
    result = index.search(
        KnowledgeQuery(owner_user_id="user-a", question="unique violet elevator north gate")
    )
    assert result.evidence
    assert index.delete("user-a", first.document.document_id)
    after_delete = index.search(
        KnowledgeQuery(owner_user_id="user-a", question="unique violet elevator north gate")
    )
    assert after_delete.status == "insufficient_evidence"
