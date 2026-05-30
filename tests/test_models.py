from pilotbook_mcp.models import Anchorage


SAMPLE = """\
---
name: Test Cove
region: "[[Gulf Islands]]"
source: "TestPilot — Gulf Islands 2025"
source_page: 23
lat: 49.0123
lon: -123.8456
depth_min_m: 5
depth_max_m: 10
bottom: [mud]
holding: good
exposed_sectors: [SW]
swing_room: limited
tidal_current: weak
cell_coverage: good
crowding: moderate
hazards: ["kelp can spoil set"]
last_updated: 2025-01
confidence: high
---
Test Cove is exposed to SW winds but has good holding in 5-10 metres.

Nearby: [[Telegraph Harbour]]
"""


def test_from_markdown_parses_frontmatter_and_body():
    a = Anchorage.from_markdown(SAMPLE)
    assert a.name == "Test Cove"
    assert a.lat == 49.0123
    assert a.lon == -123.8456
    assert a.depth_min_m == 5
    assert a.bottom == ["mud"]
    assert a.holding == "good"
    assert a.exposed_sectors == ["SW"]
    assert a.crowding == "moderate"
    assert a.hazards == ["kelp can spoil set"]
    assert a.confidence == "high"
    assert "good holding in 5-10 metres" in a.prose
    assert "Nearby: [[Telegraph Harbour]]" in a.prose


def test_round_trip_is_stable():
    a = Anchorage.from_markdown(SAMPLE)
    reparsed = Anchorage.from_markdown(a.to_markdown())
    assert reparsed == a


def test_missing_optional_fields_default_safely():
    minimal = (
        "---\n"
        'name: Bare Bay\n'
        'source: "X"\n'
        "lat: 48.0\n"
        "lon: -123.0\n"
        "---\n"
        "Body.\n"
    )
    a = Anchorage.from_markdown(minimal)
    assert a.name == "Bare Bay"
    assert a.exposed_sectors == []
    assert a.bottom == []
    assert a.holding is None
    assert a.prose.strip() == "Body."


def test_source_pdf_round_trips():
    a = Anchorage(name="X", source="S", lat=1.0, lon=2.0,
                  source_pdf="../sources/s.pdf#page=5")
    reparsed = Anchorage.from_markdown(a.to_markdown())
    assert reparsed.source_pdf == "../sources/s.pdf#page=5"


def test_coordless_anchorage_round_trips():
    a = Anchorage(name="Boughey Bay", source="S")  # no lat/lon
    assert a.lat is None and a.lon is None
    r = Anchorage.from_markdown(a.to_markdown())
    assert r.name == "Boughey Bay"
    assert r.lat is None and r.lon is None


def test_facilities_fields_round_trip():
    a = Anchorage(name="Marina Cove", source="S", lat=1.0, lon=2.0,
                  shore_power="30A", pumpout=True, potable_water=True, garbage=True,
                  facilities=["fuel", "restaurant", "wifi"])
    r = Anchorage.from_markdown(a.to_markdown())
    assert r.shore_power == "30A"
    assert r.pumpout is True
    assert r.potable_water is True
    assert r.garbage is True
    assert r.facilities == ["fuel", "restaurant", "wifi"]
