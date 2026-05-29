"""Split extracted pilot-book text into per-anchorage chunks on coordinate anchors."""

from __future__ import annotations

import re

# e.g. 48°21.50'N  — degrees, decimal minutes, hemisphere
COORD_RE = re.compile(r"\d{1,3}°\d{1,2}\.\d+[''][NSEW]")


def split_on_coordinates(text: str) -> list[str]:
    """Each chunk begins at a coordinate line and runs to just before the next one."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if COORD_RE.search(ln)]
    chunks: list[str] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunk = "\n".join(lines[start:end]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks
