"""Small bounded in-process cache for normalized provider results."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class CacheEntry[T]:
    provider: str
    request_fingerprint: str
    fetched_at: datetime
    expires_at: datetime
    schema_version: str
    value: T


def request_fingerprint(provider: str, query: BaseModel) -> str:
    """Hash only normalized query data; credentials are never part of cache keys."""

    payload = json.dumps(query.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{provider}:{payload}".encode()).hexdigest()


class MemoryProviderCache[T]:
    """Deterministic LRU-like cache with a hard item bound."""

    def __init__(self, *, max_items: int = 256) -> None:
        self._max_items = max_items
        self._items: OrderedDict[str, CacheEntry[T]] = OrderedDict()

    def get(self, fingerprint: str, *, now: datetime | None = None) -> T | None:
        current = now or datetime.now(UTC)
        entry = self._items.get(fingerprint)
        if entry is None:
            return None
        if entry.expires_at <= current:
            del self._items[fingerprint]
            return None
        self._items.move_to_end(fingerprint)
        return entry.value

    def put(
        self,
        *,
        provider: str,
        fingerprint: str,
        value: T,
        ttl: timedelta,
        now: datetime | None = None,
    ) -> CacheEntry[T]:
        fetched_at = now or datetime.now(UTC)
        entry = CacheEntry(
            provider=provider,
            request_fingerprint=fingerprint,
            fetched_at=fetched_at,
            expires_at=fetched_at + ttl,
            schema_version="1",
            value=value,
        )
        self._items[fingerprint] = entry
        self._items.move_to_end(fingerprint)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)
        return entry
