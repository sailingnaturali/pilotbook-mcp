"""Deterministic confirmation of controlling_depth_m against the prose.

The LLM extractor proposes a controlling (entrance) depth; this pass keeps it only if a
literal entrance-depth phrase in the prose agrees. Mismatches are dropped to None and
audited. A figure the regex finds when the LLM left it blank is recorded (most
trustworthy: text-sourced) and audited for review. Keel-safety values never survive on
the model's word alone.
"""

from __future__ import annotations

import re

from pilotbook_mcp.models import Anchorage

_DEPTH = r"(\d+(?:\.\d+)?)\s*(?:m|metres|meters)\b"
# Only phrasings that denote depth OF WATER on the approach. Deliberately omitted:
# "bar dries X m" — that means the bar dries X m ABOVE datum (i.e. no water at datum),
# the opposite of a controlling depth, so it must never be read as one. The `entrance`
# pattern requires a least-depth/sill/bar qualifier so it can't grab an anchoring depth
# that merely sits near the word "entrance".
_PATTERNS = [
    re.compile(rf"drawing\s+{_DEPTH}\s+or\s+less", re.I),
    re.compile(rf"controlling\s+depth\s+(?:of\s+)?{_DEPTH}", re.I),
    re.compile(rf"bar\s+carries\s+{_DEPTH}", re.I),
    re.compile(rf"entrance[^.\n]{{0,30}}?(?:sill|bar|shoal|least\s+depth)\s+(?:of\s+)?{_DEPTH}", re.I),
]
_TOLERANCE_M = 0.05


def find_controlling_depths(prose: str | None) -> list[float]:
    """Every entrance/approach depth figure the known phrasings yield, in metres."""
    out: list[float] = []
    for pat in _PATTERNS:
        for m in pat.finditer(prose or ""):
            out.append(float(m.group(1)))
    return out


def confirm_controlling_depth(anchorage: Anchorage) -> str | None:
    """Validate (and possibly correct) anchorage.controlling_depth_m in place.

    Mutates the anchorage rather than returning a new one: Task 9's ingest loop calls
    this per record just before writing, and only needs the audit note back. Returns an
    audit note string when human review is warranted, else None.
    """
    found = find_controlling_depths(anchorage.prose)
    proposed = anchorage.controlling_depth_m
    if proposed is not None:
        if any(abs(proposed - f) <= _TOLERANCE_M for f in found):
            return None  # model and prose agree
        anchorage.controlling_depth_m = None
        return (f"{anchorage.name}: LLM proposed controlling_depth_m={proposed} m, "
                "not found in prose — dropped")
    if found:
        shallowest = min(found)  # shallowest = binding gate
        anchorage.controlling_depth_m = shallowest
        return (f"{anchorage.name}: regex-sourced controlling_depth_m="
                f"{shallowest} m — review")
    return None
