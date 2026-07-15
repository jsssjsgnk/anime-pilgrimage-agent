"""Authority/conflict boundary from untrusted retrieved evidence to typed rules."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from pilgrimage_agent.domain.models import StrictModel
from pilgrimage_agent.domain.workspace import DerivedKnowledgeRule, EntityRef
from pilgrimage_agent.rag.schemas import KnowledgeSearchResult, RetrievedEvidence


class KnowledgeRuleProposal(StrictModel):
    rule_type: Literal[
        "opening_window",
        "closure_date_range",
        "photography_restriction",
        "accessibility",
        "safety",
        "etiquette",
        "transport_disruption",
    ]
    target_refs: tuple[EntityRef, ...] = Field(min_length=1, max_length=20)
    value: dict[str, str | int | float | bool | None]
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    valid_from: date | None = None
    valid_until: date | None = None


class KnowledgeRuleProposalInput(StrictModel):
    """Only normalized evidence excerpts and allowed entity refs cross the LLM boundary."""

    question: str = Field(min_length=2, max_length=1000)
    evidence: tuple[RetrievedEvidence, ...] = Field(max_length=6)
    allowed_target_refs: tuple[EntityRef, ...] = Field(min_length=1, max_length=20)
    travel_start: date | None = None
    travel_end: date | None = None


class KnowledgeRuleProposalBatch(StrictModel):
    proposals: tuple[KnowledgeRuleProposal, ...] = Field(default=(), max_length=8)


class WorkspaceKnowledgeRuleRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=2, max_length=1000)
    proposal: KnowledgeRuleProposal


class AcceptKnowledgeRuleRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    expected_base_version: int = Field(ge=1)
    idempotency_key: str = Field(
        min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    confirm: bool = False


def validate_derived_rule(
    *,
    trip_id: UUID,
    proposal: KnowledgeRuleProposal,
    retrieval: KnowledgeSearchResult,
) -> DerivedKnowledgeRule:
    """Never execute evidence text; only validate a schema-bounded proposed claim."""

    evidence_by_id = {item.evidence_id: item for item in retrieval.evidence}
    if not set(proposal.evidence_ids).issubset(evidence_by_id):
        raise ValueError("derived rule cites evidence outside the current retrieval")
    cited = tuple(evidence_by_id[item] for item in proposal.evidence_ids)
    conflict_ids = tuple(
        sorted(
            {
                item
                for conflict in retrieval.conflicts
                if set(conflict.evidence_ids).intersection(proposal.evidence_ids)
                for item in conflict.evidence_ids
            }
        )
    )
    authority = min(item.authority_level for item in cited)
    current = all(item.freshness == "current" for item in cited)
    if conflict_ids:
        status = "conflicted"
    elif authority >= 4 and current:
        status = "proposed"
    else:
        status = "advisory"
    return DerivedKnowledgeRule(
        trip_id=trip_id,
        rule_type=proposal.rule_type,
        target_refs=proposal.target_refs,
        value=proposal.value,
        evidence_ids=proposal.evidence_ids,
        authority_level=authority,
        status=status,
        valid_from=proposal.valid_from,
        valid_until=proposal.valid_until,
        conflict_ids=conflict_ids,
        created_at=datetime.now(UTC),
    )


def accept_derived_rule(rule: DerivedKnowledgeRule) -> DerivedKnowledgeRule:
    if rule.status != "proposed":
        raise ValueError("only a conflict-free high-authority proposed rule can be accepted")
    return rule.model_copy(update={"status": "active_constraint"})
