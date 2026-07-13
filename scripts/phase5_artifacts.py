"""Generate Phase 5 schemas and a transparent fixed-corpus RAG report."""

from __future__ import annotations

import json
from pathlib import Path

from pilgrimage_agent.exports import GeoJsonExport, PlanExport
from pilgrimage_agent.rag.evaluation import evaluate
from pilgrimage_agent.rag.fixtures import load_fixture_index

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


def main() -> int:
    index, queries = load_fixture_index(ROOT / "fixtures" / "rag")
    report = evaluate(index, queries)
    thresholds_pass = (
        report.recall_at_6 >= 0.80
        and report.mrr_at_10 >= 0.70
        and report.citation_precision >= 0.90
        and report.namespace_leaks == 0
        and report.malicious_tool_calls == 0
        and report.deleted_result_residues == 0
        and report.unsupported_answer_rate <= 0.10
    )
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "rag-evaluation.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    for filename, schema in (
        ("plan-export-schema.json", PlanExport.model_json_schema()),
        ("geojson-export-schema.json", GeoJsonExport.model_json_schema()),
    ):
        (ARTIFACTS / filename).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        "RAG metrics: "
        f"Recall@6={report.recall_at_6:.3f}, MRR@10={report.mrr_at_10:.3f}, "
        f"Citation Precision={report.citation_precision:.3f}, "
        f"failed_queries={len(report.failed_query_ids)}"
    )
    return 0 if thresholds_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
