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


def test_run_review_empty_vault_warns_with_path(tmp_path, capsys):
    vault = tmp_path / "empty-vault"
    vault.mkdir()
    cli.run_review(str(vault))
    out = capsys.readouterr().out
    assert "No anchorages found" in out
    assert "empty-vault" in out  # resolved path is shown


def test_run_review_triages_undetermined_vs_protected_vs_low_confidence(tmp_path, capsys):
    from pilotbook_mcp.ingest.writer import write_anchorage
    vault = tmp_path / "vault"
    # empty + low → undetermined (flag)
    write_anchorage(vault, Anchorage(name="Undetermined", source="X", lat=48.0, lon=-123.0,
                                     exposed_sectors=[], confidence="low"))
    # empty + high → confirmed fully protected (NOT flagged)
    write_anchorage(vault, Anchorage(name="Confirmed Protected", source="X", lat=48.05, lon=-123.0,
                                     exposed_sectors=[], confidence="high"))
    # has sectors + low → low confidence (flag)
    write_anchorage(vault, Anchorage(name="Soft Call", source="X", lat=48.1, lon=-123.0,
                                     exposed_sectors=["SW"], confidence="low"))
    # has sectors + high → solid (not flagged)
    write_anchorage(vault, Anchorage(name="Solid", source="X", lat=48.2, lon=-123.0,
                                     exposed_sectors=["SW"], confidence="high"))
    cli.run_review(str(vault))
    out = capsys.readouterr().out
    assert "undetermined exposure" in out and "Undetermined" in out
    assert "low/medium confidence" in out and "Soft Call" in out
    assert "Confirmed Protected" not in out  # empty + high = confirmed protected
    assert "Solid" not in out


def test_run_audit_writes_worklist_for_flagged_records(tmp_path, monkeypatch, capsys):
    from pilotbook_mcp.ingest.writer import write_anchorage
    vault = tmp_path / "vault"
    source = "TestPilot — X 2025"
    write_anchorage(vault, Anchorage(name="Bad Sectors", source=source, lat=48.0, lon=-123.0,
                                     exposed_sectors=["W"], prose="Protection from west winds."))
    write_anchorage(vault, Anchorage(name="Fine", source=source, lat=48.1, lon=-123.0,
                                     exposed_sectors=["S"], prose="Open to southerly winds."))
    monkeypatch.setattr(cli, "_make_client", lambda: object())

    def fake_audit(a, *, client, model):
        if a.name == "Bad Sectors":   # current [W] vs prose-derived exposed_to [] -> flagged in code
            return {"protected_from": ["W"], "exposed_to": [], "evidence": "",
                    "audit_confidence": "high"}
        return {"protected_from": [], "exposed_to": ["S"], "evidence": "open to southerly winds",
                "audit_confidence": "high"}   # current [S] == exposed_to [S] -> agrees
    monkeypatch.setattr(cli, "audit_record", fake_audit)

    cli.run_audit(source, vault=str(vault))
    worklist = (vault / "audits" / "testpilot-x-2025.audit.md")
    assert worklist.exists()
    text = worklist.read_text()
    assert "1 flagged" in text
    assert "Bad Sectors" in text
    assert "Fine" not in text  # agreed records aren't listed


def test_run_index_empty_vault_warns_and_writes_nothing(tmp_path, capsys):
    vault = tmp_path / "empty-vault"
    vault.mkdir()
    cli.run_index(str(vault))
    out = capsys.readouterr().out
    assert "No anchorages found" in out
    assert not (vault / "index.json").exists()
    assert not (vault / "INDEX.md").exists()


def test_run_ingest_force_reprocesses_covered_pages(tmp_path, monkeypatch):
    pdf_file = tmp_path / "book.pdf"
    pdf_file.write_bytes(b"%PDF fake")
    vault = tmp_path / "vault"
    source = "TestPilot — X 2025"

    from pilotbook_mcp.ingest.writer import write_anchorage
    write_anchorage(vault, Anchorage(name="Old", source=source, lat=48.0, lon=-123.0,
                                     exposed_sectors=["S"], confidence="high",
                                     source_pdf="../sources/testpilot-x-2025.pdf#page=1"))

    monkeypatch.setattr(cli.pdf, "extract_pages", lambda p: ["48°21.50'N P1"])
    monkeypatch.setattr(cli.pdf, "is_scanned", lambda text, pages: False)
    monkeypatch.setattr(cli, "_make_client", lambda: object())
    calls = []
    def fake_extract(chunk, src, *, client, model):
        calls.append(chunk)
        return Anchorage(name="Old", source=src, lat=48.0, lon=-123.0,
                         exposed_sectors=["S"], confidence="high")
    monkeypatch.setattr(cli, "extract_record", fake_extract)

    # force=True must re-extract page 1 even though it's already covered
    cli.run_ingest(str(pdf_file), source=source, vault=str(vault), force=True)
    assert len(calls) == 1


def test_run_ingest_force_clears_stale_records(tmp_path, monkeypatch):
    pdf_file = tmp_path / "book.pdf"
    pdf_file.write_bytes(b"%PDF fake")
    vault = tmp_path / "vault"
    source = "TestPilot — X 2025"

    # A stale record whose name the re-run will NOT reproduce — must be removed.
    from pilotbook_mcp.ingest.writer import write_anchorage
    write_anchorage(vault, Anchorage(name="Stale Name", source=source, lat=48.0, lon=-123.0,
                                     exposed_sectors=["S"], confidence="high",
                                     source_pdf="../sources/testpilot-x-2025.pdf#page=1"))

    monkeypatch.setattr(cli.pdf, "extract_pages", lambda p: ["48°21.50'N P1"])
    monkeypatch.setattr(cli.pdf, "is_scanned", lambda text, pages: False)
    monkeypatch.setattr(cli, "_make_client", lambda: object())
    monkeypatch.setattr(cli, "extract_record",
                        lambda chunk, src, *, client, model: Anchorage(
                            name="Fresh Name", source=src, lat=48.0, lon=-123.0,
                            exposed_sectors=["SW"], confidence="high"))

    cli.run_ingest(str(pdf_file), source=source, vault=str(vault), force=True)

    v = Vault.load(vault)
    assert v.get("Stale Name") is None      # cleared
    assert v.get("Fresh Name") is not None   # re-extracted


def test_run_ingest_skips_out_of_range_coordinates(tmp_path, monkeypatch):
    pdf_file = tmp_path / "book.pdf"
    pdf_file.write_bytes(b"%PDF fake")
    vault = tmp_path / "vault"
    monkeypatch.setattr(cli.pdf, "extract_pages", lambda p: ["48°21.50'N bad"])
    monkeypatch.setattr(cli.pdf, "is_scanned", lambda text, pages: False)
    monkeypatch.setattr(cli, "_make_client", lambda: object())
    monkeypatch.setattr(cli, "extract_record",
                        lambda chunk, src, *, client, model: Anchorage(
                            name="Bad Coord", source=src, lat=483.6, lon=-123.0,
                            exposed_sectors=["S"], confidence="high"))
    cli.run_ingest(str(pdf_file), source="TestPilot — X 2025", vault=str(vault))
    from pilotbook_mcp.vault import Vault
    assert Vault.load(vault).get("Bad Coord") is None  # rejected, not written


def test_run_ingest_writes_coordless_anchorage(tmp_path, monkeypatch):
    pdf_file = tmp_path / "book.pdf"
    pdf_file.write_bytes(b"%PDF fake")
    vault = tmp_path / "vault"
    monkeypatch.setattr(cli.pdf, "extract_pages", lambda p: ["wB2::Boughey-Bay-BA\nBoughey Bay."])
    monkeypatch.setattr(cli.pdf, "is_scanned", lambda text, pages: False)
    monkeypatch.setattr(cli, "_make_client", lambda: object())
    monkeypatch.setattr(cli, "extract_record",
                        lambda chunk, src, *, client, model: Anchorage(
                            name="Boughey Bay", source=src,  # no lat/lon
                            exposed_sectors=["N"], confidence="medium"))
    cli.run_ingest(str(pdf_file), source="TestPilot — X 2025", vault=str(vault))
    assert Vault.load(vault).get("Boughey Bay") is not None  # written despite no coords


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
