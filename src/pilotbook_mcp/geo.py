"""Great-circle distance in nautical miles and a radius filter."""

from __future__ import annotations

import math

from pilotbook_mcp.models import Anchorage

_EARTH_NM = 3440.065  # mean earth radius in nautical miles


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return _EARTH_NM * 2 * math.asin(math.sqrt(a))


def within_radius(
    anchorages: list[Anchorage], lat: float, lon: float, radius_nm: float
) -> list[tuple[Anchorage, float]]:
    """Anchorages within radius_nm of (lat, lon), sorted nearest-first."""
    out: list[tuple[Anchorage, float]] = []
    for a in anchorages:
        d = haversine_nm(lat, lon, a.lat, a.lon)
        if d <= radius_nm:
            out.append((a, d))
    out.sort(key=lambda pair: pair[1])
    return out
