"""Semantic anchorage search backed by vault-search (optional [search] extra)."""

from __future__ import annotations

try:
    import vault_search as _vs
    HAS_SEARCH = True
except ImportError:  # the [search] extra isn't installed
    _vs = None
    HAS_SEARCH = False

INSTALL_HINT = "semantic search requires: pip install 'pilotbook-mcp[search]'"

# Retriever mode chosen by the eval in a later task; defaults to hybrid until measured.
DEFAULT_MODE = "hybrid"

if HAS_SEARCH:
    PILOT = _vs.VaultProfile(
        glob="anchorages/**/*.md",
        front_matter_fields=["name", "region", "source", "source_page",
                             "source_pdf", "lat", "lon"],
        chunk_strategy="whole_file",
        breadcrumb="{name} — {region}",
        citation="{name} ({source}, p.{source_page})",
    )
else:  # keep the symbol importable for tests/tooling even without the extra
    PILOT = None


def _as_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_hit(hit) -> dict:
    m = hit.chunk.metadata
    return {
        "name": m.get("name", ""),
        "region": m.get("region", ""),
        "lat": _as_float(m.get("lat")),
        "lon": _as_float(m.get("lon")),
        "citation": hit.chunk.citation,
        "score": hit.score,
        "text": hit.chunk.text,
    }
