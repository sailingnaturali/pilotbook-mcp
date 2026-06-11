import pytest

from pilotbook_mcp.sectors import SECTORS, bucket_direction, is_exposed


def test_sectors_are_eight_point():
    assert SECTORS == ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@pytest.mark.parametrize(
    "deg,expected",
    [
        (0, "N"), (360, "N"), (22, "N"), (23, "NE"), (45, "NE"),
        (90, "E"), (135, "SE"), (180, "S"), (225, "SW"),
        (270, "W"), (315, "NW"), (350, "N"),
    ],
)
def test_bucket_direction(deg, expected):
    assert bucket_direction(deg) == expected


def test_is_exposed_true_when_wind_from_an_exposed_sector():
    assert is_exposed(["SW"], "SW") is True


def test_is_exposed_false_when_protected():
    assert is_exposed(["SW"], "NE") is False


def test_is_exposed_empty_sectors_is_never_exposed():
    assert is_exposed([], "SW") is False


def test_bucket_boundaries_round_half_up_consistently():
    from pilotbook_mcp.sectors import bucket_direction
    # banker's rounding made 22.5 -> N but 67.5 -> E; boundaries now half-up
    assert bucket_direction(22.5) == "NE"
    assert bucket_direction(67.5) == "E"


def test_exposure_hits_near_boundary_widens_to_adjacent_sector():
    from pilotbook_mcp.sectors import exposure_hits
    # 030° is ~30° off due north — it physically enters an N-open anchorage
    # even though it buckets to NE.
    assert exposure_hits(["N"], 30.0) == {"N"}
    assert exposure_hits(["NE"], 30.0) == {"NE"}
    assert exposure_hits(["E"], 30.0) == set()      # 60° away — not a hit
    assert exposure_hits(["N", "NE"], 30.0) == {"N", "NE"}
    assert exposure_hits(["NW"], 350.0) == {"NW"}   # wraparound
