import pytest

from pilotbook_mcp.ingest import pdf


def test_extract_text_calls_pdftotext_layout(monkeypatch):
    calls = {}

    def fake_run(cmd, capture_output, text, check):
        calls["cmd"] = cmd
        class R:
            stdout = "Anchor over mud in 3-5 metres. Good holding."
        return R()

    monkeypatch.setattr(pdf.subprocess, "run", fake_run)
    out = pdf.extract_text("book.pdf")
    assert "Good holding" in out
    assert calls["cmd"][0] == "pdftotext"
    assert "-layout" in calls["cmd"]


def test_is_scanned_true_when_text_density_low():
    assert pdf.is_scanned("", pages=10) is True
    assert pdf.is_scanned("x" * 50, pages=10) is True


def test_is_scanned_false_with_real_text():
    assert pdf.is_scanned("y" * 5000, pages=10) is False


def test_extract_pages_splits_on_formfeed(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        class R:
            stdout = "page one\x0cpage two\x0cpage three"
        return R()
    monkeypatch.setattr(pdf.subprocess, "run", fake_run)
    pages = pdf.extract_pages("book.pdf")
    assert pages == ["page one", "page two", "page three"]


def test_extract_pages_drops_trailing_formfeed(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        class R:
            stdout = "page one\x0cpage two\x0c"  # trailing form-feed like real pdftotext
        return R()
    monkeypatch.setattr(pdf.subprocess, "run", fake_run)
    assert pdf.extract_pages("book.pdf") == ["page one", "page two"]
