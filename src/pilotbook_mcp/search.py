"""Semantic anchorage search backed by vault-search (optional [search] extra)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

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


def _cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "pilotbook-mcp"


class AnchorageIndex:
    """Lazily builds and self-heals a cached vault-search index for one vault."""

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)
        self._embedder = None
        self._index = None
        self._fp: str | None = None

    def cache_path(self) -> Path:
        h = hashlib.sha1(str(self.vault_root.resolve()).encode()).hexdigest()[:16]
        return _cache_root() / f"{h}.db"

    def _fingerprint(self) -> str:
        parts = []
        for p in sorted(self.vault_root.glob(PILOT.glob)):
            st = p.stat()
            rel = p.relative_to(self.vault_root)
            parts.append(f"{rel}:{st.st_size}:{st.st_mtime_ns}")
        return hashlib.sha1("\n".join(parts).encode()).hexdigest()

    def _build(self, db: Path, fp: str) -> None:
        chunks = _vs.chunk_vault(self.vault_root, PILOT)
        _vs.build_index(db, chunks, self._embedder)
        db.with_suffix(".fp").write_text(fp)

    def ensure(self) -> None:
        fp = self._fingerprint()
        if self._index is not None and self._fp == fp:
            return                      # fresh in-process
        if self._embedder is None:
            self._embedder = _vs.Embedder()
        if self._index is not None:     # release any prior open index (no fd leak)
            self._index.close()
            self._index = None
        db = self.cache_path()
        try:
            db.parent.mkdir(parents=True, exist_ok=True)
        except OSError:                 # cache dir not writable -> temp db for the session
            db = Path(tempfile.gettempdir()) / db.name
        fp_file = db.with_suffix(".fp")
        fresh = (db.exists() and fp_file.exists()
                 and fp_file.read_text().strip() == fp)
        if not fresh:
            self._build(db, fp)
        try:
            index = _vs.Index.open(db)
            index.count()               # force-detect a corrupt/garbage db (opens lazily)
        except Exception:               # corrupt/unreadable -> rebuild once and reopen
            self._build(db, fp)
            index = _vs.Index.open(db)
        self._index = index
        self._fp = fp
