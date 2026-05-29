from pathlib import Path

from pilotbook_mcp.tools import (
    find_anchorages_near,
    get_anchorage,
    list_sources,
    rank_anchorages_tool,
)
from pilotbook_mcp.vault import Vault

FIXTURE = Path(__file__).parent / "fixtures" / "vault"


def _vault():
    return Vault.load(FIXTURE)


def test_find_anchorages_near_returns_sorted_summaries():
    out = find_anchorages_near(_vault(), lat=48.51, lon=-123.40, radius_nm=20)
    names = [a["name"] for a in out["anchorages"]]
    assert names[0] == "Test Cove"          # nearest
    assert "Telegraph Harbour" in names
    assert out["anchorages"][0]["exposed_sectors"] == ["SW"]
    assert "distance_nm" in out["anchorages"][0]


def test_find_anchorages_near_empty_when_out_of_range():
    out = find_anchorages_near(_vault(), lat=10.0, lon=10.0, radius_nm=5)
    assert out["anchorages"] == []


def test_get_anchorage_returns_full_record_and_prose():
    out = get_anchorage(_vault(), name="Test Cove")
    assert out["found"] is True
    assert out["anchorage"]["source"] == "TestPilot — Test Region 2025"
    assert "good holding" in out["anchorage"]["prose"]
    assert out["anchorage"]["confidence"] == "high"


def test_get_anchorage_missing():
    out = get_anchorage(_vault(), name="Nowhere")
    assert out["found"] is False


def test_rank_anchorages_tool_ranks_named_candidates():
    forecast = [{"time": "t", "wind_from_deg": 225, "wind_kn": 20.0,
                 "swell_from_deg": None, "swell_m": None}]
    out = rank_anchorages_tool(_vault(), names=["Test Cove", "Telegraph Harbour"], forecast=forecast)
    # Telegraph (NW-exposed) is calm in a SW wind; Test Cove (SW-exposed) is not.
    assert out["ranked"][0]["name"] == "Telegraph Harbour"
    assert out["ranked"][-1]["name"] == "Test Cove"


def test_rank_anchorages_tool_reports_unknown_names():
    out = rank_anchorages_tool(_vault(), names=["Ghost Bay"], forecast=[])
    assert out["unknown"] == ["Ghost Bay"]
    assert out["ranked"] == []


def test_list_sources():
    out = list_sources(_vault())
    assert out["sources"][0]["retitled"] == "testpilot-test-region-2025.pdf"
