"""Node-specific context snapshots that exclude conversation and secrets."""

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import ClassVar
from uuid import UUID

from pilgrimage_agent.agent.schemas import ContextSnapshot
from pilgrimage_agent.domain.workspace import (
    AgentRole,
    ContextFact,
    EntityRef,
    ImpactAnalysis,
    ItineraryVersion,
    PlanPatch,
    RoleContext,
)


class ContextBuilder:
    """Build only the identifiers and facts required by one graph node."""

    def build(
        self,
        *,
        node: str,
        owner_user_id: str,
        thread_id: str,
        trip_id: str,
        facts: tuple[str, ...],
        route_a_point_ids: tuple[str, ...] = (),
        relevant_knowledge_ids: tuple[str, ...] = (),
    ) -> ContextSnapshot:
        bounded_facts = tuple(fact[:240] for fact in facts[:12])
        bounded_points = route_a_point_ids[:30]
        bounded_knowledge = relevant_knowledge_ids[:12]
        digest_input = "|".join((owner_user_id, thread_id, trip_id, node, *bounded_facts))
        snapshot_id = sha256(digest_input.encode()).hexdigest()[:24]
        token_estimate = sum(len(item) for item in (*bounded_facts, *bounded_points)) // 3 + 24
        return ContextSnapshot(
            snapshot_id=snapshot_id,
            node=node,
            state_ids=(owner_user_id, thread_id, trip_id),
            fact_summary=bounded_facts,
            route_a_point_ids=bounded_points,
            relevant_knowledge_ids=bounded_knowledge,
            estimated_tokens=min(token_estimate, 4000),
        )

    @staticmethod
    def safe_projection(snapshot: ContextSnapshot) -> Mapping[str, object]:
        """Return the exact versioned shape allowed across the LLM boundary."""

        return snapshot.model_dump(mode="json")


class RoleContextBuilder:
    """Create role-specific v2 projections from normalized scalar facts and references."""

    _fact_limits: ClassVar[dict[AgentRole, int]] = {
        AgentRole.REQUIREMENT: 24,
        AgentRole.SUBJECT: 30,
        AgentRole.PLACE_CURATOR: 40,
        AgentRole.ACCESS: 24,
        AgentRole.BASE: 24,
        AgentRole.ITINERARY_PLANNER: 60,
        AgentRole.VALIDATOR: 60,
        AgentRole.REVIEWER: 60,
        AgentRole.REPLANNER: 50,
        AgentRole.EVIDENCE_COLLECTOR: 30,
    }

    def build(
        self,
        *,
        role: AgentRole,
        run_id: UUID,
        facts: tuple[ContextFact, ...],
        refs: tuple[EntityRef, ...],
    ) -> RoleContext:
        bounded_facts = tuple(facts[: self._fact_limits[role]])
        bounded_refs = tuple(refs[:80])
        payload = {
            "role": role.value,
            "facts": [item.model_dump(mode="json") for item in bounded_facts],
            "refs": [item.model_dump(mode="json") for item in bounded_refs],
        }
        byte_size = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        )
        while byte_size > 64_000 and bounded_facts:
            bounded_facts = bounded_facts[:-1]
            payload["facts"] = [
                item.model_dump(mode="json") for item in bounded_facts
            ]
            byte_size = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            )
        estimated_tokens = min(4000, byte_size // 3 + 1)
        return RoleContext(
            role=role,
            run_id=run_id,
            facts=bounded_facts,
            refs=bounded_refs,
            estimated_tokens=estimated_tokens,
            byte_size=byte_size,
        )

    def reviewer(
        self,
        *,
        run_id: UUID,
        itinerary: ItineraryVersion,
        user_priorities: tuple[str, ...],
        evidence_status: str,
    ) -> RoleContext:
        issues = tuple(item.code for item in itinerary.validation_issues)
        facts = (
            ContextFact(key="strategy", value=itinerary.strategy.value),
            ContextFact(key="timezone", value=itinerary.timezone),
            ContextFact(key="day_count", value=len(itinerary.days)),
            ContextFact(
                key="scheduled_count",
                value=sum(len(day.visits) for day in itinerary.days),
            ),
            ContextFact(key="walking_meters", value=itinerary.total_walking_meters),
            ContextFact(key="duration_minutes", value=itinerary.total_duration_minutes),
            ContextFact(key="omission_count", value=len(itinerary.omissions)),
            ContextFact(key="violation_codes", value=",".join(issues) or "none"),
            ContextFact(key="evidence_status", value=evidence_status),
            ContextFact(key="user_priorities", value="; ".join(user_priorities)[:1000]),
            ContextFact(
                key="coverage",
                value="; ".join(
                    f"{item.subject_id}:{len(item.scheduled_place_ids)}:"
                    f"minimum={item.minimum_place_count}:ok={item.minimum_satisfied}"
                    for item in itinerary.subject_coverage
                )[:2000],
            ),
        )
        refs = (
            EntityRef(
                entity_type="itinerary",
                entity_id=str(itinerary.itinerary_id),
                version=itinerary.version,
            ),
            *(
                EntityRef(entity_type="place", entity_id=str(visit.place_id))
                for day in itinerary.days
                for visit in day.visits
            ),
        )
        return self.build(
            role=AgentRole.REVIEWER, run_id=run_id, facts=facts, refs=refs
        )

    def replanner(
        self,
        *,
        run_id: UUID,
        patch: PlanPatch,
        impact: ImpactAnalysis,
        validation_before: tuple[str, ...],
        validation_after: tuple[str, ...],
    ) -> RoleContext:
        facts = (
            ContextFact(key="patch_id", value=str(patch.patch_id)),
            ContextFact(key="operation_count", value=len(patch.operations)),
            ContextFact(
                key="invalidated_nodes", value=",".join(impact.invalidated_nodes)
            ),
            ContextFact(key="stable_refs", value=",".join(impact.stable_refs)),
            ContextFact(
                key="validation_before", value=",".join(validation_before) or "none"
            ),
            ContextFact(
                key="validation_after", value=",".join(validation_after) or "none"
            ),
        )
        return self.build(
            role=AgentRole.REPLANNER,
            run_id=run_id,
            facts=facts,
            refs=(
                EntityRef(entity_type="patch", entity_id=str(patch.patch_id)),
                *(
                    EntityRef(entity_type="invalidated", entity_id=item)
                    for item in impact.invalidated_refs
                ),
            ),
        )
