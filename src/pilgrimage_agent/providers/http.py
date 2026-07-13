"""Credential-safe HTTP transport with bounded retries and normalized errors."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind


class SafeHttpClient:
    """Perform read-only JSON calls without logging request URLs or headers."""

    def __init__(
        self,
        *,
        provider: str,
        timeout_seconds: float,
        max_attempts: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self.provider = provider
        self.max_attempts = max_attempts
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )

    async def close(self) -> None:
        if self._owned_client:
            await self.client.aclose()

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        if method not in {"GET", "POST"}:
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                self.provider,
                "Only read-only GET and search POST requests are supported.",
            )
        last_error: ProviderError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await self.client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )
            except httpx.TimeoutException:
                last_error = ProviderError(
                    ProviderErrorKind.TIMEOUT,
                    self.provider,
                    "The upstream service timed out.",
                    retryable=True,
                )
            except httpx.HTTPError:
                raise ProviderError(
                    ProviderErrorKind.UPSTREAM,
                    self.provider,
                    "The upstream service could not be reached.",
                    retryable=False,
                ) from None
            else:
                if response.status_code in {401, 403}:
                    raise ProviderError(
                        ProviderErrorKind.AUTH,
                        self.provider,
                        "The upstream service rejected its configured credential.",
                    )
                if response.status_code == 404:
                    raise ProviderError(
                        ProviderErrorKind.NOT_FOUND,
                        self.provider,
                        "The requested resource was not found.",
                    )
                if response.status_code == 429:
                    last_error = ProviderError(
                        ProviderErrorKind.RATE_LIMIT,
                        self.provider,
                        "The upstream rate limit was reached.",
                        retryable=True,
                    )
                elif response.status_code >= 500:
                    last_error = ProviderError(
                        ProviderErrorKind.UPSTREAM,
                        self.provider,
                        "The upstream service returned a server error.",
                        retryable=True,
                    )
                elif response.status_code >= 400:
                    raise ProviderError(
                        ProviderErrorKind.VALIDATION,
                        self.provider,
                        "The upstream service rejected the normalized request.",
                    )
                else:
                    try:
                        return response.json()
                    except ValueError:
                        raise ProviderError(
                            ProviderErrorKind.UPSTREAM,
                            self.provider,
                            "The upstream service returned invalid JSON.",
                        ) from None
            if attempt < self.max_attempts:
                await asyncio.sleep(0.05 * attempt)
        assert last_error is not None
        raise last_error

