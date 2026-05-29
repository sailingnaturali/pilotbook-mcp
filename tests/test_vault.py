from pathlib import Path

from pilotbook_mcp.vault import Vault

FIXTURE = Path(__file__).parent / "fixtures" / "vault"


def test_load_reads_all_anchorages():
    v = Vault.load(FIXTURE)
    names = sorted(a.name for a in v.anchorages)
    assert names == ["Telegraph Harbour", "Test Cove"]


def test_get_by_name_is_case_insensitive():
    v = Vault.load(FIXTURE)
    assert v.get("test cove").source_page == 23
    assert v.get("TELEGRAPH HARBOUR").exposed_sectors == ["NW"]


def test_get_missing_returns_none():
    v = Vault.load(FIXTURE)
    assert v.get("Nowhere Bay") is None


def test_sources_reads_manifest():
    v = Vault.load(FIXTURE)
    sources = v.sources()
    assert sources[0]["retitled"] == "testpilot-test-region-2025.pdf"
    assert sources[0]["pages"] == 2


def test_load_recurses_into_book_subfolders(tmp_path):
    book = tmp_path / "anchorages" / "somebook-2025"
    book.mkdir(parents=True)
    (book / "deep-cove.md").write_text(
        '---\nname: Deep Cove\nsource: "SomeBook 2025"\nlat: 49.0\nlon: -123.0\n---\nNested.\n',
        encoding="utf-8",
    )
    v = Vault.load(tmp_path)
    assert v.get("Deep Cove") is not None
