from pathlib import Path

from pilotbook_mcp.ingest.writer import (
    archive_source,
    slugify,
    update_manifest,
    write_anchorage,
)
from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.vault import Vault


def test_slugify():
    assert slugify("SalishSeaPilot — Gulf Islands 2025") == "salishseapilot-gulf-islands-2025"
    assert slugify("Dreamspeaker: Vol. 1!") == "dreamspeaker-vol-1"


def test_archive_source_copies_and_retitles(tmp_path):
    src = tmp_path / "RawScan.pdf"
    src.write_bytes(b"%PDF-1.7 fake")
    vault = tmp_path / "vault"
    dest = archive_source(src, "SalishSeaPilot — Gulf Islands 2025", vault)
    assert dest == vault / "sources" / "salishseapilot-gulf-islands-2025.pdf"
    assert dest.read_bytes() == b"%PDF-1.7 fake"


def test_update_manifest_appends_entry(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    update_manifest(vault, {"retitled": "a.pdf", "original": "RawScan.pdf",
                            "sha256": "abc", "publisher": "X", "year": 2025,
                            "pages": 143, "ingested": "2026-05-28"})
    sources = Vault.load(vault).sources()
    assert sources[0]["retitled"] == "a.pdf"
    assert sources[0]["pages"] == 143


def test_update_manifest_dedupes_by_retitled(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    e1 = {"retitled": "a.pdf", "original": "RawV1.pdf", "pages": 100}
    e2 = {"retitled": "a.pdf", "original": "RawV2.pdf", "pages": 144}
    update_manifest(vault, e1)
    update_manifest(vault, e2)
    sources = Vault.load(vault).sources()
    assert len(sources) == 1
    assert sources[0]["original"] == "RawV2.pdf"
    assert sources[0]["pages"] == 144


def test_write_anchorage_creates_slugged_md(tmp_path):
    vault = tmp_path / "vault"
    a = Anchorage(name="Test Cove", source="X", lat=48.5, lon=-123.4, exposed_sectors=["SW"])
    path = write_anchorage(vault, a)
    assert path == vault / "anchorages" / "x" / "test-cove.md"
    reparsed = Anchorage.from_markdown(path.read_text(encoding="utf-8"))
    assert reparsed.name == "Test Cove"
    assert reparsed.exposed_sectors == ["SW"]


def test_duplicate_slug_from_different_page_disambiguates(tmp_path, capsys):
    from pilotbook_mcp.ingest.writer import write_anchorage
    from pilotbook_mcp.models import Anchorage
    a1 = Anchorage(name="Twin Cove", source="Book", lat=48.5, lon=-123.4,
                   source_pdf="book.pdf#page=10")
    a2 = Anchorage(name="Twin Cove", source="Book", lat=50.1, lon=-125.0,
                   source_pdf="book.pdf#page=42")
    p1 = write_anchorage(tmp_path, a1)
    p2 = write_anchorage(tmp_path, a2)
    assert p1 != p2
    assert p2.name == "twin-cove-p42.md"
    assert "duplicate slug" in capsys.readouterr().err
    assert p1.exists() and p2.exists()        # nothing clobbered


def test_same_page_reingest_overwrites_in_place(tmp_path):
    from pilotbook_mcp.ingest.writer import write_anchorage
    from pilotbook_mcp.models import Anchorage
    a = Anchorage(name="Twin Cove", source="Book", lat=48.5, lon=-123.4,
                  source_pdf="book.pdf#page=10")
    p1 = write_anchorage(tmp_path, a)
    p2 = write_anchorage(tmp_path, a)
    assert p1 == p2
