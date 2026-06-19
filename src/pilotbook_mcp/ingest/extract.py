"""Claude-API extraction of a structured Anchorage from one cruising-guide page.

Uses Anthropic structured tool use: the model returns fields as a forced tool call,
so there is no free-text JSON to parse. The instructions block and the tool schema
are marked for prompt caching (identical across every page of a book).
"""

from __future__ import annotations

from pilotbook_mcp.models import Anchorage

_INSTRUCTIONS = """\
You are given the extracted text of ONE page of a cruising guide. It may include
scattered chartlet map labels (road names, "RESTAURANT", depth soundings) — ignore them.

If the page describes a single anchorage, call `record_anchorage` with its fields.
If the page does NOT describe an anchorage (cover, index, region introduction, or a
chartlet with no anchorage text), call `record_anchorage` with is_anchorage=false.

For `exposed_sectors`, list the 8-point compass directions the anchorage is OPEN TO —
i.e. wind or swell FROM those directions makes it uncomfortable. Examples:
"exposed to SW" -> ["SW"]; "open to the southeast" -> ["SE"]; "good shelter in all
but SE winds" -> ["SE"]. Derive lat/lon from the page coordinates (decimal degrees;
W and S are negative). Record `controlling_depth_m` (in METRES) ONLY when the page states
a least depth on the approach or entrance (a bar, sill, or shoal the boat must cross) —
e.g. "drawing 1.8 m or less", "controlling depth 2 m", "the bar carries 1.5 m". Convert
feet or fathoms to metres. Do not populate it from anchoring-depth prose. Set `confidence`
to your confidence in exposed_sectors.
Put the original anchorage description (lightly cleaned) in `prose`.
Also record shore-side facilities when the page or its chartlet shows them (icons or
labels like fuel/gas, pumpout, water, garbage, power with amps, restaurant, pub,
store, laundry, ATM, WiFi, showers, marina, customs). Set the structured fields
(shore_power, pumpout, potable_water, garbage) and list the rest in `facilities`.
Omit anything not indicated — most wild anchorages have no facilities.
"""

_8POINT = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

ANCHORAGE_TOOL = {
    "name": "record_anchorage",
    "description": "Record one anchorage's structured fields from the page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_anchorage": {"type": "boolean",
                             "description": "false if the page describes no anchorage"},
            "name": {"type": "string"},
            "lat": {"type": "number"},
            "lon": {"type": "number"},
            "region": {"type": "string"},
            "source_page": {"type": "integer"},
            "depth_min_m": {"type": "number"},
            "depth_max_m": {"type": "number"},
            "controlling_depth_m": {"type": "number",
                "description": "Charted LEAST depth in METRES on the approach/entrance (bar, "
                               "sill, shoal) the vessel must cross to enter — NOT the "
                               "anchoring depth. Omit if the page states no entrance/approach "
                               "depth."},
            "bottom": {"type": "array",
                       "items": {"type": "string",
                                 "enum": ["mud", "sand", "rock", "kelp", "shell", "gravel"]}},
            "holding": {"type": "string", "enum": ["good", "fair", "poor", "variable"]},
            "exposed_sectors": {"type": "array", "items": {"type": "string", "enum": _8POINT}},
            "swing_room": {"type": "string", "enum": ["ample", "adequate", "limited", "tight"]},
            "tidal_current": {"type": "string",
                              "enum": ["none", "weak", "moderate", "strong", "reversing"]},
            "cell_coverage": {"type": "string", "enum": ["good", "spotty", "none"]},
            "crowding": {"type": "string", "enum": ["low", "moderate", "high"]},
            "shore_power": {"type": "string",
                            "description": "shore power amperage if mentioned, e.g. '30A' or '20/30/50A'"},
            "pumpout": {"type": "boolean", "description": "blackwater pumpout available"},
            "potable_water": {"type": "boolean", "description": "fresh water available at a dock"},
            "garbage": {"type": "boolean", "description": "garbage drop-off accepted"},
            "facilities": {"type": "array", "items": {"type": "string",
                "enum": ["fuel", "restaurant", "pub", "general store", "deli", "liquor",
                         "laundry", "ATM", "wifi", "showers", "marina", "customs"]},
                "description": "shore-side amenities present at or adjacent to the anchorage"},
            "hazards": {"type": "array", "items": {"type": "string"}},
            "last_updated": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "prose": {"type": "string"},
        },
        "required": ["is_anchorage"],
    },
    "cache_control": {"type": "ephemeral"},
}


def build_system_prompt() -> list[dict]:
    """System blocks (cached — identical across every page). Mentions exposed_sectors."""
    return [{"type": "text", "text": _INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}]


def extract_record(chunk: str, source: str, *, client, model: str = "claude-sonnet-4-6") -> Anchorage | None:
    """Extract one page into an Anchorage, or None if the page has no anchorage.

    Never raises on model-output shape — returns None if no usable tool call came back.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=build_system_prompt(),
        tools=[ANCHORAGE_TOOL],
        tool_choice={"type": "tool", "name": "record_anchorage"},
        messages=[{"role": "user", "content": chunk}],
    )
    data = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "record_anchorage":
            data = dict(block.input)
            break
    if not data or data.get("is_anchorage") is False or "name" not in data:
        return None
    data.pop("is_anchorage", None)
    data["source"] = source  # provenance is injected, never trusted to the model
    known = set(Anchorage.__dataclass_fields__) - {"source_pdf"}  # set deterministically by the CLI, never by the model
    return Anchorage(**{k: v for k, v in data.items() if k in known})
