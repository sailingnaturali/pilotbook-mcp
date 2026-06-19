from pilotbook_mcp.clearance import keel_clearance


def test_clear_when_depth_exceeds_draft_plus_margin():
    v = keel_clearance(controlling_depth_m=4.0, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "clear"
    assert v["controlling_depth_m"] == 4.0
    assert v["draft_m"] == 1.37
    assert "chart datum" in v["note"]


def test_tight_within_margin():
    # 1.37 <= 1.8 < 1.37 + 0.5 (=1.87)
    v = keel_clearance(controlling_depth_m=1.8, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "tight"
    assert "chart datum" in v["note"]


def test_unsafe_when_depth_below_draft():
    v = keel_clearance(controlling_depth_m=1.0, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "unsafe_at_datum"
    assert "rising tide" in v["note"]


def test_unknown_when_depth_missing():
    v = keel_clearance(controlling_depth_m=None, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "unknown"
    assert v["controlling_depth_m"] is None
    assert "not recorded" in v["note"]


def test_boundary_exactly_at_draft_is_tight():
    v = keel_clearance(controlling_depth_m=1.37, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "tight"


def test_boundary_exactly_at_draft_plus_margin_is_clear():
    v = keel_clearance(controlling_depth_m=1.87, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "clear"
