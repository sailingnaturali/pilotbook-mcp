"""8-point compass helpers. Bearings are meteorological 'from' degrees."""

from __future__ import annotations

SECTORS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def bucket_direction(degrees: float) -> str:
    """Snap a 'from' bearing in degrees to the nearest 8-point sector."""
    idx = round((degrees % 360) / 45) % 8
    return SECTORS[idx]


def is_exposed(exposed_sectors: list[str], wind_from: str) -> bool:
    """True when wind_from (a sector) is one of the anchorage's exposed sectors."""
    return wind_from in set(exposed_sectors)
