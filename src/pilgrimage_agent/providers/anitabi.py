"""Documented read-only Anitabi Open API pilgrimage-point Provider."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    PilgrimagePoint,
    PilgrimagePointQuery,
    PilgrimagePointResult,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.cache import MemoryProviderCache, request_fingerprint
from pilgrimage_agent.providers.common import provenance
from pilgrimage_agent.providers.http import SafeHttpClient
from pilgrimage_agent.providers.points import FixturePilgrimagePointProvider

_LIST = TypeAdapter(list[Any])


class _AnitabiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _AnitabiLiteResponse(_AnitabiModel):
    id: int | str
    modified: int | None = None
    points_length: int = Field(alias="pointsLength", ge=0)
    images_length: int | None = Field(default=None, alias="imagesLength", ge=0)


class _AnitabiDetailPoint(_AnitabiModel):
    id: str = Field(min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=300)
    cn: str | None = Field(default=None, max_length=300)
    ep: int | str | None = None
    s: int | float | None = Field(default=None, ge=0)
    geo: tuple[float, float]
    image: HttpUrl | None = None
    origin: str | None = Field(default=None, max_length=200)
    origin_url: HttpUrl | None = Field(default=None, alias="originURL")


def _episode_reference(episode: int | str | None, seconds: int | float | None) -> str | None:
    parts: list[str] = []
    if isinstance(episode, int):
        parts.append(f"第{episode}话")
    elif isinstance(episode, str) and episode.strip():
        parts.append(episode.strip())
    if seconds is not None:
        total = int(seconds)
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        timestamp = (
            f"{hours:02d}:{minutes:02d}:{secs:02d}"
            if hours
            else f"{minutes:02d}:{secs:02d}"
        )
        parts.append(timestamp)
    return " · ".join(parts) if parts else None


class AnitabiProvider:
    """Fetch the complete documented Anitabi point array for one Bangumi subject."""

    provider = "anitabi"

    def __init__(
        self,
        *,
        http: SafeHttpClient,
        base_url: str = "https://api.anitabi.cn",
        user_agent: str = "anime-pilgrimage-agent/0.1 (read-only)",
    ) -> None:
        if base_url.rstrip("/") != "https://api.anitabi.cn":
            raise ValueError("Anitabi base URL must use the documented API host")
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.cache: MemoryProviderCache[PilgrimagePointResult] = MemoryProviderCache()

    async def fetch(self, query: PilgrimagePointQuery) -> PilgrimagePointResult:
        if not query.subject_id.isdecimal():
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                self.provider,
                "Anitabi requires a numeric Bangumi subject identifier.",
            )
        fingerprint = request_fingerprint(self.provider, query)
        cached = self.cache.get(fingerprint)
        if cached is not None:
            return cached

        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        subject_path = f"{self.base_url}/bangumi/{query.subject_id}"
        lite_raw = await self.http.request_json(
            "GET", f"{subject_path}/lite", headers=headers
        )
        detail_raw = await self.http.request_json(
            "GET", f"{subject_path}/points/detail", headers=headers
        )
        result = self._normalize(lite_raw, detail_raw, query)
        self.cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(hours=6),
        )
        return result

    def _normalize(
        self,
        lite_raw: object,
        detail_raw: object,
        query: PilgrimagePointQuery,
    ) -> PilgrimagePointResult:
        try:
            lite = _AnitabiLiteResponse.model_validate(lite_raw)
            items = _LIST.validate_python(detail_raw)
        except ValidationError:
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "Anitabi returned data that did not match its documented schema.",
            ) from None

        warnings: list[str] = []
        if str(lite.id) != query.subject_id:
            warnings.append("Anitabi lite metadata did not match the requested subject.")
        documented_detail_count = lite.images_length or lite.points_length
        if len(items) != documented_detail_count:
            warnings.append(
                "Anitabi detail count did not match the advertised screenshot-detail count; "
                "Route A is partial."
            )
        if lite.images_length is not None and lite.points_length > lite.images_length:
            warnings.append(
                f"Anitabi advertises {lite.points_length} total map points, but its documented "
                f"detail API exposes {lite.images_length} screenshot-detailed points; Route A "
                "does not claim the unavailable remainder."
            )

        subject_map_url = f"https://anitabi.cn/map?bangumiId={query.subject_id}"
        result_provenance = provenance(
            self.provider,
            subject_map_url,
            ttl=timedelta(hours=6),
            status=DataStatus.COMMUNITY,
        )
        points: list[PilgrimagePoint] = []
        for index, raw_item in enumerate(items):
            try:
                item = _AnitabiDetailPoint.model_validate(raw_item)
                point = self._point(item, query.subject_id, subject_map_url, result_provenance)
            except (ValidationError, ValueError):
                warnings.append(f"Skipped invalid Anitabi point at index {index}.")
                continue
            points.append(point)

        complete = (
            not warnings
            and str(lite.id) == query.subject_id
            and len(points) == lite.points_length
        )
        return PilgrimagePointResult(
            points=tuple(points),
            is_complete=complete,
            warnings=tuple(warnings),
            provenance=result_provenance,
        )

    def _point(
        self,
        item: _AnitabiDetailPoint,
        subject_id: str,
        subject_map_url: str,
        result_provenance: DataProvenance,
    ) -> PilgrimagePoint:
        name = (item.cn or item.name or "").strip()
        if not name:
            raise ValueError("Anitabi point has no usable name")
        latitude, longitude = item.geo
        source_url = str(item.origin_url) if item.origin_url else subject_map_url
        episode_reference = _episode_reference(item.ep, item.s)
        return PilgrimagePoint(
            id=uuid5(NAMESPACE_URL, f"anitabi:{subject_id}:{item.id}"),
            subject_id=subject_id,
            name=name,
            latitude=latitude,
            longitude=longitude,
            episode_refs=(episode_reference,) if episode_reference else (),
            image_url=item.image,
            confidence="community",
            source_label=item.origin or "Anitabi",
            provenance=DataProvenance.model_validate(
                {**result_provenance.model_dump(), "source_url": source_url}
            ),
        )


class FixtureAnitabiProvider(FixturePilgrimagePointProvider):
    """Deterministic Anitabi-shaped point fixture for tests and offline demos."""

    provider = "anitabi-fixture"
