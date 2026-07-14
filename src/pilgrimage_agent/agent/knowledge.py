"""Namespace-safe project knowledge boundary for the Agent graph."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pilgrimage_agent.domain.models import ConfirmedSubject, TripRequest
from pilgrimage_agent.rag.schemas import KnowledgeQuery, KnowledgeSearchResult
from pilgrimage_agent.rag.sql import SqlRagRepository


class KnowledgeRetriever(Protocol):
    async def retrieve(
        self,
        *,
        owner_user_id: str,
        trip_id: UUID,
        request: TripRequest,
        subject: ConfirmedSubject,
    ) -> KnowledgeSearchResult: ...


class SqlKnowledgeRetriever:
    def __init__(self, repository: SqlRagRepository) -> None:
        self.repository = repository

    async def retrieve(
        self,
        *,
        owner_user_id: str,
        trip_id: UUID,
        request: TripRequest,
        subject: ConfirmedSubject,
    ) -> KnowledgeSearchResult:
        aliases = tuple(
            item
            for item in (subject.name, subject.name_cn, *subject.aliases)
            if item is not None
        )
        return await self.repository.search(
            KnowledgeQuery(
                owner_user_id=owner_user_id,
                trip_id=trip_id,
                question=(
                    "访问规则、开放时间、拍摄礼仪、交通中断、无障碍与安全注意事项"
                ),
                subject_ids=(subject.subject_id,),
                aliases=aliases,
                location_tags=(request.destination,) if request.destination else (),
                travel_date=request.start_date,
                top_k=6,
            )
        )


class EmptyKnowledgeRetriever:
    async def retrieve(
        self,
        *,
        owner_user_id: str,
        trip_id: UUID,
        request: TripRequest,
        subject: ConfirmedSubject,
    ) -> KnowledgeSearchResult:
        del owner_user_id, trip_id, request, subject
        return KnowledgeSearchResult(status="insufficient_evidence", evidence=())
