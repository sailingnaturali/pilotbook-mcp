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
