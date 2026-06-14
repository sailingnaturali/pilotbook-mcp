"""assess_anchorage — composed anchoring verdict (protection x overnight wind).

One tool call: find nearby anchorages, fetch the overnight forecast (shared
marine-forecast lib), rank by protection vs the forecast wind (existing scorer),
and flag any overnight wind shift into an exposed sector. Swing/scope is a
deferred follow-on (idea-tide-corrected-scope-tool)."""
from __future__ import annotations

import logging

from marine_forecast import RateLimitedClient, fetch_forecast

from pilotbook_mcp import tools
from pilotbook_mcp.sectors import exposure_hits
from pilotbook_mcp.vault import Vault

logger = logging.getLogger(__name__)

_MAX_CANDIDATES = 5


def forecast_to_steps(hours) -> list[dict]:
    """Adapt MarineForecastHour series → rank_anchorages forecast steps.
    Skip hours with no wind direction/speed (can't score protection)."""
    steps: list[dict] = []
    for h in hours:
        if h.wind.dir_deg is None or h.wind.speed_kn is None:
            continue
        steps.append({
            "wind_from_deg": h.wind.dir_deg,
            "wind_kn": h.wind.speed_kn,
            "swell_from_deg": h.swell.dir_deg,
            "swell_m": h.swell.height_m,
        })
    return steps


def lee_shore_shift(exposed_sectors: list[str], hours) -> dict | None:
    """First forecast hour whose wind blows from an exposed sector → lee shore.
    Returns {"sector", "utc", "wind_kn"} or None (never for a fully enclosed
    anchorage with no exposed sectors).

    Fix 1: hours with null speed_kn are skipped — we never fire a flag with
    wind_kn: None, and a null-speed hour in an exposed direction is not a risk
    we can quantify."""
    if not exposed_sectors:
        return None
    for h in hours:
        if h.wind.dir_deg is None or h.wind.speed_kn is None:
            continue
        hit = exposure_hits(exposed_sectors, h.wind.dir_deg)
        if hit:
            return {"sector": "/".join(sorted(hit)),
                    "utc": h.utc.isoformat(),
                    "wind_kn": h.wind.speed_kn}
    return None


async def assess_anchorage(vault: Vault,
                           lat: float, lon: float, radius_nm: float = 10.0,
                           hours: int = 12) -> dict:
    """Composed verdict: protection-ranked nearby anchorages vs the overnight
    forecast, each with a lee-shore/wind-shift flag. One call.

    Fix 4: creates and owns its own RateLimitedClient, always aclose()d.
    Fix 2: graceful degradation when forecast is unavailable or all-null.
    Fix 3: consistent return shape across all paths."""
    near = tools.find_anchorages_near(vault, lat=lat, lon=lon, radius_nm=radius_nm)
    candidates = near.get("anchorages", [])[:_MAX_CANDIDATES]

    # Fix 3: no-candidates path includes forecast_hours key
    if not candidates:
        return {"anchorages": [],
                "forecast_hours": 0,
                "summary_display": f"No charted anchorages within {radius_nm:.0f} "
                                   "nautical miles."}

    # Fix 4: own the client lifecycle per call
    client = RateLimitedClient()
    try:
        # Fix 2: catch network errors from fetch_forecast
        try:
            forecast_hours = await fetch_forecast(client, lat, lon, hours_ahead=hours)
        except Exception as exc:
            logger.warning("forecast fetch failed: %s", exc)
            forecast_hours = None

        steps = forecast_to_steps(forecast_hours) if forecast_hours is not None else []

        # Fix 2: empty steps (all-null wind or fetch failure) → degraded result
        if not steps:
            n = len(candidates)
            return {
                "anchorages": [
                    {"name": c["name"],
                     "distance_nm": c.get("distance_nm"),
                     "exposed_sectors": c.get("exposed_sectors", [])}
                    for c in candidates
                ],
                "forecast_hours": 0,
                "summary_display": (
                    f"Overnight forecast unavailable — {n} anchorage"
                    f"{'s' if n != 1 else ''} within {radius_nm:.0f} "
                    "nautical miles, not ranked."
                ),
            }

        names = [c["name"] for c in candidates]
        ranked = tools.rank_anchorages_tool(vault, names=names, forecast=steps)["ranked"]
        sectors_by_name = {c["name"]: c.get("exposed_sectors", []) for c in candidates}
        for entry in ranked:
            entry["lee_shore_shift"] = lee_shore_shift(
                sectors_by_name.get(entry.get("name"), []), forecast_hours)

        # Fix 3: success path includes summary_display
        top = ranked[0]["name"] if ranked else "unknown"
        return {
            "anchorages": ranked,
            "forecast_hours": len(steps),
            "summary_display": f"Top pick: {top} ({len(steps)}-hour forecast).",
        }
    finally:
        await client.aclose()
