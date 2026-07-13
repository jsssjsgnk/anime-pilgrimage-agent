"""User-entered, read-only intercity candidate provider."""

from __future__ import annotations

from pilgrimage_agent.domain.planning import AccessOption, ManualIntercityQuery


class ManualIntercityProvider:
    provider = "manual-intercity"

    def __init__(self, options: tuple[AccessOption, ...]) -> None:
        self.options = options

    async def fetch(self, query: ManualIntercityQuery) -> tuple[AccessOption, ...]:
        return tuple(
            option
            for option in self.options
            if option.origin.casefold() == query.origin.casefold()
            and option.destination.casefold() == query.destination.casefold()
            and option.departure_at >= query.earliest_departure
            and option.arrival_at <= query.latest_arrival
        )


class FixtureManualIntercityProvider(ManualIntercityProvider):
    provider = "manual-intercity-fixture"

