import json

from pilotbook_mcp.ingest import cli
from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.vault import Vault


def test_run_ingest_writes_vault(tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF fake")
    vault = tmp_path / "vault"

    monkeypatch.setattr(cli.pdf, "extract_text", lambda p: "48°21.50'N 123°42.68'W\nTest Cove. Exposed to SW.")
    monkeypatch.setattr(cli.pdf, "is_scanned", lambda text, pages: False)
    monkeypatch.setattr(cli, "_page_count", lambda p: 1)
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


def test_run_index_writes_index_json(tmp_path):
    vault = tmp_path / "vault"
    from pilotbook_mcp.ingest.writer import write_anchorage
    write_anchorage(vault, Anchorage(name="A", source="X", lat=48.0, lon=-123.0, exposed_sectors=["N"]))
    cli.run_index(str(vault))
    idx = json.loads((vault / "index.json").read_text())
    assert idx[0]["name"] == "A"
    assert idx[0]["exposed_sectors"] == ["N"]
