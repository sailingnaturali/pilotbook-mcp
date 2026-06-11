from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.scoring import rank_anchorages, score_anchorage


def _exposed_sw(holding="good", crowding="low"):
    return Anchorage(name="SWExposed", source="X", lat=48.5, lon=-123.4,
                     exposed_sectors=["SW"], holding=holding, crowding=crowding)


def _exposed_nw():
    return Anchorage(name="NWExposed", source="X", lat=48.6, lon=-123.4,
                     exposed_sectors=["NW"], holding="good", crowding="low")


def _sw_wind_step(kn=20.0):
    return {"time": "2026-05-28T22:00", "wind_from_deg": 225, "wind_kn": kn,
            "swell_from_deg": None, "swell_m": None}


def _sw_swell_step(m=1.0):
    return {"time": "2026-05-28T22:00", "wind_from_deg": 0, "wind_kn": 0.0,
            "swell_from_deg": 225, "swell_m": m}


def test_protected_anchorage_scores_zero():
    s = score_anchorage(_exposed_nw(), [_sw_wind_step()])
    assert s.score == 0.0


def test_exposed_wind_adds_penalty():
    s = score_anchorage(_exposed_sw(), [_sw_wind_step(kn=20.0)])
    assert s.wind_penalty == 20.0
    assert s.swell_penalty == 0.0
    assert s.score == 20.0


def test_poor_holding_amplifies_wind():
    good = score_anchorage(_exposed_sw(holding="good"), [_sw_wind_step(kn=20.0)])
    poor = score_anchorage(_exposed_sw(holding="poor"), [_sw_wind_step(kn=20.0)])
    assert poor.wind_penalty > good.wind_penalty
    assert poor.wind_penalty == 30.0  # 20 * 1.5


def test_swell_weighted_higher_than_equivalent_wind():
    # 1.0 m swell should outweigh 1 kn of wind by a lot
    swell = score_anchorage(_exposed_sw(), [_sw_swell_step(m=1.0)])
    assert swell.swell_penalty == 30.0  # 1.0 * 10 * 3
    assert swell.score == 30.0


def test_rank_orders_calmest_first_and_breaks_ties_by_crowding():
    calm = _exposed_nw()                       # not exposed to SW -> score 0, crowding low
    busy_calm = Anchorage(name="BusyCalm", source="X", lat=48.6, lon=-123.4,
                          exposed_sectors=["NW"], holding="good", crowding="high")
    rough = _exposed_sw()                       # exposed to SW -> penalised
    ranked = rank_anchorages([rough, busy_calm, calm], [_sw_wind_step(kn=15.0)])
    assert [r["name"] for r in ranked] == ["NWExposed", "BusyCalm", "SWExposed"]
    assert "SW" in ranked[-1]["reason"]
    assert ranked[0]["score"] == 0.0


def test_near_boundary_wind_penalizes_adjacent_exposed_sector():
    # 030° wind must penalize an N-exposed anchorage (old 8-point snap missed
    # anything more than 22.5° from the sector center).
    n_exposed = Anchorage(name="NExposed", source="X", lat=48.5, lon=-123.4,
                          exposed_sectors=["N"], holding="good", crowding="low")
    step = {"time": "t", "wind_from_deg": 30, "wind_kn": 20.0,
            "swell_from_deg": None, "swell_m": None}
    s = score_anchorage(n_exposed, [step])
    assert s.wind_penalty == 20.0
    assert "N" in s.reason


def test_rank_breaks_full_ties_by_name():
    a = Anchorage(name="Beta Bay", source="X", lat=48.5, lon=-123.4,
                  exposed_sectors=["SW"], holding="good", crowding="low")
    b = Anchorage(name="Alpha Cove", source="X", lat=48.6, lon=-123.4,
                  exposed_sectors=["SW"], holding="good", crowding="low")
    ranked = rank_anchorages([a, b], [_sw_wind_step(kn=10.0)])
    assert [r["name"] for r in ranked] == ["Alpha Cove", "Beta Bay"]
