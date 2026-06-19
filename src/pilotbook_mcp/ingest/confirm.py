"""Deterministic confirmation of controlling_depth_m against the prose.

A pure validator: the LLM (record_anchorage or the backfill proposer) proposes a
controlling (entrance) depth, and this pass keeps it only if a figure in the prose
confirms it (within tolerance). Mismatches are dropped to None and audited. It never
*originates* a value — regex alone is not allowed to invent a keel-safety depth. (An
earlier version recorded a regex-only figure when the model left the field blank; that
was safe only while the patterns were precise/unambiguous, but the broadened real-idiom
patterns can match anchoring or tide figures, so origination was removed.)
"""

from __future__ import annotations

import re

from pilotbook_mcp.models import Anchorage

_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(metres?|meters?|fathoms?|feet|foot|ft|m)"  # longest-first so "metres" != "m"+"etres"
_DEPTH = rf"{_NUM}\s*{_UNIT}\b"
# Match shoaling/approach idioms that denote depth OF WATER on the way in. The LLM owns the
# entrance-vs-anchoring judgment (see depth_propose.py); these patterns only prove the
# proposed number is literally in the prose. Deliberately NOT matched: "bar dries X m"
# (X above datum — no water), and bare "depths of X" (would grab interior anchoring depths).
_PATTERNS = [
    re.compile(rf"drawing\s+{_DEPTH}\s+or\s+less", re.I),
    re.compile(rf"drawing\s+more\s+than\s+{_DEPTH}", re.I),
    re.compile(rf"(?:shallows?|shoals?|drops?|falls?)\s+to\s+{_DEPTH}", re.I),
    re.compile(rf"controlling\s+depth\s+(?:of\s+)?{_DEPTH}", re.I),
    re.compile(rf"bar\s+carries\s+{_DEPTH}", re.I),
    re.compile(rf"entrance[^.\n]{{0,30}}?(?:sill|bar|shoal|least\s+depth)\s+(?:of\s+)?{_DEPTH}", re.I),
]
_TOLERANCE_M = 0.08  # just enough to absorb fathom/foot conversion rounding (~0.07 m worst case)

_FACTOR = {
    "m": 1.0, "metre": 1.0, "metres": 1.0, "meter": 1.0, "meters": 1.0,
    "fathom": 1.8288, "fathoms": 1.8288,
    "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
}

# A measurement token: must NOT follow a letter (so "calm"/"draft"/"from" don't match),
# but MAY follow a digit so the no-space form "1.5m"/"3ft" is caught. Bare "m" included —
# it's the most common abbreviation ("1.5 m", "2m").
_UNIT_TOKEN = re.compile(r"(?<![a-z])(metres?|meters?|fathoms?|feet|foot|ft|m)\b", re.I)


def _normalise(text: str) -> str:
    """Collapse whitespace and casefold so a verbatim quote matches across wrapping/case."""
    return " ".join((text or "").split()).casefold()


def quote_confirms(prose: str, evidence: str) -> bool:
    """True if the LLM's evidence quote is a real, depth-bearing substring of the prose.

    Anti-hallucination: the model cannot quote text that isn't there. Robust to
    spelled-out numbers and parentheticals because it matches the phrase, not the digit.
    """
    if not evidence:
        return False
    if not _UNIT_TOKEN.search(evidence):   # must be a depth citation, not arbitrary text
        return False
    return _normalise(evidence) in _normalise(prose)


def find_controlling_depths(prose: str | None) -> list[float]:
    """Every approach/entrance depth figure the known idioms yield, converted to metres."""
    out: list[float] = []
    for pat in _PATTERNS:
        for m in pat.finditer(prose or ""):
            num, unit = m.groups()  # each pattern captures exactly (number, unit)
            factor = _FACTOR.get(unit.lower())
            if factor is not None:
                out.append(round(float(num) * factor, 2))
    return out


def confirm_controlling_depth(anchorage: Anchorage) -> str | None:
    """Validate the LLM-proposed anchorage.controlling_depth_m against the prose, in place.

    Pure validator — never originates a value. Mutates the anchorage rather than returning
    a new one: callers (ingest loop, backfill) only need the audit note back.
      - model proposed nothing  -> leave None, return None.
      - proposed + a prose figure confirms it (within tolerance) -> keep, return None.
      - proposed + no prose figure confirms it -> drop to None, return an audit note.
    """
    proposed = anchorage.controlling_depth_m
    if proposed is None:
        return None
    found = find_controlling_depths(anchorage.prose)
    if any(abs(proposed - f) <= _TOLERANCE_M for f in found):
        return None  # model and prose agree
    anchorage.controlling_depth_m = None
    return (f"{anchorage.name}: LLM proposed controlling_depth_m={proposed} m, "
            "not found in prose — dropped")
