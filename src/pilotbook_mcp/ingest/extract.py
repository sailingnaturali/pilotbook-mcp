"""Claude-API extraction of a structured Anchorage from a pilot-book text chunk."""

from __future__ import annotations

import json

from pilotbook_mcp.models import Anchorage

_SCHEMA_DOC = """\
You convert one pilot-book anchorage description into a single JSON object.
Return ONLY the JSON object, no prose around it. Fields:
  name (str), lat (float), lon (float), region (str|null),
  source_page (int|null), depth_min_m (float|null), depth_max_m (float|null),
  bottom (list of: mud|sand|rock|kelp|shell|gravel),
  holding (good|fair|poor|variable|null),
  exposed_sectors (list of 8-point compass the anchorage is OPEN TO, i.e. wind/swell
    FROM these directions makes it uncomfortable; e.g. "exposed to SW"->["SW"],
    "shelter in all but SE"->["SE"], "open to the southeast"->["SE"]),
  swing_room (ample|adequate|limited|tight|null),
  tidal_current (none|weak|moderate|strong|reversing|null),
  cell_coverage (good|spotty|none|null),
  crowding (low|moderate|high|null; reflect seasonal popularity noted in the text),
  hazards (list of short strings),
  last_updated (str|null, e.g. "2025-01"),
  confidence (high|medium|low — your confidence in exposed_sectors specifically),
  prose (the original description text, lightly cleaned, verbatim where possible).
Derive lat/lon from the coordinates in the chunk (decimal degrees; W and S negative).
"""


def build_system_prompt() -> list[dict]:
    """System blocks. The schema block is cached (identical across every chunk)."""
    return [{"type": "text", "text": _SCHEMA_DOC, "cache_control": {"type": "ephemeral"}}]


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def extract_record(chunk: str, source: str, *, client, model: str = "claude-sonnet-4-6") -> Anchorage:
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=build_system_prompt(),
        messages=[{"role": "user", "content": chunk}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = _extract_json(text)
    data["source"] = source  # provenance is injected, never trusted to the model
    known = set(Anchorage.__dataclass_fields__)
    return Anchorage(**{k: v for k, v in data.items() if k in known})
