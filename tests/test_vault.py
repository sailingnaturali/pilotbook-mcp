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


def test_load_skips_malformed_file_keeps_rest(tmp_path, capsys):
    # One bad frontmatter must not blank all 673 anchorages at startup (R3).
    book = tmp_path / "anchorages" / "test-book"
    book.mkdir(parents=True)
    (book / "good.md").write_text(
        "---\nname: Good Cove\nsource: T\nlat: 48.5\nlon: -123.4\n---\nFine.\n",
        encoding="utf-8")
    (book / "bad.md").write_text("not even frontmatter", encoding="utf-8")
    v = Vault.load(tmp_path)
    assert [a.name for a in v.anchorages] == ["Good Cove"]
    assert "bad.md" in capsys.readouterr().err


def test_load_warns_on_duplicate_names(tmp_path, capsys):
    book = tmp_path / "anchorages" / "test-book"
    book.mkdir(parents=True)
    for fn in ("one.md", "two.md"):
        (book / fn).write_text(
            "---\nname: Same Cove\nsource: T\nlat: 48.5\nlon: -123.4\n---\nx\n",
            encoding="utf-8")
    v = Vault.load(tmp_path)
    assert len(v.anchorages) == 2
    assert "duplicate" in capsys.readouterr().err.lower()
    assert v.get("Same Cove") is not None      # O(1) dict lookup still works
