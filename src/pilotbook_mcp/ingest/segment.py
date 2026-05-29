"""Page-based segmentation: keep pages that look like anchorage entries."""

from __future__ import annotations

import re

# e.g. 48°21.50'N — degrees, decimal minutes, hemisphere
COORD_RE = re.compile(r"\d{1,3}°\d{1,2}\.\d+[''][NSEW]")
# e.g. tB9::Oak-Bay-GI — the e-book's per-anchorage page marker
MARKER_RE = re.compile(r"t[A-Z]+\d+::")


def candidate_pages(pages: list[str]) -> list[str]:
    """Pages likely to describe an anchorage: have a coordinate or an anchorage marker."""
    return [p for p in pages if COORD_RE.search(p) or MARKER_RE.search(p)]
