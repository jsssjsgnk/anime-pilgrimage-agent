from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind


def test_provider_error_is_normalized_and_value_safe() -> None:
    error = ProviderError(
        kind=ProviderErrorKind.RATE_LIMIT,
        provider="fixture",
        safe_message="request budget exhausted",
        retryable=True,
    )
    assert str(error) == "fixture: rate_limit: request budget exhausted"
    assert error.retryable is True


def test_provider_error_taxonomy_is_complete() -> None:
    assert {item.value for item in ProviderErrorKind} == {
        "validation",
        "auth",
        "quota",
        "rate_limit",
        "timeout",
        "upstream",
        "not_found",
        "partial_data",
    }

