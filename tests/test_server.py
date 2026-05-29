import os
from pathlib import Path

import pytest

from pilotbook_mcp.server import dispatch
from pilotbook_mcp.vault import Vault

FIXTURE = Path(__file__).parent / "fixtures" / "vault"


@pytest.fixture
def vault():
    return Vault.load(FIXTURE)


def test_dispatch_find(vault):
    out = dispatch(vault, "find_anchorages_near", {"lat": 48.51, "lon": -123.40, "radius_nm": 20})
    assert out["anchorages"][0]["name"] == "Test Cove"


def test_dispatch_get(vault):
    out = dispatch(vault, "get_anchorage", {"name": "Telegraph Harbour"})
    assert out["found"] is True


def test_dispatch_rank(vault):
    forecast = [{"time": "t", "wind_from_deg": 225, "wind_kn": 20.0,
                 "swell_from_deg": None, "swell_m": None}]
    out = dispatch(vault, "rank_anchorages", {"names": ["Test Cove", "Telegraph Harbour"],
                                              "forecast": forecast})
    assert out["ranked"][0]["name"] == "Telegraph Harbour"


def test_dispatch_list_sources(vault):
    out = dispatch(vault, "list_sources", {})
    assert out["sources"]


def test_dispatch_unknown_tool_raises(vault):
    with pytest.raises(ValueError):
        dispatch(vault, "nope", {})
