"""Deterministic overnight-comfort scoring for anchorages against a forecast."""

from __future__ import annotations

from dataclasses import dataclass

from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.sectors import exposure_hits

WIND_WEIGHT = 1.0
# Deliberate calibration: swell dominates wind for overnight comfort — 1 m of
# swell in an exposed sector (30 pts) outweighs 20 kn of wind. Uncapped on
# purpose: 2 m of swell SHOULD swamp everything else in the ranking.
SWELL_WEIGHT = 3.0
SWELL_SCALE = 10.0          # convert metres to a wind-knot-comparable scale
POOR_HOLDING_MULT = 1.5

_CROWDING_RANK = {"low": 0, "moderate": 1, "high": 2}


@dataclass
class Score:
    name: str
    score: float
    wind_penalty: float
    swell_penalty: float
    reason: str


def score_anchorage(anchorage: Anchorage, forecast: list[dict]) -> Score:
    wind_penalty = 0.0
    swell_penalty = 0.0
    hit_sectors: set[str] = set()

    for step in forecast:
        wind_hits = exposure_hits(anchorage.exposed_sectors, step["wind_from_deg"])
        if wind_hits:
            w = step["wind_kn"] * WIND_WEIGHT
            if anchorage.holding == "poor":
                w *= POOR_HOLDING_MULT
            wind_penalty += w
            hit_sectors.update(wind_hits)

        swell_deg = step.get("swell_from_deg")
        swell_m = step.get("swell_m")
        if swell_deg is not None and swell_m is not None:
            swell_hits = exposure_hits(anchorage.exposed_sectors, swell_deg)
            if swell_hits:
                swell_penalty += swell_m * SWELL_SCALE * SWELL_WEIGHT
                hit_sectors.update(swell_hits)

    score = round(wind_penalty + swell_penalty, 3)
    reason = _reason(anchorage, score, hit_sectors)
    return Score(anchorage.name, score, round(wind_penalty, 3), round(swell_penalty, 3), reason)


def _reason(anchorage: Anchorage, score: float, hit: set[str]) -> str:
    if score == 0.0:
        prot = "/".join(anchorage.exposed_sectors) or "all directions"
        return f"Calm — forecast wind/swell not in its exposed sector ({prot})."
    sectors = "/".join(sorted(hit))
    note = " Poor holding compounds drag risk." if anchorage.holding == "poor" else ""
    return f"Exposed {sectors}; forecast wind/swell from there → uncomfortable.{note}"


def rank_anchorages(anchorages: list[Anchorage], forecast: list[dict]) -> list[dict]:
    scored = [score_anchorage(a, forecast) for a in anchorages]
    by_name = {a.name: a for a in anchorages}

    def sort_key(s: Score):
        crowd = _CROWDING_RANK.get(by_name[s.name].crowding or "", 1)
        return (s.score, crowd, s.name)    # name last: input-order independent

    scored.sort(key=sort_key)
    return [
        {"name": s.name, "score": s.score, "wind_penalty": s.wind_penalty,
         "swell_penalty": s.swell_penalty, "reason": s.reason}
        for s in scored
    ]
