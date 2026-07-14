"""Read-only Bangumi subject providers."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    DataProvenance,
    SubjectCandidate,
    SubjectSearchQuery,
    SubjectSearchResult,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.cache import MemoryProviderCache, request_fingerprint
from pilgrimage_agent.providers.common import provenance
from pilgrimage_agent.providers.http import SafeHttpClient

BANGUMI_BASE_URL = "https://api.bgm.tv"
BANGUMI_WEB_URL = "https://bgm.tv/subject"
_DICT = TypeAdapter(dict[str, Any])


def _aliases(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    aliases: list[str] = []
    for item in value:
        if not isinstance(item, dict) or item.get("key") not in {"别名", "Alias"}:
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        for alias in values:
            if isinstance(alias, str) and alias.strip():
                aliases.append(alias.strip())
            elif isinstance(alias, dict) and isinstance(alias.get("v"), str):
                aliases.append(alias["v"].strip())
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


class BangumiSubjectProvider:
    provider = "bangumi"

    def __init__(
        self,
        *,
        token: str | None,
        user_agent: str,
        http: SafeHttpClient,
    ) -> None:
        self.token = token
        self.user_agent = user_agent
        self.http = http
        self.cache: MemoryProviderCache[SubjectSearchResult] = MemoryProviderCache()

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def fetch(self, query: SubjectSearchQuery) -> SubjectSearchResult:
        fingerprint = request_fingerprint(self.provider, query)
        cached = self.cache.get(fingerprint)
        if cached is not None:
            return cached
        raw = await self.http.request_json(
            "POST",
            f"{BANGUMI_BASE_URL}/v0/search/subjects",
            headers=self._headers(),
            params={"limit": query.limit, "offset": 0},
            json_body={
                "keyword": query.query,
                "sort": "match",
                "filter": {"type": [2]},
            },
        )
        try:
            payload = _DICT.validate_python(raw)
            items = payload.get("data", [])
            if not isinstance(items, list):
                raise ValueError
            result_provenance = provenance(
                self.provider,
                "https://bangumi.github.io/api/#/条目/post_search_subjects",
                ttl=timedelta(hours=12),
            )
            candidates = tuple(
                self._candidate(item, result_provenance)
                for item in items[: query.limit]
                if isinstance(item, dict)
            )
            result = SubjectSearchResult(candidates=candidates, provenance=result_provenance)
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "Bangumi returned a response that did not match the expected schema.",
            ) from None
        self.cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(hours=12),
        )
        return result

    def _candidate(
        self, item: dict[str, Any], item_provenance: Any
    ) -> SubjectCandidate:
        subject_id = str(item["id"])
        images = item.get("images") if isinstance(item.get("images"), dict) else {}
        image = images.get("medium") if isinstance(images, dict) else None
        score = item.get("score")
        return SubjectCandidate(
            subject_id=subject_id,
            name=str(item["name"]),
            name_cn=str(item["name_cn"]) if item.get("name_cn") else None,
            aliases=_aliases(item.get("infobox")),
            image_url=image if isinstance(image, str) and image.startswith("http") else None,
            score=float(score) if isinstance(score, int | float) else None,
            provenance=DataProvenance.model_validate(
                {
                    **item_provenance.model_dump(),
                    "source_url": f"{BANGUMI_WEB_URL}/{subject_id}",
                }
            ),
        )

    async def get_subject(self, subject_id: str) -> ConfirmedSubject:
        if not subject_id or len(subject_id) > 50:
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                self.provider,
                "subject_id must contain between 1 and 50 characters.",
            )
        raw = await self.http.request_json(
            "GET",
            f"{BANGUMI_BASE_URL}/v0/subjects/{subject_id}",
            headers=self._headers(),
        )
        try:
            payload = _DICT.validate_python(raw)
            return ConfirmedSubject(
                subject_id=str(payload["id"]),
                name=str(payload["name"]),
                name_cn=str(payload["name_cn"]) if payload.get("name_cn") else None,
                aliases=_aliases(payload.get("infobox")),
                provenance=provenance(
                    self.provider,
                    f"{BANGUMI_WEB_URL}/{subject_id}",
                    ttl=timedelta(days=7),
                ),
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "Bangumi returned a response that did not match the expected schema.",
            ) from None


class FixtureBangumiSubjectProvider:
    provider = "bangumi-fixture"

    def __init__(self) -> None:
        prov = provenance(
            self.provider,
            "https://bgm.tv/subject/328609",
            ttl=timedelta(days=365),
        )
        self.subject = ConfirmedSubject(
            subject_id="328609",
            name="ぼっち・ざ・ろっく！",  # noqa: RUF001 - official title
            name_cn="孤独摇滚！",  # noqa: RUF001 - official title
            aliases=("Bocchi the Rock!",),
            provenance=prov,
        )
        lycoris_provenance = provenance(
            self.provider,
            "https://bgm.tv/subject/364450",
            ttl=timedelta(days=365),
        )
        self.subjects = {
            self.subject.subject_id: self.subject,
            "364450": ConfirmedSubject(
                subject_id="364450",
                name="Lycoris Recoil",
                name_cn="莉可丽丝",
                aliases=("Lycoris Recoil",),
                provenance=lycoris_provenance,
            ),
        }

    async def fetch(self, query: SubjectSearchQuery) -> SubjectSearchResult:
        candidates: tuple[SubjectCandidate, ...] = ()
        normalized = query.query.casefold()
        if any(term in normalized for term in ("孤独摇滚", "ぼっち", "bocchi")):
            candidates = (
                SubjectCandidate(
                    **self.subject.model_dump(exclude={"provenance"}),
                    score=8.5,
                    provenance=self.subject.provenance,
                ),
            )
        elif any(term in normalized for term in ("莉可丽丝", "lycoris")):
            subject = self.subjects["364450"]
            candidates = (
                SubjectCandidate(
                    **subject.model_dump(exclude={"provenance"}),
                    score=8.2,
                    provenance=subject.provenance,
                ),
            )
        return SubjectSearchResult(
            candidates=candidates[: query.limit],
            provenance=self.subject.provenance,
        )

    async def get_subject(self, subject_id: str) -> ConfirmedSubject:
        if subject_id not in self.subjects:
            raise ProviderError(
                ProviderErrorKind.NOT_FOUND,
                self.provider,
                "The fixture subject was not found.",
            )
        return self.subjects[subject_id]
