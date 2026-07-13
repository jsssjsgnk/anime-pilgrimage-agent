"""Transparent golden-set evaluation with per-query failure disclosure."""

from pilgrimage_agent.rag.retrieval import HybridKnowledgeIndex, allowed_namespaces
from pilgrimage_agent.rag.schemas import GoldenQuery, KnowledgeQuery, RagEvaluationReport


def evaluate(index: HybridKnowledgeIndex, queries: tuple[GoldenQuery, ...]) -> RagEvaluationReport:
    if len(queries) < 24:
        raise ValueError("RAG golden set must contain at least 24 queries")
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    supported_citations = 0
    citation_count = 0
    namespace_leaks = 0
    unsupported = 0
    negative_count = 0
    failed: list[str] = []
    malicious_tool_calls = 0
    for golden in queries:
        result = index.search(
            KnowledgeQuery(
                owner_user_id=golden.owner_user_id,
                trip_id=golden.trip_id,
                question=golden.question,
                aliases=golden.aliases,
                location_tags=golden.location_tags,
                travel_date=golden.travel_date,
            )
        )
        retrieved = [item.document_id for item in result.evidence]
        malicious_tool_calls += result.tool_calls_triggered
        allowed = allowed_namespaces(golden.owner_user_id, golden.trip_id)
        namespace_leaks += sum(
            1 for document_id in retrieved if index.documents[document_id].namespace not in allowed
        )
        if golden.expected_empty:
            negative_count += 1
            if retrieved:
                unsupported += 1
                failed.append(golden.query_id)
            continue
        expected = golden.expected_document_ids
        hits = expected.intersection(retrieved[:6])
        recalls.append(len(hits) / len(expected))
        first_rank = next(
            (
                rank
                for rank, document_id in enumerate(retrieved[:10], start=1)
                if document_id in expected
            ),
            None,
        )
        reciprocal_ranks.append(0.0 if first_rank is None else 1 / first_rank)
        citation_count += 1
        if first_rank is not None:
            supported_citations += 1
        if hits != expected:
            failed.append(golden.query_id)

    private_id = next(
        document_id
        for document_id, document in index.documents.items()
        if document.namespace == "user:golden-user"
    )
    index.delete("golden-user", private_id)
    deleted_search = index.search(
        KnowledgeQuery(
            owner_user_id="golden-user",
            question="What private low-walking preference did I explicitly save?",
        )
    )
    deleted_residues = sum(
        1 for evidence in deleted_search.evidence if evidence.document_id == private_id
    )
    return RagEvaluationReport(
        model_revision=index.embedder.model_revision,
        corpus_sha256=index.corpus_sha256(),
        query_count=len(queries),
        recall_at_6=sum(recalls) / len(recalls),
        mrr_at_10=sum(reciprocal_ranks) / len(reciprocal_ranks),
        citation_precision=supported_citations / citation_count,
        namespace_leaks=namespace_leaks,
        malicious_tool_calls=malicious_tool_calls,
        deleted_result_residues=deleted_residues,
        unsupported_answer_rate=unsupported / max(negative_count, 1),
        failed_query_ids=tuple(failed),
    )
