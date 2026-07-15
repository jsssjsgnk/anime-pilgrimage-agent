"""Resolve raw scene evidence into stable canonical visitable places."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import product
from math import cos, floor, radians, sin
from uuid import NAMESPACE_URL, UUID, uuid5

from pilgrimage_agent.domain.models import (
    DataStatus,
    GeoCoordinate,
    PilgrimagePoint,
)
from pilgrimage_agent.domain.workspace import (
    AmbiguousPlaceMerge,
    EvidenceQuarantine,
    EvidenceResolutionStatus,
    PlaceResolutionOverride,
    PlaceResolutionResult,
    SceneEvidence,
    SubjectAppearance,
    VisitPlace,
)
from pilgrimage_agent.planning.geo import haversine_meters

POLICY_VERSION = "place-resolution-v2"
_SPACE = re.compile(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", re.UNICODE)
_EXIT = re.compile(
    r"(?:exit\s*[a-z0-9]+|[東西南北中央]?(?:口|出口)|\d+番?(?:口|出口))",
    re.IGNORECASE,
)


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(_SPACE.sub(" ", normalized).split())


def _fingerprint(point: PilgrimagePoint) -> str:
    payload = {
        "id": str(point.id),
        "subject_id": point.subject_id,
        "name": point.name,
        "latitude": point.latitude,
        "longitude": point.longitude,
        "episode_refs": point.episode_refs,
        "source_label": point.source_label,
        "provider": point.provenance.provider,
    }
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def evidence_from_point(
    point: PilgrimagePoint, *, trip_id: UUID | None = None
) -> SceneEvidence:
    """Compatibility adapter: one legacy point becomes one raw evidence record."""

    provider = point.provenance.provider
    namespace = str(trip_id) if trip_id is not None else "compatibility"
    evidence_id = uuid5(
        NAMESPACE_URL,
        f"scene-evidence:{namespace}:{provider}:{point.subject_id}:{point.id}",
    )
    return SceneEvidence(
        evidence_id=evidence_id,
        subject_id=point.subject_id,
        provider=provider,
        provider_record_id=str(point.id),
        coordinate=GeoCoordinate(latitude=point.latitude, longitude=point.longitude),
        names=(point.name,),
        description=point.description,
        episode_refs=point.episode_refs,
        image_url=point.image_url,
        source_url=point.provenance.source_url,
        source_label=point.source_label,
        provenance=point.provenance,
        raw_fingerprint=_fingerprint(point),
    )


def _distance(first: SceneEvidence, second: SceneEvidence) -> float:
    assert first.coordinate is not None
    assert second.coordinate is not None
    return haversine_meters(first.coordinate, second.coordinate)


def _name_similarity(first: SceneEvidence, second: SceneEvidence) -> float:
    first_names = tuple(_normalized_name(name) for name in first.names)
    second_names = tuple(_normalized_name(name) for name in second.names)
    return max(
        SequenceMatcher(None, left, right).ratio()
        for left in first_names
        for right in second_names
    )


def _distinctive_name_containment(first: SceneEvidence, second: SceneEvidence) -> bool:
    generic = {"station", "park", "street", "bridge", "exit", "駅", "公園", "橋"}
    for left in (_normalized_name(name).replace(" ", "") for name in first.names):
        for right in (_normalized_name(name).replace(" ", "") for name in second.names):
            shorter, longer = sorted((left, right), key=len)
            if len(shorter) >= 4 and shorter not in generic and shorter in longer:
                return True
    return False


def _exit_tokens(evidence: SceneEvidence) -> frozenset[str]:
    return frozenset(
        _normalized_name(match.group(0))
        for name in evidence.names
        for match in _EXIT.finditer(unicodedata.normalize("NFKC", name))
    )


@dataclass(frozen=True, slots=True)
class _PairDecision:
    action: str
    distance_meters: float
    similarity: float
    override_id: UUID | None = None


def _override_for(
    first: UUID,
    second: UUID,
    overrides: tuple[PlaceResolutionOverride, ...],
) -> PlaceResolutionOverride | None:
    pair = {first, second}
    matching = [item for item in overrides if pair.issubset(set(item.evidence_ids))]
    splits = [item for item in matching if item.action == "split"]
    return min(splits or matching, key=lambda item: str(item.override_id), default=None)


def _pair_decision(
    first: SceneEvidence,
    second: SceneEvidence,
    overrides: tuple[PlaceResolutionOverride, ...],
    *,
    radius_meters: float,
) -> _PairDecision:
    distance = _distance(first, second)
    similarity = _name_similarity(first, second)
    override = _override_for(first.evidence_id, second.evidence_id, overrides)
    if override is not None:
        return _PairDecision(
            override.action, distance, similarity, override.override_id
        )
    first_exits = _exit_tokens(first)
    second_exits = _exit_tokens(second)
    if first_exits and second_exits and first_exits.isdisjoint(second_exits):
        return _PairDecision("split", distance, similarity)
    if distance > radius_meters:
        return _PairDecision("separate", distance, similarity)
    if (
        first.provider == second.provider
        and first.provider_record_id == second.provider_record_id
    ):
        return _PairDecision("merge", distance, 1.0)
    if distance <= 25 and _distinctive_name_containment(first, second):
        return _PairDecision("merge", distance, max(similarity, 0.9))
    if distance <= 12 and similarity >= 0.85:
        return _PairDecision("merge", distance, similarity)
    if similarity >= 0.92:
        return _PairDecision("merge", distance, similarity)
    if similarity >= 0.35 or distance <= 25:
        return _PairDecision("ambiguous", distance, similarity)
    return _PairDecision("separate", distance, similarity)


def _spatial_candidate_pairs(
    evidence: tuple[SceneEvidence, ...], radius_meters: float
) -> set[frozenset[UUID]]:
    """Generate bounded nearby candidates using a three-dimensional earth grid."""

    earth_radius = 6_371_008.8
    buckets: dict[tuple[int, int, int], list[SceneEvidence]] = defaultdict(list)
    pairs: set[frozenset[UUID]] = set()
    for item in evidence:
        assert item.coordinate is not None
        latitude = radians(item.coordinate.latitude)
        longitude = radians(item.coordinate.longitude)
        key = (
            floor(earth_radius * cos(latitude) * cos(longitude) / radius_meters),
            floor(earth_radius * cos(latitude) * sin(longitude) / radius_meters),
            floor(earth_radius * sin(latitude) / radius_meters),
        )
        for offset in product((-1, 0, 1), repeat=3):
            neighbor_key = (
                key[0] + offset[0],
                key[1] + offset[1],
                key[2] + offset[2],
            )
            for candidate in buckets.get(neighbor_key, ()):
                pairs.add(frozenset((candidate.evidence_id, item.evidence_id)))
        buckets[key].append(item)
    return pairs


def _medoid(evidence: tuple[SceneEvidence, ...]) -> SceneEvidence:
    return min(
        evidence,
        key=lambda candidate: (
            sum(_distance(candidate, other) for other in evidence),
            str(candidate.evidence_id),
        ),
    )


def _canonical_name(evidence: tuple[SceneEvidence, ...]) -> str:
    normalized = Counter(
        _normalized_name(name) for item in evidence for name in item.names if name.strip()
    )
    winner = min(normalized, key=lambda name: (-normalized[name], len(name), name))
    originals = sorted(
        name.strip()
        for item in evidence
        for name in item.names
        if _normalized_name(name) == winner
    )
    return originals[0]


def _place_type(name: str) -> str:
    normalized = _normalized_name(name)
    if _EXIT.search(normalized):
        return "station_exit"
    if "station" in normalized or "駅" in normalized:
        return "station"
    if "street" in normalized or "通り" in normalized or "街" in normalized:
        return "street"
    return "unknown"


def _verification(evidence: tuple[SceneEvidence, ...]) -> str:
    statuses = {item.provenance.status for item in evidence}
    if DataStatus.LIVE in statuses or DataStatus.CACHED in statuses:
        return "verified"
    if DataStatus.COMMUNITY in statuses:
        return "community"
    return "unverified"


def _cluster_place(
    cluster: tuple[SceneEvidence, ...],
    decisions: dict[frozenset[UUID], _PairDecision],
) -> VisitPlace:
    ordered = tuple(sorted(cluster, key=lambda item: str(item.evidence_id)))
    medoid = _medoid(ordered)
    assert medoid.coordinate is not None
    evidence_ids = tuple(item.evidence_id for item in ordered)
    place_id = uuid5(
        NAMESPACE_URL, "visit-place:" + ":".join(str(item) for item in evidence_ids)
    )
    by_subject: dict[str, list[UUID]] = defaultdict(list)
    for item in ordered:
        by_subject[item.subject_id].append(item.evidence_id)
    appearances = tuple(
        SubjectAppearance(subject_id=subject_id, evidence_ids=tuple(ids))
        for subject_id, ids in sorted(by_subject.items())
    )
    pair_decisions = [
        decisions[frozenset((left.evidence_id, right.evidence_id))]
        for index, left in enumerate(ordered)
        for right in ordered[index + 1 :]
    ]
    confidence = min(
        (max(item.similarity, 0.8 if item.action == "merge" else 0.0) for item in pair_decisions),
        default=1.0,
    )
    override_ids = tuple(
        sorted(
            {item.override_id for item in pair_decisions if item.override_id is not None},
            key=str,
        )
    )
    name = _canonical_name(ordered)
    return VisitPlace(
        place_id=place_id,
        canonical_name=name,
        coordinate=medoid.coordinate,
        place_type=_place_type(name),
        visitability="unknown",
        verification_status=_verification(ordered),
        scene_evidence_ids=evidence_ids,
        subject_appearances=appearances,
        merge_confidence=confidence,
        resolution_version=POLICY_VERSION,
        applied_override_ids=override_ids,
        provenance_label=" + ".join(sorted({item.provider for item in ordered})),
    )


def resolve_places(
    evidence: Iterable[SceneEvidence],
    *,
    overrides: tuple[PlaceResolutionOverride, ...] = (),
    radius_meters: float = 100.0,
) -> PlaceResolutionResult:
    """Resolve evidence with complete-link consistency and stable IDs/membership."""

    if radius_meters <= 0 or radius_meters > 1_000:
        raise ValueError("place resolution radius must be within (0, 1000] meters")
    ordered = tuple(sorted(evidence, key=lambda item: str(item.evidence_id)))
    ids = [item.evidence_id for item in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("scene evidence IDs must be unique")
    valid: list[SceneEvidence] = []
    quarantined: list[EvidenceQuarantine] = []
    normalized_evidence: list[SceneEvidence] = []
    for item in ordered:
        if item.coordinate is None:
            normalized_evidence.append(
                item.model_copy(
                    update={
                        "resolution_status": EvidenceResolutionStatus.QUARANTINED,
                        "quarantine_reason": "Coordinate is missing or invalid.",
                    }
                )
            )
            quarantined.append(
                EvidenceQuarantine(
                    evidence_id=item.evidence_id,
                    reason_code="invalid_coordinate",
                    detail="Coordinate is missing or invalid.",
                )
            )
        else:
            resolved = item.model_copy(
                update={"resolution_status": EvidenceResolutionStatus.RESOLVED}
            )
            valid.append(resolved)
            normalized_evidence.append(resolved)

    by_evidence_id = {item.evidence_id: item for item in valid}
    candidate_pairs = _spatial_candidate_pairs(tuple(valid), radius_meters)
    candidate_pairs.update(
        frozenset((left, right))
        for override in overrides
        for left in override.evidence_ids
        for right in override.evidence_ids
        if left != right and left in by_evidence_id and right in by_evidence_id
    )
    decisions: dict[frozenset[UUID], _PairDecision] = {}
    ambiguous: list[AmbiguousPlaceMerge] = []
    for pair in sorted(candidate_pairs, key=lambda item: tuple(sorted(map(str, item)))):
        first_id, second_id = sorted(pair, key=str)
        first = by_evidence_id[first_id]
        second = by_evidence_id[second_id]
        decision = _pair_decision(
            first, second, overrides, radius_meters=radius_meters
        )
        decisions[pair] = decision
        if decision.action == "ambiguous":
            ambiguous.append(
                AmbiguousPlaceMerge(
                    evidence_ids=(first.evidence_id, second.evidence_id),
                    distance_meters=decision.distance_meters,
                    name_similarity=decision.similarity,
                    reason=(
                        "Close evidence has insufficient identity agreement; "
                        "review required."
                    ),
                )
            )

    def merges(first_id: UUID, second_id: UUID) -> bool:
        pair_decision = decisions.get(frozenset((first_id, second_id)))
        return pair_decision is not None and pair_decision.action == "merge"

    clusters: list[list[SceneEvidence]] = []
    for item in valid:
        compatible = [
            cluster
            for cluster in clusters
            if all(
                merges(item.evidence_id, member.evidence_id)
                for member in cluster
            )
        ]
        if compatible:
            min(compatible, key=lambda cluster: str(cluster[0].evidence_id)).append(item)
        else:
            clusters.append([item])
    places = tuple(
        sorted(
            (
                _cluster_place(tuple(cluster), decisions)
                for cluster in clusters
            ),
            key=lambda place: str(place.place_id),
        )
    )
    return PlaceResolutionResult(
        policy_version=POLICY_VERSION,
        evidence=tuple(normalized_evidence),
        places=places,
        quarantined=tuple(quarantined),
        ambiguous_merges=tuple(
            sorted(ambiguous, key=lambda item: tuple(map(str, item.evidence_ids)))
        ),
        overrides=overrides,
    )
