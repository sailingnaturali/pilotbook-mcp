import json

from pilotbook_mcp.ingest import cli
from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.vault import Vault


def test_run_ingest_writes_vault(tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF fake")
    vault = tmp_path / "vault"

    monkeypatch.setattr(cli.pdf, "extract_pages",
                        lambda p: ["48°21.50'N 123°42.68'W\nTest Cove. Exposed to SW."])
    monkeypatch.setattr(cli.pdf, "is_scanned", lambda text, pages: False)
    monkeypatch.setattr(cli, "_make_client", lambda: object())

    def fake_extract(chunk, source, *, client, model):
        return Anchorage(name="Test Cove", source=source, lat=48.36, lon=-123.71,
                         exposed_sectors=["SW"], confidence="high")
    monkeypatch.setattr(cli, "extract_record", fake_extract)

    cli.run_ingest(str(pdf), source="TestPilot — X 2025", vault=str(vault))

    v = Vault.load(vault)
    assert v.get("Test Cove").exposed_sectors == ["SW"]
    assert v.sources()[0]["retitled"] == "testpilot-x-2025.pdf"
    assert v.sources()[0]["pages"] == 1
    assert v.get("Test Cove").source_pdf == "../sources/testpilot-x-2025.pdf#page=1"


def test_run_ingest_skips_already_covered_pages(tmp_path, monkeypatch):
    pdf_file = tmp_path / "book.pdf"
    pdf_file.write_bytes(b"%PDF fake")
    vault = tmp_path / "vault"
    source = "TestPilot — X 2025"

    # Pre-seed page 1 as already ingested (with a source_pdf #page=1 link).
    from pilotbook_mcp.ingest.writer import write_anchorage
    write_anchorage(vault, Anchorage(name="Already Done", source=source, lat=48.0, lon=-123.0,
                                     exposed_sectors=["S"], confidence="high",
                                     source_pdf="../sources/testpilot-x-2025.pdf#page=1"))

    # Two candidate pages: page 1 (covered) and page 2 (new).
    monkeypatch.setattr(cli.pdf, "extract_pages",
                        lambda p: ["48°21.50'N P1", "48°22.00'N P2"])
    monkeypatch.setattr(cli.pdf, "is_scanned", lambda text, pages: False)
    monkeypatch.setattr(cli, "_make_client", lambda: object())

    calls = []
    def fake_extract(chunk, src, *, client, model):
        calls.append(chunk)
        return Anchorage(name="New Cove", source=src, lat=48.4, lon=-123.7,
                         exposed_sectors=["SW"], confidence="high")
    monkeypatch.setattr(cli, "extract_record", fake_extract)

    cli.run_ingest(str(pdf_file), source=source, vault=str(vault))

    # Page 1 was skipped (not re-extracted); only page 2 hit the model.
    assert len(calls) == 1 and "P2" in calls[0]
    v = Vault.load(vault)
    assert v.get("Already Done") is not None
    assert v.get("New Cove") is not None


def test_run_review_flags_low_confidence(tmp_path, capsys):
    vault = tmp_path / "vault"
    from pilotbook_mcp.ingest.writer import write_anchorage
    write_anchorage(vault, Anchorage(name="Good", source="X", lat=48.0, lon=-123.0,
                                     exposed_sectors=["SW"], confidence="high"))
    write_anchorage(vault, Anchorage(name="Shaky", source="X", lat=48.1, lon=-123.0,
                                     exposed_sectors=[], confidence="low"))
    cli.run_review(str(vault))
    out = capsys.readouterr().out
    assert "Shaky" in out
    assert "Good" not in out


def test_run_index_writes_index_json_and_md(tmp_path):
    vault = tmp_path / "vault"
    from pilotbook_mcp.ingest.writer import write_anchorage
    write_anchorage(vault, Anchorage(name="A", source="X", lat=48.0, lon=-123.0,
                                     exposed_sectors=["N"], region="[[Gulf Islands]]"))
    cli.run_index(str(vault))
    idx = json.loads((vault / "index.json").read_text())
    assert idx[0]["name"] == "A"
    assert idx[0]["exposed_sectors"] == ["N"]
    assert idx[0]["region"] == "Gulf Islands"
    assert idx[0]["path"] == "anchorages/x/a.md"
    index_md = (vault / "INDEX.md").read_text()
    assert "## Gulf Islands" in index_md
    assert "[A](anchorages/x/a.md)" in index_md
