import shutil
from pathlib import Path

import pytest

from pilotbook_mcp import search as S

VAULT = Path(__file__).parent / "fixtures" / "vault"


def test_pilot_profile_shape():
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    assert S.PILOT.chunk_strategy == "whole_file"
    assert S.PILOT.glob == "anchorages/**/*.md"
    assert S.PILOT.citation == "{name} ({source}, p.{source_page})"


def test_as_float():
    assert S._as_float("49.366") == 49.366
    assert S._as_float(None) is None
    assert S._as_float("not-a-number") is None


def test_to_hit_maps_chunk():
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
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


def _fixture_index(tmp_path, monkeypatch):
    # isolate the XDG cache so tests never touch the real ~/.cache
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    vault = tmp_path / "vault"
    shutil.copytree(VAULT, vault)
    return S.AnchorageIndex(vault), vault


def test_ensure_builds_cache(tmp_path, monkeypatch, model_available):
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    idx.ensure()
    assert idx.cache_path().exists()
    assert idx.cache_path().with_suffix(".fp").exists()


def test_ensure_self_heals_on_vault_change(tmp_path, monkeypatch, model_available):
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


def test_ensure_rebuilds_corrupt_db(tmp_path, monkeypatch, model_available):
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    idx.ensure()
    idx.cache_path().write_bytes(b"corrupt not-a-sqlite-db")
    idx2 = S.AnchorageIndex(vault)
    idx2.ensure()                       # must not raise
    assert idx2._index.count() >= 1     # real recovery: rebuilt index is queryable


def test_ensure_same_instance_rebuilds_after_change(tmp_path, monkeypatch, model_available):
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    idx.ensure()
    fp1 = idx._fp
    (vault / "anchorages" / "another.md").write_text(
        "---\nname: Another\nregion: X\nsource: T 2025\nsource_page: 3\n"
        "lat: 48.9\nlon: -123.2\n---\nAnother calm spot.\n", encoding="utf-8")
    idx.ensure()                        # same instance — must not short-circuit
    assert idx._fp != fp1               # fingerprint advanced -> it rebuilt
    assert idx._index.count() >= 3      # 2 fixtures + the new one


def test_search_returns_payload(tmp_path, monkeypatch, model_available):
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


def test_search_resets_index_on_failure(tmp_path, monkeypatch, model_available):
    idx, vault = _fixture_index(tmp_path, monkeypatch)
    idx.ensure()
    assert idx._index is not None

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(S._vs, "search", boom)

    out = idx.search("anything", limit=2)
    assert out["hits"] == []
    assert "search failed" in out["error"]
    assert idx._index is None and idx._fp is None   # reset -> next call recovers


def test_ensure_is_thread_safe(tmp_path, monkeypatch, model_available):
    # The server warms the index from a daemon thread at startup while a
    # search may arrive concurrently — both funnel through ensure().
    import threading
    idx, _ = _fixture_index(tmp_path, monkeypatch)
    builds = []
    orig_build = idx._build

    def counting_build(db, fp):
        builds.append(1)
        orig_build(db, fp)

    monkeypatch.setattr(idx, "_build", counting_build)
    threads = [threading.Thread(target=idx.ensure) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(builds) == 1          # built exactly once, no racing rebuilds
    assert idx.search("cove", limit=1)["hits"] is not None


def test_warm_never_raises(tmp_path, monkeypatch):
    # warm() runs unsupervised in a daemon thread — a broken vault must not
    # take the server down or print a traceback into the MCP stdio stream.
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    idx = S.AnchorageIndex(tmp_path / "does-not-exist")
    idx.warm()  # must not raise
