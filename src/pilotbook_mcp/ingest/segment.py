"""Page-based segmentation: keep pages that look like anchorage entries."""

from __future__ import annotations

import re

# e.g. 48°21.50'N — degrees, decimal minutes, hemisphere
COORD_RE = re.compile(r"\d{1,3}°\d{1,2}\.\d+[''][NSEW]")
# e.g. tB9::Oak-Bay-GI — the e-book's per-anchorage page marker
MARKER_RE = re.compile(r"t[A-Z]+\d+::")


def candidate_pages(pages: list[str]) -> list[tuple[int, str]]:
    """(1-based PDF page number, text) for pages likely to describe an anchorage."""
    return [(i + 1, p) for i, p in enumerate(pages)
            if COORD_RE.search(p) or MARKER_RE.search(p)]
