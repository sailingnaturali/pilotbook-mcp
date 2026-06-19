from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.ingest.confirm import find_controlling_depths, confirm_controlling_depth


def test_finds_drawing_phrasing():
    assert find_controlling_depths("vessels drawing 1.8 metres or less can enter") == [1.8]


def test_finds_controlling_depth_phrasing():
    assert find_controlling_depths("the controlling depth of 2 m on the bar") == [2.0]


def test_finds_bar_carries_phrasing():
    assert find_controlling_depths("the bar carries 1.5 m at datum") == [1.5]


def test_llm_value_confirmed_by_prose_is_kept():
    a = Anchorage(name="X", source="S", controlling_depth_m=1.8,
                  prose="drawing 1.8 metres or less")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m == 1.8
    assert note is None


def test_llm_value_unconfirmed_is_dropped_and_audited():
    a = Anchorage(name="X", source="S", controlling_depth_m=3.0,
                  prose="a pretty cove with good holding")  # no entrance depth stated
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m is None
    assert note is not None and "not found" in note


def test_no_value_originated_when_model_proposes_nothing():
    # Pure validator: with no LLM proposal, confirm never invents a depth from regex,
    # even when the prose contains a matchable figure. Leaves it unknown (safe).
    a = Anchorage(name="X", source="S", controlling_depth_m=None,
                  prose="drawing 1.2 metres or less; entrance is shallow")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m is None
    assert note is None


def test_no_depth_anywhere_stays_none_no_note():
    a = Anchorage(name="X", source="S", controlling_depth_m=None,
                  prose="lovely spot, good holding")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m is None
    assert note is None


def test_find_returns_all_matched_figures():
    # find_controlling_depths surfaces every matched figure; the LLM (not the regex)
    # decides which is the entrance depth, and confirm validates the proposal against this set.
    assert find_controlling_depths("drawing 2.0 metres or less; the bar carries 1.4 m") == [2.0, 1.4]


def test_llm_value_disagreeing_with_prose_is_dropped():
    # LLM says 3.0 m but the prose explicitly states 2.0 m — outside tolerance -> drop.
    a = Anchorage(name="X", source="S", controlling_depth_m=3.0,
                  prose="drawing 2.0 metres or less")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m is None
    assert note is not None and "not found" in note


def test_bar_dries_is_not_read_as_depth():
    # "dries X m" = X m ABOVE datum (no water), the opposite of a controlling depth.
    assert find_controlling_depths("the bar dries 1.2 m at low water") == []


def test_feet_and_fathoms_now_convert_to_metres():
    # Unit conversion is intentional now (the author mixes units).
    assert find_controlling_depths("drawing 6 feet or less") == [1.83]
    assert find_controlling_depths("the bar carries 1 fathom") == [1.83]


def test_entrance_anchoring_depth_is_not_grabbed():
    # An anchoring depth merely sitting near "entrance" must not be read as controlling.
    assert find_controlling_depths("the entrance leads to depths of 8 m inside") == []
    # But an explicit entrance sill IS captured.
    assert find_controlling_depths("the entrance sill of 1.6 m bars deep keels") == [1.6]


def test_find_controlling_depths_handles_none():
    assert find_controlling_depths(None) == []


def test_finds_shallows_to_phrasing():
    assert find_controlling_depths("the entrance shallows to 1.1 metres at zero tide") == [1.1]


def test_finds_drops_to_fathoms_converted():
    # 0.2 fathoms * 1.8288 = 0.36576 -> 0.37
    assert find_controlling_depths("depths in the entrance drop to 0.2 fathoms at zero tide") == [0.37]


def test_finds_drawing_more_than_phrasing():
    assert find_controlling_depths("sailboats drawing more than 2 m should enter on a rising tide") == [2.0]


def test_finds_bar_carries_feet_converted():
    # 6 feet * 0.3048 = 1.8288 -> 1.83
    assert find_controlling_depths("the bar carries 6 feet") == [1.83]


def test_confirm_keeps_within_widened_tolerance():
    # LLM read "about one foot" as 0.3; prose figure is 0.2 fathoms (~0.37). 0.07 <= 0.08 -> keep.
    a = Anchorage(name="X", source="S", controlling_depth_m=0.3,
                  prose="depths in the entrance drop to 0.2 fathoms (about one foot) at zero tide")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m == 0.3
    assert note is None
