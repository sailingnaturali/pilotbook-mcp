"""Evidence-quote confirmation for controlling_depth_m.

The LLM proposer (ingest/depth_propose.py) returns the verbatim prose phrase it read an
entrance/approach depth from; this module confirms that phrase is a real, depth-bearing
substring of the prose. The model cannot quote text that isn't there, so a hallucinated
depth cannot pass — while spelled-out numbers and parenthetical conversions, which a
digit-regex could not handle, confirm fine because we match the phrase, not the number.
"""

from __future__ import annotations

import re

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
    if not _UNIT_TOKEN.search(evidence):   # must contain a measurement token, not arbitrary text
        return False
    return _normalise(evidence) in _normalise(prose)
