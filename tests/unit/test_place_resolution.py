"""Scene evidence resolves to canonical places without loss or order dependence."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from pilgrimage_agent.curation.resolution import evidence_from_point, resolve_places
from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    GeoCoordinate,
    PilgrimagePoint,
)
from pilgrimage_agent.domain.workspace import (
    EvidenceResolutionStatus,
    PlaceResolutionOverride,
    SceneEvidence,
)


def _provenance(provider: str = "fixture") -> DataProvenance:
    return DataProvenance(
        provider=provider,
        fetched_at=datetime.now(UTC),
        status=DataStatus.COMMUNITY,
    )


def _evidence(
    key: str,
    subject_id: str,
    name: str,
    latitude: float | None,
    longitude: float | None,
    *,
    source_label: str | None = None,
) -> SceneEvidence:
    coordinate = (
        GeoCoordinate(latitude=latitude, longitude=longitude)
        if latitude is not None and longitude is not None
        else None
    )
    return SceneEvidence(
        evidence_id=uuid5(NAMESPACE_URL, f"test-evidence:{key}"),
        subject_id=subject_id,
        provider="fixture",
        provider_record_id=key,
        coordinate=coordinate,
        names=(name,),
        source_label=source_label,
        provenance=_provenance(),
        raw_fingerprint=(key.encode().hex() + "0" * 64)[:64],
    )


def _corpus() -> tuple[SceneEvidence, ...]:
    return (
        _evidence(
            "shared-bocchi",
            "328609",
            "下北沢 SHELTER 周辺",
            35.66110,
            139.66810,
            source_label="SHELTER",
        ),
        _evidence(
            "shared-lycoris",
            "lycoris",
            "SHELTER",
            35.66115,
            139.66812,
            source_label="SHELTER",
        ),
        _evidence("exit-1", "328609", "下北沢駅 1番出口", 35.65900, 139.66700),
        _evidence("exit-2", "328609", "下北沢駅 2番出口", 35.65902, 139.66702),
        _evidence("park-tokyo", "328609", "Central Park", 35.68000, 139.70000),
        _evidence("park-osaka", "lycoris", "Central Park", 34.69000, 135.50000),
        _evidence("isolated", "your-name", "糸守 展望台", 36.10000, 137.20000),
        _evidence("invalid", "your-name", "Invalid record", None, None),
    )


def _membership(result: object) -> set[frozenset[str]]:
    places = result.places  # type: ignore[attr-defined]
    return {
        frozenset(str(item) for item in place.scene_evidence_ids) for place in places
    }


def test_resolution_handles_shared_places_exits_distance_invalid_and_singletons() -> None:
    corpus = _corpus()
    result = resolve_places(corpus)

    assert len(result.evidence) == 8
    assert len(result.quarantined) == 1
    assert len(result.places) == 6
    shared = next(place for place in result.places if len(place.subject_appearances) == 2)
    assert {item.subject_id for item in shared.subject_appearances} == {
        "328609",
        "lycoris",
    }
    exits = [place for place in result.places if place.place_type == "station_exit"]
    assert len(exits) == 2
    assert all(len(place.scene_evidence_ids) == 1 for place in exits)
    assert all(
        item.resolution_status is EvidenceResolutionStatus.RESOLVED
        for item in result.evidence
        if item.coordinate is not None
    )
    invalid = next(item for item in result.evidence if item.coordinate is None)
    assert invalid.resolution_status is EvidenceResolutionStatus.QUARANTINED
    assert invalid.quarantine_reason


def test_resolution_membership_and_ids_are_stable_under_input_order() -> None:
    corpus = _corpus()
    forward = resolve_places(corpus)
    reverse = resolve_places(tuple(reversed(corpus)))

    assert _membership(forward) == _membership(reverse)
    assert {place.place_id for place in forward.places} == {
        place.place_id for place in reverse.places
    }


def test_same_source_label_is_not_place_identity() -> None:
    first = _evidence(
        "source-a",
        "328609",
        "Completely Different Facility",
        35.66110,
        139.66810,
        source_label="same article title",
    )
    second = _evidence(
        "source-b",
        "lycoris",
        "Unrelated Street Corner",
        35.66111,
        139.66811,
        source_label="same article title",
    )

    result = resolve_places((first, second))

    assert len(result.places) == 2
    assert result.ambiguous_merges


def test_manual_split_and_merge_overrides_survive_reingestion() -> None:
    first, second, exit_one, exit_two, *_rest = _corpus()
    split = PlaceResolutionOverride(
        action="split",
        evidence_ids=(first.evidence_id, second.evidence_id),
        reason="The user confirmed separate facilities.",
        created_at=datetime.now(UTC),
    )
    merged = PlaceResolutionOverride(
        action="merge",
        evidence_ids=(exit_one.evidence_id, exit_two.evidence_id),
        reason="The user confirmed one visit destination.",
        created_at=datetime.now(UTC),
    )

    first_run = resolve_places((first, second, exit_one, exit_two), overrides=(split, merged))
    second_run = resolve_places(
        (exit_two, first, exit_one, second), overrides=first_run.overrides
    )

    assert len(first_run.places) == 3
    assert _membership(first_run) == _membership(second_run)
    assert first_run.overrides == second_run.overrides
    assert {override.override_id for override in first_run.overrides} == {
        split.override_id,
        merged.override_id,
    }


def test_legacy_point_adapter_is_stable_and_preserves_source() -> None:
    point = PilgrimagePoint(
        id=uuid5(NAMESPACE_URL, "legacy-point"),
        subject_id="328609",
        name="下北沢 SHELTER",
        latitude=35.6611,
        longitude=139.6681,
        episode_refs=("第8话",),
        image_url="https://image.anitabi.cn/points/328609/fixture.jpg?plan=h160",
        confidence="community",
        source_label="Anitabi",
        provenance=_provenance("anitabi"),
    )

    first = evidence_from_point(point)
    second = evidence_from_point(point)

    assert first == second
    assert first.provider == "anitabi"
    assert first.provider_record_id == str(point.id)
    assert first.episode_refs == ("第8话",)
    assert str(first.image_url).endswith("fixture.jpg?plan=h160")
