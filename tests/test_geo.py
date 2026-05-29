from pilotbook_mcp.geo import haversine_nm, within_radius
from pilotbook_mcp.models import Anchorage


def _anchorage(name, lat, lon):
    return Anchorage(name=name, source="X", lat=lat, lon=lon)


def test_haversine_known_distance():
    # ~ 1 minute of latitude = 1 nautical mile
    d = haversine_nm(48.0, -123.0, 48.0 + 1 / 60, -123.0)
    assert abs(d - 1.0) < 0.02


def test_within_radius_filters_and_sorts_by_distance():
    here = (48.50, -123.40)
    anchorages = [
        _anchorage("Far", 49.50, -123.40),     # ~60 nm north
        _anchorage("Near", 48.51, -123.40),    # ~0.6 nm
        _anchorage("Mid", 48.60, -123.40),     # ~6 nm
    ]
    result = within_radius(anchorages, *here, radius_nm=10)
    names = [a.name for a, _dist in result]
    assert names == ["Near", "Mid"]
    assert result[0][1] < result[1][1]
