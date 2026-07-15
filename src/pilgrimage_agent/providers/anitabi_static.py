"""Versioned MiriaGo-compatible reader for complete Anitabi static map data."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, HttpUrl, TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    GeoCoordinate,
    PilgrimagePoint,
    PilgrimagePointQuery,
    PilgrimagePointResult,
    StrictModel,
)
from pilgrimage_agent.providers.anitabi import episode_reference
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.cache import MemoryProviderCache
from pilgrimage_agent.providers.http import SafeHttpClient

_JSON_LIST = TypeAdapter(list[Any])
_VALID_FILE = re.compile(r"^g(?:\d+)?\.json$")
_ALLOWED_BASES = frozenset(
    {"https://www.anitabi.cn/d", "https://anitabi.cn/d"}
)


class _StaticLitePoint(StrictModel):
    point_id: str = Field(min_length=1, max_length=100)
    coordinate: GeoCoordinate


class _StaticWork(StrictModel):
    bangumi_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    city: str | None = Field(default=None, max_length=200)
    center: GeoCoordinate
    zoom: float
    points: tuple[_StaticLitePoint, ...]


class _StaticIndex(StrictModel):
    works: tuple[_StaticWork, ...]
    page_size: int = Field(ge=1, le=10_000)
    version: str = Field(min_length=1, max_length=120)


class _StaticDetail(StrictModel):
    point_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    episode: int | str | None = None
    seconds: int | None = Field(default=None, ge=0)
    image_url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=2000)
    origin: str | None = Field(default=None, max_length=200)
    origin_url: HttpUrl | None = None


class _PointProvider(Protocol):
    async def fetch(self, query: PilgrimagePointQuery) -> PilgrimagePointResult: ...


def _text(value: object) -> str | None:
    if value is None or value is False or value == 0:
        return None
    normalized = str(value).strip()
    return normalized or None


def _item(sequence: Sequence[object], index: int) -> object | None:
    return sequence[index] if index < len(sequence) else None


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def _scene_seconds(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, float):
        seconds = round(value)
    elif isinstance(value, str):
        try:
            seconds = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    return seconds if seconds >= 0 else None


def _coordinate(latitude: object, longitude: object) -> GeoCoordinate:
    return GeoCoordinate(
        latitude=_number(latitude, field="latitude"),
        longitude=_number(longitude, field="longitude"),
    )


def _image_url(value: object) -> str | None:
    image = _text(value)
    if image is None:
        return None
    if image.startswith("/images/"):
        return f"https://image.anitabi.cn{image[len('/images'):]}"
    return image if image.startswith(("https://", "http://")) else None


class AnitabiStaticAdapter:
    """Read only allowlisted g.json/gN.json resources with version-aware caches."""

    provider = "anitabi_static"

    def __init__(
        self,
        *,
        http: SafeHttpClient,
        base_url: str = "https://www.anitabi.cn/d",
        fallback_url: str = "https://anitabi.cn/d",
        cache_ttl: timedelta = timedelta(hours=6),
    ) -> None:
        normalized = (base_url.rstrip("/"), fallback_url.rstrip("/"))
        if any(item not in _ALLOWED_BASES for item in normalized):
            raise ValueError("Anitabi static URLs must use the allowlisted /d origins")
        if cache_ttl <= timedelta(0) or cache_ttl > timedelta(days=1):
            raise ValueError("Anitabi static cache TTL must be within (0, 1 day]")
        self.http = http
        self.base_urls = tuple(dict.fromkeys(normalized))
        self.cache_ttl = cache_ttl
        self.index_cache: MemoryProviderCache[_StaticIndex] = MemoryProviderCache(
            max_items=1
        )
        self.page_cache: MemoryProviderCache[list[Any]] = MemoryProviderCache(
            max_items=256
        )
        self._active_version: str | None = None

    def clear(self) -> None:
        """Clear only static-index/page cache state for this adapter."""

        self.index_cache.clear()
        self.page_cache.clear()
        self._active_version = None

    def refresh(self) -> None:
        """Force the next index read while retaining only matching-version pages."""

        self.index_cache.clear()

    async def fetch(self, query: PilgrimagePointQuery) -> PilgrimagePointResult:
        if not query.subject_id.isdecimal():
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                self.provider,
                "Anitabi requires a numeric Bangumi subject identifier.",
            )
        index = await self._index()
        bangumi_id = int(query.subject_id)
        work_index = next(
            (
                position
                for position, work in enumerate(index.works)
                if work.bangumi_id == bangumi_id
            ),
            -1,
        )
        if work_index < 0:
            raise ProviderError(
                ProviderErrorKind.NOT_FOUND,
                self.provider,
                "The confirmed Bangumi subject is absent from the static Anitabi index.",
            )
        work = index.works[work_index]
        guessed_page = work_index // index.page_size
        page_count = ceil(len(index.works) / index.page_size)
        detail_rows: list[Any] | None = None
        page_source: str | None = None
        page_order = (guessed_page, *(
            page for page in range(page_count) if page != guessed_page
        ))
        for page in page_order:
            page_payload, source = await self._page(page, index.version)
            detail_rows = self._find_work_rows(page_payload, bangumi_id)
            if detail_rows is not None:
                page_source = source
                break
        if detail_rows is None or page_source is None:
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "The static Anitabi index and detail pages were temporarily inconsistent.",
            )
        return self._normalize(work, detail_rows, index.version, page_source)

    async def _index(self) -> _StaticIndex:
        cached = self.index_cache.get("index")
        if cached is not None:
            return cached
        raw, _source = await self._read("g.json")
        index = self._parse_index(raw)
        if self._active_version is not None and self._active_version != index.version:
            self.page_cache.clear()
        self._active_version = index.version
        self.index_cache.put(
            provider=self.provider,
            fingerprint="index",
            value=index,
            ttl=self.cache_ttl,
        )
        return index

    async def _page(self, page: int, version: str) -> tuple[list[Any], str]:
        fingerprint = f"page:{version}:{page}"
        cached = self.page_cache.get(fingerprint)
        if cached is not None:
            return cached, self._url(self.base_urls[0], f"g{page}.json", version)
        raw, source = await self._read(f"g{page}.json", version=version)
        try:
            payload = _JSON_LIST.validate_python(raw)
        except ValidationError:
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "Anitabi returned an invalid static detail page.",
            ) from None
        self.page_cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=payload,
            ttl=self.cache_ttl,
        )
        return payload, source

    async def _read(
        self, file_name: str, *, version: str | None = None
    ) -> tuple[object, str]:
        if _VALID_FILE.fullmatch(file_name) is None:
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                self.provider,
                "Only the Anitabi g.json and g<number>.json resources are allowed.",
            )
        first_error: ProviderError | None = None
        for base in self.base_urls:
            source = self._url(base, file_name, version)
            try:
                return await self.http.request_json("GET", source), source
            except ProviderError as error:
                first_error = first_error or error
        assert first_error is not None
        raise first_error

    @staticmethod
    def _url(base: str, file_name: str, version: str | None) -> str:
        suffix = f"?{urlencode({'v': version})}" if version else ""
        return f"{base}/{file_name}{suffix}"

    def _parse_index(self, raw: object) -> _StaticIndex:
        try:
            index = _JSON_LIST.validate_python(raw)
            works_raw = _JSON_LIST.validate_python(index[0])
            page_size = int(index[1])
            version = _text(index[2])
            if version is None:
                raise ValueError
            works = tuple(self._parse_work(item) for item in works_raw)
            return _StaticIndex(works=works, page_size=page_size, version=version)
        except (IndexError, TypeError, ValueError, ValidationError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "Anitabi returned an invalid static index.",
            ) from None

    @staticmethod
    def _parse_work(raw: object) -> _StaticWork:
        record = _JSON_LIST.validate_python(raw)
        points_raw = _JSON_LIST.validate_python(_item(record, 12) or [])
        if len(points_raw) % 4 != 0:
            raise ValueError("compressed point coordinates must use groups of four")
        points: list[_StaticLitePoint] = []
        for offset in range(0, len(points_raw), 4):
            point_id = _text(points_raw[offset])
            if point_id is None:
                raise ValueError("static point ID is required")
            points.append(
                _StaticLitePoint(
                    point_id=point_id,
                    coordinate=_coordinate(
                        points_raw[offset + 1], points_raw[offset + 2]
                    ),
                )
            )
        title = _text(_item(record, 1)) or _text(_item(record, 3))
        if title is None:
            raise ValueError("static work title is required")
        return _StaticWork(
            bangumi_id=int(record[0]),
            title=title,
            city=_text(_item(record, 4)),
            center=_coordinate(_item(record, 9), _item(record, 10)),
            zoom=_number(_item(record, 11) or 12, field="zoom"),
            points=tuple(points),
        )

    @staticmethod
    def _find_work_rows(page: list[Any], bangumi_id: int) -> list[Any] | None:
        for raw_entry in page:
            try:
                entry = _JSON_LIST.validate_python(raw_entry)
                if int(entry[0]) != bangumi_id:
                    continue
                return _JSON_LIST.validate_python(entry[2])
            except (IndexError, TypeError, ValueError, ValidationError):
                continue
        return None

    def _normalize(
        self,
        work: _StaticWork,
        detail_rows: list[Any],
        version: str,
        page_source: str,
    ) -> PilgrimagePointResult:
        details: dict[str, _StaticDetail] = {}
        warnings: list[str] = []
        for index, raw in enumerate(detail_rows):
            try:
                detail = self._parse_detail(raw)
            except ValidationError as error:
                fields = ",".join(
                    sorted(
                        {
                            str(item["loc"][0])
                            for item in error.errors(
                                include_url=False,
                                include_input=False,
                            )
                            if item["loc"]
                        }
                    )
                )
                warnings.append(
                    "Skipped invalid static Anitabi detail at index "
                    f"{index} (fields: {fields or 'record'})."
                )
                continue
            except (TypeError, ValueError):
                warnings.append(
                    f"Skipped invalid static Anitabi detail at index {index}."
                )
                continue
            if detail.point_id in details:
                warnings.append(f"Skipped duplicate static Anitabi point {detail.point_id}.")
                continue
            details[detail.point_id] = detail
        fetched_at = datetime.now(UTC)
        expires_at = fetched_at + self.cache_ttl
        result_provenance = DataProvenance(
            provider=self.provider,
            source_url=page_source,
            fetched_at=fetched_at,
            expires_at=expires_at,
            status=DataStatus.COMMUNITY,
            schema_version=version,
        )
        points: list[PilgrimagePoint] = []
        for lite in work.points:
            selected_detail = details.get(lite.point_id)
            if selected_detail is None:
                warnings.append(
                    f"Static Anitabi detail is missing for point {lite.point_id}."
                )
                continue
            source_url = (
                str(selected_detail.origin_url)
                if selected_detail.origin_url is not None
                else f"https://anitabi.cn/map?bangumiId={work.bangumi_id}"
            )
            points.append(
                PilgrimagePoint(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"anitabi:{work.bangumi_id}:{lite.point_id}",
                    ),
                    subject_id=str(work.bangumi_id),
                    name=selected_detail.name,
                    latitude=lite.coordinate.latitude,
                    longitude=lite.coordinate.longitude,
                    episode_refs=tuple(
                        filter(
                            None,
                            (
                                episode_reference(
                                    selected_detail.episode,
                                    selected_detail.seconds,
                                ),
                            ),
                        )
                    ),
                    image_url=selected_detail.image_url,
                    description=selected_detail.description,
                    confidence="community",
                    source_label=selected_detail.origin or "Anitabi",
                    provenance=DataProvenance.model_validate(
                        {
                            **result_provenance.model_dump(),
                            "source_url": source_url,
                        }
                    ),
                )
            )
        expected_count = len(work.points)
        complete = len(points) == expected_count and not warnings
        return PilgrimagePointResult(
            points=tuple(points),
            is_complete=complete,
            expected_count=expected_count,
            loaded_count=len(points),
            data_version=version,
            warnings=tuple(warnings),
            provenance=result_provenance,
        )

    @staticmethod
    def _parse_detail(raw: object) -> _StaticDetail:
        row = _JSON_LIST.validate_python(raw)
        point_id = _text(_item(row, 0))
        name = _text(_item(row, 2)) or _text(_item(row, 1))
        if point_id is None or name is None:
            raise ValueError("static point identity and name are required")
        return _StaticDetail(
            point_id=point_id,
            name=name,
            episode=_item(row, 8),
            seconds=_scene_seconds(_item(row, 9)),
            image_url=_image_url(_item(row, 6)),
            description=_text(_item(row, 10)),
            origin=_text(_item(row, 11)),
            origin_url=_text(_item(row, 12)),
        )


class StaticThenDetailAnitabiProvider:
    """Prefer complete static data; detail fallback is always disclosed as partial."""

    provider = "anitabi_static_with_detail_fallback"

    def __init__(self, static: AnitabiStaticAdapter, detail: _PointProvider) -> None:
        self.static = static
        self.detail = detail

    async def fetch(self, query: PilgrimagePointQuery) -> PilgrimagePointResult:
        try:
            return await self.static.fetch(query)
        except ProviderError as error:
            detail = await self.detail.fetch(query)
            return detail.model_copy(
                update={
                    "is_complete": False,
                    "warnings": (
                        "Anitabi static data was unavailable; the documented detail "
                        f"fallback is incomplete ({error.kind.value}).",
                        *detail.warnings,
                    ),
                }
            )
