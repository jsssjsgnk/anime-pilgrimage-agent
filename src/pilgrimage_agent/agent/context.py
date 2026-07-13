"""Node-specific context snapshots that exclude conversation and secrets."""

from collections.abc import Mapping
from hashlib import sha256

from pilgrimage_agent.agent.schemas import ContextSnapshot


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
