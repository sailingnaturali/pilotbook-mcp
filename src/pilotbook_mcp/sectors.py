"""8-point compass helpers. Bearings are meteorological 'from' degrees."""

from __future__ import annotations

SECTORS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# A bearing "hits" an exposed sector when within this of the sector center.
# 45° (a full sector width, i.e. widened to the adjacent bucket) rather than
# the 22.5° half-width: a 030° wind physically enters an N-open anchorage even
# though it buckets to NE — fail toward caution for a spoken comfort ranking.
_HIT_TOLERANCE_DEG = 45.0


def bucket_direction(degrees: float) -> str:
    """Snap a 'from' bearing in degrees to the nearest 8-point sector
    (boundaries round half-up: 22.5 -> NE, 67.5 -> E)."""
    idx = int(((degrees % 360) + 22.5) // 45) % 8
    return SECTORS[idx]


def _angular_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def exposure_hits(exposed_sectors: list[str], degrees: float) -> set[str]:
    """The exposed sectors a 'from' bearing actually threatens."""
    bearing = degrees % 360
    hits: set[str] = set()
    for sector in exposed_sectors:
        if sector not in SECTORS:
            continue
        center = SECTORS.index(sector) * 45.0
        if _angular_distance(bearing, center) <= _HIT_TOLERANCE_DEG:
            hits.add(sector)
    return hits


def is_exposed(exposed_sectors: list[str], wind_from: str) -> bool:
    """True when wind_from (a sector) is one of the anchorage's exposed sectors."""
    return wind_from in set(exposed_sectors)
