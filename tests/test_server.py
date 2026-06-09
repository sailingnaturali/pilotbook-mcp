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


from pilotbook_mcp.server import dispatch, tool_list


def test_tool_list_includes_search_when_available():
    names = {t.name for t in tool_list(has_search=True)}
    assert "search_anchorages" in names
    assert {"find_anchorages_near", "get_anchorage",
            "rank_anchorages", "list_sources"} <= names


def test_tool_list_excludes_search_when_unavailable():
    names = {t.name for t in tool_list(has_search=False)}
    assert "search_anchorages" not in names


def test_dispatch_routes_search_to_index():
    class FakeIndex:
        def search(self, query, limit=5):
            return {"hits": [{"name": "Stub", "query": query, "limit": limit}]}
    out = dispatch(vault=None, name="search_anchorages",
                   args={"query": "calm cove", "limit": 2},
                   anchorage_index=FakeIndex())
    assert out["hits"][0] == {"name": "Stub", "query": "calm cove", "limit": 2}


def test_dispatch_without_extra_returns_install_hint():
    out = dispatch(vault=None, name="search_anchorages",
                   args={"query": "anything"}, anchorage_index=None)
    assert "pilotbook-mcp[search]" in out["error"]
