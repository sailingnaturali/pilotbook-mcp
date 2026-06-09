# Semantic Anchorage Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `search_anchorages` semantic-search tool to pilotbook-mcp, backed by the vault-search hybrid-retrieval module pulled in via a public-repo git dependency under a `[search]` optional extra.

**Architecture:** A small upstream addition to vault-search (a `mode` param + top-level re-exports, released as a public tag), then a focused `pilotbook_mcp/search.py` module: a `PILOT` VaultProfile, an `AnchorageIndex` that lazily builds and self-heals a cached SQLite index keyed by a vault fingerprint, and a pure-semantic tool returning ranked anchorages with citations and full prose. The retriever mode (hybrid vs vector) is chosen by a measured eval.

**Tech Stack:** Python 3.11, uv, vault-search (fastembed ONNX + sqlite-vec/FTS5), mcp, pyyaml, pytest/pytest-asyncio.

**Two repos, sequenced:** Tasks 1–3 are in **vault-search** (`/Users/clarkbw/src/sailingnaturali/vault-search`). Tasks 4–9 are in **pilotbook-mcp** (`/Users/clarkbw/src/sailingnaturali/pilotbook-mcp`, branch `feat/semantic-anchorage-search`). Task 4 depends on the public tag from Task 3.

---

## File Structure

```
vault-search/                         (Tasks 1–3)
  src/vault_search/__init__.py        # add top-level re-exports
  src/vault_search/search.py          # add `mode` param to search()
  tests/test_search.py                # mode tests
  pyproject.toml                      # version bump 0.1.0 -> 0.2.0

pilotbook-mcp/                        (Tasks 4–9, branch feat/semantic-anchorage-search)
  pyproject.toml                      # [search] extra + [tool.uv.sources] git entry
  src/pilotbook_mcp/search.py         # PILOT profile, AnchorageIndex, mapping, soft-import
  src/pilotbook_mcp/server.py         # conditional tool listing + async routing
  tests/test_search.py                # profile/mapping/cache/search/soft-dep tests
  tests/test_server.py                # tool-list + dispatch routing (extend)
  golden/pilot.yaml                   # golden query set (real anchorage names)
  scripts/eval_search.py              # runs vault_search.eval.run_eval with PILOT
  README.md                           # usage + eval results
```

---

## Task 1: vault-search — top-level re-exports

**Repo:** vault-search. **Files:**
- Modify: `src/vault_search/__init__.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Create a branch**

Run: `cd /Users/clarkbw/src/sailingnaturali/vault-search && git checkout main && git pull && git checkout -b feat/search-mode`
Expected: switched to a new branch.

- [ ] **Step 2: Write the failing test** `tests/test_api.py`:

```python
def test_top_level_reexports():
    import vault_search as vs
    for name in ["VaultProfile", "Chunk", "SearchHit", "Embedder",
                 "Index", "build_index", "chunk_vault", "search"]:
        assert hasattr(vs, name), f"vault_search.{name} missing"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL (AttributeError: module 'vault_search' has no attribute 'VaultProfile')

- [ ] **Step 4: Add re-exports.** Replace `src/vault_search/__init__.py` with:

```python
"""vault-search: vault-agnostic local-first hybrid retrieval."""

from vault_search.chunk import chunk_vault
from vault_search.embed import Embedder
from vault_search.index import Index, build_index
from vault_search.models import Chunk, SearchHit, VaultProfile
from vault_search.search import search

__version__ = "0.1.0"

__all__ = [
    "VaultProfile", "Chunk", "SearchHit", "Embedder",
    "Index", "build_index", "chunk_vault", "search", "__version__",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v && uv run pytest -q`
Expected: PASS (new test passes; full suite still green — 24 passed)

- [ ] **Step 6: Commit**

```bash
git add src/vault_search/__init__.py tests/test_api.py
git commit -m "feat: top-level re-exports for a clean public API"
```

---

## Task 2: vault-search — `mode` param on `search()`

**Repo:** vault-search. **Files:**
- Modify: `src/vault_search/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Append failing tests** to `tests/test_search.py`:

```python
def test_search_mode_keyword_skips_vector(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    emb = Embedder()
    build_index(db, chunk_vault(VAULT, COLREGS), emb)
    idx = Index.open(db)
    # keyword mode must not call knn at all
    called = {"knn": 0}
    real_knn = idx.knn
    monkeypatch.setattr(idx, "knn", lambda *a, **k: (called.__setitem__("knn", called["knn"] + 1), real_knn(*a, **k))[1])
    hits = search(idx, emb, "sidelights sternlight", limit=3, mode="keyword")
    assert called["knn"] == 0
    assert hits and hits[0].retriever == "keyword"
    assert hits[0].chunk.metadata["number"] == "25"


def test_search_mode_vector_ranks_paraphrase(tmp_path):
    db = tmp_path / "v.db"
    emb = Embedder()
    build_index(db, chunk_vault(VAULT, COLREGS), emb)
    idx = Index.open(db)
    hits = search(idx, emb, "what shapes does a boat at anchor show", limit=3, mode="vector")
    assert hits and hits[0].retriever == "vector"
    assert hits[0].chunk.metadata["number"] == "30"


def test_search_unknown_mode_raises(tmp_path):
    db = tmp_path / "u.db"
    emb = Embedder()
    build_index(db, chunk_vault(VAULT, COLREGS), emb)
    idx = Index.open(db)
    import pytest
    with pytest.raises(ValueError):
        search(idx, emb, "anything", mode="bogus")
```

Note: `Index.open` takes only `db_path` (no embedder) — match the existing tests in this file.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_search.py -v`
Expected: FAIL (search() got an unexpected keyword argument 'mode')

- [ ] **Step 3: Add the `mode` param.** Replace the `search` function in `src/vault_search/search.py` with:

```python
def search(index: Index, embedder: Embedder, query: str, limit: int = 5,
           k: int = 60, pool: int = 20, mode: str = "hybrid") -> list[SearchHit]:
    """Hybrid search: BM25 + vector KNN, fused with Reciprocal Rank Fusion.

    k: RRF constant (higher = flatter rank weighting).
    pool: candidates pulled from each retriever before fusion (affects recall).
    mode: "hybrid" (both), "vector" (KNN only), or "keyword" (BM25 only).
    """
    if mode not in ("hybrid", "vector", "keyword"):
        raise ValueError(f"unknown mode: {mode}")
    rankings: list[list[int]] = []
    if mode in ("hybrid", "keyword"):
        rankings.append(index.bm25(query, n=pool))
    if mode in ("hybrid", "vector"):
        rankings.append(index.knn(embedder.encode([query])[0], n=pool))
    fused = rrf_fuse(rankings, k=k)
    return [SearchHit(chunk=index.get_chunk(rowid), score=score, retriever=mode)
            for rowid, score in fused[:limit]]
```

(Single-list `rrf_fuse` yields a clean `1/(k+rank)` score; `keyword` mode never embeds.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_search.py -v && uv run pytest -q`
Expected: PASS (3 new pass; full suite green)

- [ ] **Step 5: Commit**

```bash
git add src/vault_search/search.py tests/test_search.py
git commit -m "feat: mode param on search() (hybrid|vector|keyword)"
```

---

## Task 3: vault-search — release v0.2.0 and make repo public

**Repo:** vault-search. **Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Bump the version.** In `pyproject.toml` change `version = "0.1.0"` to `version = "0.2.0"`. Also update `__version__ = "0.1.0"` to `__version__ = "0.2.0"` in `src/vault_search/__init__.py`.

- [ ] **Step 2: Update the test that asserts the version.** In `tests/test_smoke.py`, change the assertion `assert vault_search.__version__ == "0.1.0"` to `== "0.2.0"`.

- [ ] **Step 3: Verify the suite**

Run: `uv run pytest -q`
Expected: PASS (all green)

- [ ] **Step 4: Commit and merge to main**

```bash
git add pyproject.toml src/vault_search/__init__.py tests/test_smoke.py
git commit -m "chore: bump to 0.2.0"
git checkout main
git merge --no-ff feat/search-mode -m "Merge: mode param + public API re-exports (v0.2.0)"
uv run pytest -q   # verify on merged result
git branch -d feat/search-mode
```

- [ ] **Step 5: Tag and push (push the tag the git source will pin)**

```bash
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

- [ ] **Step 6: Make the GitHub repo public** (user-approved during design — vault-search is MIT, no secrets)

```bash
gh repo edit sailingnaturali/vault-search --visibility public --accept-visibility-change-consequences
gh repo view sailingnaturali/vault-search --json visibility -q .visibility
```
Expected: `PUBLIC`

- [ ] **Step 7: Verify the tag installs from git with no auth**

Run: `cd /tmp && uv run --with "vault-search @ git+https://github.com/sailingnaturali/vault-search@v0.2.0" python -c "import vault_search; print(vault_search.__version__)"`
Expected: prints `0.2.0`. (This proves the public git dependency resolves cleanly — the exact mechanism pilotbook-mcp will use.)

---

## Task 4: pilotbook-mcp — add the `[search]` extra and git source

**Repo:** pilotbook-mcp (branch `feat/semantic-anchorage-search`). **Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Confirm the branch**

Run: `cd /Users/clarkbw/src/sailingnaturali/pilotbook-mcp && git branch --show-current`
Expected: `feat/semantic-anchorage-search`

- [ ] **Step 2: Add the optional extra.** In `pyproject.toml`, under `[project.optional-dependencies]` (which already has `ingest`), add a `search` extra:

```toml
[project.optional-dependencies]
ingest = [
    "anthropic>=0.40.0",
]
search = [
    "vault-search>=0.2",
]
```

- [ ] **Step 3: Add the git source.** Add a new top-level table to `pyproject.toml` (anywhere after `[build-system]`):

```toml
[tool.uv.sources]
vault-search = { git = "https://github.com/sailingnaturali/vault-search", tag = "v0.2.0" }
```

- [ ] **Step 4: Sync with the extra and verify the import resolves from git**

Run: `uv sync --extra search`
Then: `uv run python -c "import vault_search; print(vault_search.__version__)"`
Expected: prints `0.2.0`. If uv reports it cannot find the tag, confirm Task 3 pushed `v0.2.0` and the repo is public.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add [search] extra sourcing vault-search v0.2.0 from git"
```

---

## Task 5: pilotbook-mcp — PILOT profile and result mapping

**Repo:** pilotbook-mcp. **Files:**
- Create: `src/pilotbook_mcp/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing test** `tests/test_search.py`:

```python
from pathlib import Path

from pilotbook_mcp import search as S

VAULT = Path(__file__).parent / "fixtures" / "vault"


def test_pilot_profile_shape():
    assert S.PILOT.chunk_strategy == "whole_file"
    assert S.PILOT.glob == "anchorages/**/*.md"
    assert S.PILOT.citation == "{name} ({source}, p.{source_page})"


def test_as_float():
    assert S._as_float("49.366") == 49.366
    assert S._as_float(None) is None
    assert S._as_float("not-a-number") is None


def test_to_hit_maps_chunk():
    import vault_search as vs
    chunk = vs.Chunk.make(
        doc_path="anchorages/x.md", ordinal=0,
        text="Body prose.", embed_text="bc\n\nBody prose.",
        metadata={"name": "Test Cove", "region": "[[Test Region]]",
                  "lat": "48.51", "lon": "-123.40"},
        citation="Test Cove (TestPilot — Test Region 2025, p.23)")
    hit = vs.SearchHit(chunk=chunk, score=0.04, retriever="vector")
    out = S._to_hit(hit)
    assert out == {
        "name": "Test Cove", "region": "[[Test Region]]",
        "lat": 48.51, "lon": -123.40,
        "citation": "Test Cove (TestPilot — Test Region 2025, p.23)",
        "score": 0.04, "text": "Body prose.",
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_search.py -v`
Expected: FAIL (ModuleNotFoundError: pilotbook_mcp.search)

- [ ] **Step 3: Create `src/pilotbook_mcp/search.py`** with the soft import, profile, and mapping helpers:

```python
"""Semantic anchorage search backed by vault-search (optional [search] extra)."""

from __future__ import annotations

try:
    import vault_search as _vs
    HAS_SEARCH = True
except ImportError:  # the [search] extra isn't installed
    _vs = None
    HAS_SEARCH = False

INSTALL_HINT = "semantic search requires: pip install 'pilotbook-mcp[search]'"

# Retriever mode chosen by the eval in Task 9; defaults to hybrid until measured.
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_search.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/search.py tests/test_search.py
git commit -m "feat: PILOT profile and hit mapping for semantic search"
```

---

## Task 6: pilotbook-mcp — AnchorageIndex cache lifecycle

**Repo:** pilotbook-mcp. **Files:**
- Modify: `src/pilotbook_mcp/search.py`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Append failing tests** to `tests/test_search.py`:

```python
import shutil

import pytest


def _fixture_index(tmp_path, monkeypatch):
    # isolate the XDG cache so tests never touch the real ~/.cache
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    vault = tmp_path / "vault"
    shutil.copytree(VAULT, vault)
    return S.AnchorageIndex(vault), vault


def test_ensure_builds_cache(tmp_path, monkeypatch):
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    idx.ensure()
    assert idx.cache_path().exists()
    assert idx.cache_path().with_suffix(".fp").exists()


def test_ensure_self_heals_on_vault_change(tmp_path, monkeypatch):
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    idx.ensure()
    fp1 = idx.cache_path().with_suffix(".fp").read_text()
    # add a new anchorage -> fingerprint must change -> rebuild
    (vault / "anchorages" / "new-cove.md").write_text(
        "---\nname: New Cove\nregion: X\nsource: T 2025\nsource_page: 9\n"
        "lat: 48.7\nlon: -123.1\n---\nNew Cove is calm.\n", encoding="utf-8")
    idx2 = S.AnchorageIndex(vault)
    idx2.ensure()
    fp2 = idx2.cache_path().with_suffix(".fp").read_text()
    assert fp1 != fp2


def test_ensure_rebuilds_corrupt_db(tmp_path, monkeypatch):
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    idx.ensure()
    idx.cache_path().write_bytes(b"corrupt not-a-sqlite-db")
    idx2 = S.AnchorageIndex(vault)
    idx2.ensure()                      # must not raise
    assert idx2._index is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_search.py -k ensure -v`
Expected: FAIL (AttributeError: module/ class has no AnchorageIndex)

- [ ] **Step 3: Add the cache helpers and `AnchorageIndex`** to `src/pilotbook_mcp/search.py` (append after `_to_hit`; add `hashlib`, `os`, `pathlib.Path`, `tempfile` to the imports at the top):

```python
import hashlib
import os
import tempfile
from pathlib import Path


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
            self._index = _vs.Index.open(db)
        except Exception:               # corrupt/unreadable db -> rebuild once
            self._build(db, fp)
            self._index = _vs.Index.open(db)
        self._fp = fp
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_search.py -k ensure -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/search.py tests/test_search.py
git commit -m "feat: AnchorageIndex cached, self-healing index lifecycle"
```

---

## Task 7: pilotbook-mcp — search() payload and soft-dep behavior

**Repo:** pilotbook-mcp. **Files:**
- Modify: `src/pilotbook_mcp/search.py`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Append failing tests** to `tests/test_search.py`:

```python
def test_search_returns_payload(tmp_path, monkeypatch):
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    out = idx.search("anchorage exposed to southwest wind", limit=2)
    assert "hits" in out and out["hits"]
    top = out["hits"][0]
    assert top["name"] == "Test Cove"
    assert set(top) == {"name", "region", "lat", "lon", "citation", "score", "text"}
    assert top["lat"] == 48.51
    assert "good holding" in top["text"]
    assert top["citation"].startswith("Test Cove (")


def test_search_empty_query_returns_no_hits(tmp_path, monkeypatch):
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    out = idx.search("", limit=5)
    assert out == {"hits": []}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_search.py -k "payload or empty_query" -v`
Expected: FAIL (AnchorageIndex has no attribute 'search')

- [ ] **Step 3: Add the `search` method** to `AnchorageIndex` in `src/pilotbook_mcp/search.py`:

```python
    def search(self, query: str, limit: int = 5) -> dict:
        try:
            self.ensure()
        except Exception as exc:  # e.g. first-run model download fails offline
            return {"hits": [], "error":
                    f"semantic index unavailable ({exc}); the embedding model may "
                    "need a one-time online download."}
        hits = _vs.search(self._index, self._embedder, query,
                          limit=limit, mode=DEFAULT_MODE)
        return {"hits": [_to_hit(h) for h in hits]}
```

Note: an all-whitespace/empty query produces no BM25 tokens and (in hybrid/vector) a vector with no useful match; `vault_search.search` returns an empty list for it, so `{"hits": []}` falls out naturally (the `try` succeeds, no `error` key is added). The test confirms this contract.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_search.py -k "payload or empty_query" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add the soft-dep test** to `tests/test_search.py`:

```python
def test_dispatch_without_extra_returns_install_hint():
    # simulate the [search] extra being absent at the dispatch layer
    from pilotbook_mcp.server import dispatch
    out = dispatch(vault=None, name="search_anchorages",
                   args={"query": "anything"}, anchorage_index=None)
    assert "pilotbook-mcp[search]" in out["error"]
```

- [ ] **Step 6: Run to verify it fails**

Run: `uv run pytest tests/test_search.py -k install_hint -v`
Expected: FAIL (dispatch() got an unexpected keyword argument 'anchorage_index') — implemented in Task 8.

- [ ] **Step 7: Commit (test stays red until Task 8 wires dispatch)**

```bash
git add src/pilotbook_mcp/search.py tests/test_search.py
git commit -m "feat: AnchorageIndex.search() payload; add soft-dep dispatch test (red until wiring)"
```

---

## Task 8: pilotbook-mcp — wire the tool into the server

**Repo:** pilotbook-mcp. **Files:**
- Modify: `src/pilotbook_mcp/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing tests** to `tests/test_server.py`:

```python
from pilotbook_mcp.server import dispatch, tool_list


def test_tool_list_includes_search_when_available():
    names = {t.name for t in tool_list(has_search=True)}
    assert "search_anchorages" in names
    assert {"find_anchorages_near", "get_anchorage",
            "rank_anchorages", "list_sources"} <= names


def test_tool_list_excludes_search_when_unavailable():
    names = {t.name for t in tool_list(has_search=False)}
    assert "search_anchorages" not in names


def test_dispatch_routes_search_to_index():
    class FakeIndex:
        def search(self, query, limit=5):
            return {"hits": [{"name": "Stub", "query": query, "limit": limit}]}
    out = dispatch(vault=None, name="search_anchorages",
                   args={"query": "calm cove", "limit": 2},
                   anchorage_index=FakeIndex())
    assert out["hits"][0] == {"name": "Stub", "query": "calm cove", "limit": 2}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_server.py -k "tool_list or routes_search" -v`
Expected: FAIL (cannot import name 'tool_list'; dispatch has no anchorage_index param)

- [ ] **Step 3: Refactor `server.py`.** Make four changes:

(a) Add an import near the top, after `from pilotbook_mcp.vault import Vault`:

```python
from pilotbook_mcp import search as search_mod
```

(b) Add a `search_anchorages` branch to `dispatch`, and give it the new optional param. Replace the `dispatch` signature line and add the branch at the TOP of the function body:

```python
def dispatch(vault: Vault, name: str, args: dict, anchorage_index=None) -> dict:
    """Route a tool call to its implementation. Shared by the server and tests."""
    if name == "search_anchorages":
        if anchorage_index is None:
            return {"error": search_mod.INSTALL_HINT}
        return anchorage_index.search(args["query"], args.get("limit", 5))
    if name == "find_anchorages_near":
        ...
```

(c) Extract the tool list into a module-level pure function `tool_list(has_search)` and have `_list_tools` call it. Move the four existing `types.Tool(...)` definitions into it and append the search tool conditionally:

```python
def tool_list(has_search: bool) -> list[types.Tool]:
    tools_list = [
        types.Tool(
            name="find_anchorages_near",
            description="Anchorages within a radius of a position, nearest first, with exposure summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "radius_nm": {"type": "number", "description": "Search radius in nautical miles (default 10)."},
                },
                "required": ["lat", "lon"],
            },
        ),
        types.Tool(
            name="get_anchorage",
            description="Full record and verbatim pilot-book prose for one named anchorage.",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        types.Tool(
            name="rank_anchorages",
            description=(
                "Rank named anchorages by overnight comfort against a forecast. "
                "Fetch the forecast from weather-mcp and pass it as `forecast` "
                "(a list of steps with wind_from_deg, wind_kn, swell_from_deg, swell_m)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "names": {"type": "array", "items": {"type": "string"}},
                    "forecast": {"type": "array", "items": _FORECAST_STEP},
                },
                "required": ["names", "forecast"],
            },
        ),
        types.Tool(
            name="list_sources",
            description="The pilot books ingested into the vault.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
    if has_search:
        tools_list.append(
            types.Tool(
                name="search_anchorages",
                description=(
                    "Free-text semantic search over anchorage descriptions. Returns ranked "
                    "anchorages with citation and full pilot-book prose. Use for fuzzy needs "
                    "('quiet spot to wait out a southerly with a beach'); chain results into "
                    "get_anchorage / rank_anchorages for structured detail."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "description": "Max results (default 5)."},
                    },
                    "required": ["query"],
                },
            )
        )
    return tools_list
```

(d) Rewrite `build_server` so it builds the index when available and routes search through a thread (so the one-time embed never blocks the event loop):

```python
def build_server(vault: Vault) -> Server:
    server = Server("pilotbook-mcp")
    anchorage_index = (
        search_mod.AnchorageIndex(vault.root) if search_mod.HAS_SEARCH else None
    )

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return tool_list(has_search=anchorage_index is not None)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        args = arguments or {}
        if name == "search_anchorages":
            result = await asyncio.to_thread(dispatch, vault, name, args, anchorage_index)
        else:
            result = dispatch(vault, name, args)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server
```

- [ ] **Step 4: Run the server + search tests**

Run: `uv run pytest tests/test_server.py tests/test_search.py -v`
Expected: PASS — including `test_dispatch_without_extra_returns_install_hint` from Task 7 (now that `dispatch` takes `anchorage_index`).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all green)

- [ ] **Step 6: Commit**

```bash
git add src/pilotbook_mcp/server.py tests/test_server.py
git commit -m "feat: register and route the search_anchorages tool"
```

---

## Task 9: pilotbook-mcp — golden set, measured mode, README

**Repo:** pilotbook-mcp. **Files:**
- Create: `golden/pilot.yaml`
- Create: `scripts/eval_search.py`
- Modify: `src/pilotbook_mcp/search.py` (set `DEFAULT_MODE`)
- Modify: `README.md`

- [ ] **Step 1: Write the eval script** `scripts/eval_search.py`:

```python
"""Score keyword/vector/hybrid retrievers for the pilot vault.

Usage: uv run python scripts/eval_search.py <golden.yaml> <vault_dir>
"""

import sys
from pathlib import Path

from vault_search.eval import run_eval

from pilotbook_mcp.search import PILOT


def main() -> None:
    golden, vault = Path(sys.argv[1]), Path(sys.argv[2])
    db = Path("/tmp/pilot-eval.db")
    run_eval(golden, vault, PILOT, db)   # prints the comparison table


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Build the golden set.** Create `golden/pilot.yaml` with **15–20** natural-language queries, each mapping to the anchorage `name`(s) that should surface. **This is data work, not copy-paste:** open the real vault at `/Users/clarkbw/src/sailingnaturali/pilotbook-vault/anchorages/`, read enough anchorage files to choose queries whose answers you are confident about, and exercise *semantic* gaps (paraphrase, conditions, vibe) rather than exact name matches. `expect` matches each hit chunk's `metadata["name"]`. Seed examples confirmed from the vault (expand to 15–20):

```yaml
queries:
  - query: quiet cove to escape the crowds near Hot Springs Cove with a beach to land the dinghy
    expect: ["Tootoo Cove"]
  - query: anchorage open to southerly swell, uncomfortable in unsettled weather on the west coast
    expect: ["Tootoo Cove"]
```

To find more: `grep -rl "good holding" /Users/clarkbw/src/sailingnaturali/pilotbook-vault/anchorages | head`, read those files, and write a query describing each one's distinctive prose (protection, bottom, hazards, scenery) paired with its `name`. Aim for coverage across regions.

- [ ] **Step 3: Run the eval against the real vault**

Run: `uv run python scripts/eval_search.py golden/pilot.yaml /Users/clarkbw/src/sailingnaturali/pilotbook-vault`
Expected: a table of R@1/R@3/R@5/MRR for `keyword`, `vector`, `hybrid`. **Capture it.**

- [ ] **Step 4: Set `DEFAULT_MODE` from the measured result.** In `src/pilotbook_mcp/search.py`, set `DEFAULT_MODE` to the retriever with the highest MRR in Step 3 — `"vector"` if vector's MRR exceeds hybrid's, otherwise `"hybrid"`. Update the comment to cite the numbers, e.g.:

```python
# Retriever mode chosen by scripts/eval_search.py on the pilot vault (2026-06-08):
# vector MRR 0.x > hybrid 0.y -> vector. Re-run the eval if the vault changes materially.
DEFAULT_MODE = "vector"
```

- [ ] **Step 5: Verify the suite still passes with the chosen mode**

Run: `uv run pytest -q`
Expected: PASS (all green — the fixture search test asserts `name`, which holds under any mode for the 2-doc fixture)

- [ ] **Step 6: Write the README section.** Append a "Semantic search (`[search]` extra)" section to `README.md` covering: install (`uv sync --extra search` or `pip install 'pilotbook-mcp[search]'`), what `search_anchorages` does and when to use it vs the structured tools, the lazy self-healing cache (XDG, rebuilt on vault change), and a "Results (pilot vault)" subsection with the **actual** eval table from Step 3 and a one-line read (which mode won and why). Do not invent numbers.

- [ ] **Step 7: Commit**

```bash
git add golden/pilot.yaml scripts/eval_search.py src/pilotbook_mcp/search.py README.md
git commit -m "feat: pilot golden set, measured retriever mode, search docs"
```

---

## Notes for the implementer

- **Tasks 1–3 are in vault-search; Tasks 4–9 are in pilotbook-mcp.** Task 4's `uv sync --extra search` will fail until Task 3 has pushed the `v0.2.0` tag AND made the repo public — do them in order.
- **First `uv sync --extra search` and first `Embedder()` need network** (the fastembed ONNX model downloads to `~/.cache/fastembed`). After that, build and query are offline.
- **The XDG cache is isolated in tests** via `monkeypatch.setenv("XDG_CACHE_HOME", ...)` — tests never touch the real `~/.cache`. `*.db` index files are build artifacts; confirm pilotbook-mcp's `.gitignore` ignores them (add `*.db` if absent).
- **The golden set (Task 9 Step 2) requires reading the real private vault** to pick confident query→anchorage pairs; it cannot be written blind. The two seeds are confirmed; the rest is the implementer's data work.
- **`Index.open` takes only `db_path`** (no embedder) — a deliberate vault-search API after an earlier refactor.
```
