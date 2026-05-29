"""Pure-Python implementations of the four MCP tools. No I/O beyond the Vault."""

from __future__ import annotations

from pilotbook_mcp.geo import within_radius
from pilotbook_mcp.scoring import rank_anchorages
from pilotbook_mcp.vault import Vault


def find_anchorages_near(vault: Vault, lat: float, lon: float, radius_nm: float = 10.0) -> dict:
    hits = within_radius(vault.anchorages, lat, lon, radius_nm)
    return {
        "anchorages": [
            {
                "name": a.name,
                "distance_nm": round(dist, 2),
                "lat": a.lat,
                "lon": a.lon,
                "exposed_sectors": a.exposed_sectors,
                "holding": a.holding,
                "crowding": a.crowding,
            }
            for a, dist in hits
        ]
    }


def get_anchorage(vault: Vault, name: str) -> dict:
    a = vault.get(name)
    if a is None:
        return {"found": False, "name": name}
    record = {
        "name": a.name, "region": a.region, "source": a.source, "source_page": a.source_page,
        "lat": a.lat, "lon": a.lon, "depth_min_m": a.depth_min_m, "depth_max_m": a.depth_max_m,
        "bottom": a.bottom, "holding": a.holding, "exposed_sectors": a.exposed_sectors,
        "swing_room": a.swing_room, "tidal_current": a.tidal_current,
        "cell_coverage": a.cell_coverage, "crowding": a.crowding, "hazards": a.hazards,
        "last_updated": a.last_updated, "prose": a.prose,
    }
    return {"found": True, "anchorage": record}


def rank_anchorages_tool(vault: Vault, names: list[str], forecast: list[dict]) -> dict:
    found = []
    unknown = []
    for n in names:
        a = vault.get(n)
        (found if a is not None else unknown).append(a if a is not None else n)
    ranked = rank_anchorages(found, forecast) if found else []
    return {"ranked": ranked, "unknown": unknown}


def list_sources(vault: Vault) -> dict:
    return {"sources": vault.sources()}
