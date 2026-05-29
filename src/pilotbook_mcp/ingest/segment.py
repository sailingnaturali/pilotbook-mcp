"""Page-based segmentation: keep pages that look like anchorage entries."""

from __future__ import annotations

import re

# e.g. 48°21.50'N — degrees, decimal minutes, hemisphere
COORD_RE = re.compile(r"\d{1,3}°\d{1,2}\.\d+[''][NSEW]")
# e.g. tB9::Oak-Bay-GI (Gulf Islands) or vA1::Lund-DS (Desolation) — the e-book's
# per-anchorage page marker. The leading prefix letter varies by book (t, v, …);
# what's constant is <section-letter><number>:: . Cover/TOC markers like
# `t::Gulf-Islands-cover-GI` have no section+number and are correctly excluded.
MARKER_RE = re.compile(r"[a-z]+[A-Z]+\d+::")


def candidate_pages(pages: list[str]) -> list[tuple[int, str]]:
    """(1-based PDF page number, text) for pages likely to describe an anchorage."""
    return [(i + 1, p) for i, p in enumerate(pages)
            if COORD_RE.search(p) or MARKER_RE.search(p)]
