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
