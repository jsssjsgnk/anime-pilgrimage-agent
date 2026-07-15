"""MiriaGo-compatible Anitabi static index/page contracts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    PilgrimagePoint,
    PilgrimagePointQuery,
    PilgrimagePointResult,
)
from pilgrimage_agent.providers.anitabi_static import (
    AnitabiStaticAdapter,
    StaticThenDetailAnitabiProvider,
)
from pilgrimage_agent.providers.http import SafeHttpClient
from pilgrimage_agent.providers.points import build_route_a


def _work(subject_id: int, point_ids: tuple[str, ...]) -> list[object]:
    compressed: list[object] = []
    for index, point_id in enumerate(point_ids):
        compressed.extend((point_id, 35.0 + index / 1000, 139.0, 0))
    return [
        subject_id,
        f"作品 {subject_id}",
        0,
        f"Work {subject_id}",
        "东京",
        0,
        0,
        0,
        0,
        35.0,
        139.0,
        12,
        compressed,
    ]


def _detail(
    point_id: str,
    index: int = 0,
    *,
    seconds: object = 65,
) -> list[object]:
    return [
        point_id,
        f"Point {index}",
        f"地点 {index}",
        0,
        0,
        0,
        f"/images/{point_id}.jpg",
        0,
        index + 1,
        seconds,
        "现场说明",
        "资料来源",
        "https://example.test/source",
    ]


def _response(request: httpx.Request, payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, request=request, json=payload)


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[AnitabiStaticAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = SafeHttpClient(
        provider="anitabi_static",
        timeout_seconds=1,
        max_attempts=1,
        max_response_bytes=1024 * 1024,
        client=client,
    )
    return AnitabiStaticAdapter(http=http), client


async def test_static_index_and_page_load_all_points_with_version() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.url.path}?{request.url.query.decode()}")
        if request.url.path.endswith("/g.json"):
            return _response(request, [[_work(328609, ("a", "b", "c"))], 10, "v1"])
        return _response(
            request,
            [[328609, 0, [_detail("a"), _detail("b", 1), _detail("c", 2)]]],
        )

    adapter, client = _adapter(handler)
    detail = _DetailFallback()
    provider = StaticThenDetailAnitabiProvider(adapter, detail)
    try:
        result = await provider.fetch(
            PilgrimagePointQuery(subject_id="328609", provider="anitabi")
        )
    finally:
        await client.aclose()

    assert result.is_complete
    assert result.expected_count == result.loaded_count == 3
    assert result.data_version == "v1"
    assert result.provenance.provider == "anitabi_static"
    assert result.points[0].description == "现场说明"
    assert str(result.points[0].image_url) == "https://image.anitabi.cn/a.jpg"
    assert calls == ["/d/g.json?", "/d/g0.json?v=v1"]
    assert detail.calls == 0


async def test_static_reader_uses_allowlisted_fallback_origin() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host or "")
        if request.url.host == "www.anitabi.cn":
            return _response(request, {"error": "primary unavailable"}, status=503)
        if request.url.path.endswith("/g.json"):
            return _response(request, [[_work(100, ("point",))], 10, "v1"])
        return _response(request, [[100, 0, [_detail("point")]]])

    adapter, client = _adapter(handler)
    try:
        result = await adapter.fetch(
            PilgrimagePointQuery(subject_id="100", provider="anitabi")
        )
    finally:
        await client.aclose()

    assert result.is_complete
    assert hosts == [
        "www.anitabi.cn",
        "anitabi.cn",
        "www.anitabi.cn",
        "anitabi.cn",
    ]


async def test_missing_static_detail_is_partial_without_fabricated_point() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/g.json"):
            return _response(request, [[_work(100, ("present", "missing"))], 10, "v4"])
        return _response(request, [[100, 0, [_detail("present")]]])

    adapter, client = _adapter(handler)
    try:
        result = await adapter.fetch(
            PilgrimagePointQuery(subject_id="100", provider="anitabi")
        )
    finally:
        await client.aclose()

    assert not result.is_complete
    assert result.expected_count == 2
    assert result.loaded_count == 1
    assert [point.name for point in result.points] == ["地点 0"]
    assert "missing" in result.warnings[0]


async def test_non_numeric_scene_second_does_not_drop_a_static_point() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/g.json"):
            return _response(request, [[_work(100, ("unknown-time",))], 10, "v5"])
        return _response(
            request,
            [[100, 0, [_detail("unknown-time", seconds="待补充")]]],
        )

    adapter, client = _adapter(handler)
    try:
        result = await adapter.fetch(
            PilgrimagePointQuery(subject_id="100", provider="anitabi")
        )
    finally:
        await client.aclose()

    assert result.is_complete
    assert result.expected_count == result.loaded_count == 1
    assert result.points[0].episode_refs == ("第1话",)


async def test_static_reader_rejects_non_allowlisted_origin() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: _response(request, []))
    )
    http = SafeHttpClient(
        provider="anitabi_static",
        timeout_seconds=1,
        max_attempts=1,
        client=client,
    )
    try:
        with pytest.raises(ValueError, match="allowlisted"):
            AnitabiStaticAdapter(http=http, base_url="https://example.test/d")
    finally:
        await client.aclose()


async def test_static_reader_scans_other_pages_when_guessed_page_is_stale() -> None:
    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/g.json"):
            return _response(
                request,
                [[_work(100, ("target",)), _work(200, ("other",))], 1, "v2"],
            )
        requested_pages.append(request.url.path)
        if request.url.path.endswith("/g0.json"):
            return _response(request, [[200, 0, [_detail("other")]]])
        return _response(request, [[100, 0, [_detail("target")]]])

    adapter, client = _adapter(handler)
    try:
        result = await adapter.fetch(
            PilgrimagePointQuery(subject_id="100", provider="anitabi")
        )
    finally:
        await client.aclose()

    assert result.is_complete
    assert requested_pages == ["/d/g0.json", "/d/g1.json"]


async def test_version_change_invalidates_old_page_cache() -> None:
    version = "v1"
    page_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/g.json"):
            return _response(request, [[_work(100, ("point",))], 10, version])
        page_queries.append(request.url.query.decode())
        return _response(request, [[100, 0, [_detail("point")]]])

    adapter, client = _adapter(handler)
    try:
        query = PilgrimagePointQuery(subject_id="100", provider="anitabi")
        first = await adapter.fetch(query)
        version = "v2"
        adapter.refresh()
        second = await adapter.fetch(query)
    finally:
        await client.aclose()

    assert first.data_version == "v1"
    assert second.data_version == "v2"
    assert page_queries == ["v=v1", "v=v2"]


class _DetailFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, query: PilgrimagePointQuery) -> PilgrimagePointResult:
        self.calls += 1
        point = PilgrimagePoint(
            id=UUID(int=1),
            subject_id=query.subject_id,
            name="Detail only",
            latitude=35,
            longitude=139,
            confidence="community",
            provenance=DataProvenance(
                provider="anitabi_detail",
                fetched_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=6),
                status=DataStatus.COMMUNITY,
            ),
        )
        return PilgrimagePointResult(
            points=(point,),
            is_complete=True,
            expected_count=1,
            loaded_count=1,
            provenance=point.provenance,
        )


async def test_static_failure_uses_detail_fallback_but_never_claims_complete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(request, {"error": "unavailable"}, status=503)

    adapter, client = _adapter(handler)
    detail = _DetailFallback()
    provider = StaticThenDetailAnitabiProvider(adapter, detail)
    try:
        result = await provider.fetch(
            PilgrimagePointQuery(subject_id="328609", provider="anitabi")
        )
    finally:
        await client.aclose()

    assert detail.calls == 1
    assert result.loaded_count == 1
    assert not result.is_complete
    assert "detail fallback is incomplete" in result.warnings[0]


async def test_same_static_point_id_in_two_works_keeps_distinct_scene_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/g.json"):
            return _response(
                request,
                [[_work(100, ("shared",)), _work(200, ("shared",))], 10, "v3"],
            )
        return _response(
            request,
            [[100, 0, [_detail("shared")]], [200, 0, [_detail("shared")]]],
        )

    adapter, client = _adapter(handler)
    try:
        first = await adapter.fetch(
            PilgrimagePointQuery(subject_id="100", provider="anitabi")
        )
        second = await adapter.fetch(
            PilgrimagePointQuery(subject_id="200", provider="anitabi")
        )
    finally:
        await client.aclose()

    assert first.points[0].latitude == second.points[0].latitude
    assert first.points[0].longitude == second.points[0].longitude
    assert first.points[0].id != second.points[0].id


async def test_route_a_keeps_distinct_scene_ids_at_the_same_real_place() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/g.json"):
            work = _work(100, ("scene-a", "scene-b"))
            compressed = work[12]
            assert isinstance(compressed, list)
            compressed[5] = compressed[1]
            compressed[6] = compressed[2]
            return _response(request, [[work], 10, "v6"])
        first = _detail("scene-a")
        second = _detail("scene-b")
        second[1] = first[1]
        second[2] = first[2]
        return _response(request, [[100, 0, [first, second]]])

    adapter, client = _adapter(handler)
    try:
        result = await adapter.fetch(
            PilgrimagePointQuery(subject_id="100", provider="anitabi")
        )
    finally:
        await client.aclose()

    route = build_route_a(result, subject_id="100")
    assert len(route.points) == 2
    assert route.points[0].id != route.points[1].id
    assert route.points[0].latitude == route.points[1].latitude
    assert route.points[0].longitude == route.points[1].longitude
