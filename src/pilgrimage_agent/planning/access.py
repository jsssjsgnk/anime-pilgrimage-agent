"""Deterministic access-option comparison."""

from __future__ import annotations

from pilgrimage_agent.domain.models import FlightOption
from pilgrimage_agent.domain.planning import AccessMode, AccessOption, AccessSelection


def flight_options_to_access(options: tuple[FlightOption, ...]) -> tuple[AccessOption, ...]:
    """Normalize already validated flight snapshots into comparable access candidates."""

    normalized: list[AccessOption] = []
    for option in options:
        if not option.segments:
            continue
        first, last = option.segments[0], option.segments[-1]
        normalized.append(
            AccessOption(
                option_id=option.option_id,
                mode=AccessMode.FLIGHT,
                origin=first.departure_airport,
                destination=last.arrival_airport,
                departure_at=first.departure_at,
                arrival_at=last.arrival_at,
                price=option.price,
                currency=option.currency,
                confirmation_url=option.confirmation_url,
                provenance=option.provenance,
            )
        )
    return tuple(normalized)


def select_access_options(
    *,
    inbound_options: tuple[AccessOption, ...],
    outbound_options: tuple[AccessOption, ...],
    max_total_price: int | None = None,
) -> AccessSelection:
    """Choose by known total price, then elapsed time, then stable identifier."""

    if not inbound_options or not outbound_options:
        raise ValueError("at least one inbound and outbound option is required")
    pairs: list[tuple[AccessOption, AccessOption]] = []
    for inbound in inbound_options:
        for outbound in outbound_options:
            known_prices = [price for price in (inbound.price, outbound.price) if price is not None]
            if max_total_price is not None and len(known_prices) == 2:
                if sum(known_prices) > max_total_price:
                    continue
            pairs.append((inbound, outbound))
    if not pairs:
        raise ValueError("no access option pair satisfies the price constraint")

    def rank(pair: tuple[AccessOption, AccessOption]) -> tuple[int, int, float, str, str]:
        inbound, outbound = pair
        prices = (inbound.price, outbound.price)
        unknown = sum(price is None for price in prices)
        total_price = sum(price or 0 for price in prices)
        duration = (
            (inbound.arrival_at - inbound.departure_at).total_seconds()
            + (outbound.arrival_at - outbound.departure_at).total_seconds()
        )
        return unknown, total_price, duration, inbound.option_id, outbound.option_id

    inbound, outbound = min(pairs, key=rank)
    chosen = {inbound.option_id, outbound.option_id}
    alternatives = tuple(
        option
        for option in (*inbound_options, *outbound_options)
        if option.option_id not in chosen
    )
    return AccessSelection(inbound=inbound, outbound=outbound, alternatives=alternatives)
