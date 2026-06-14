from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from marine_forecast.openmeteo import MarineForecastHour, WaveObs, WindObs

from pilotbook_mcp.assess import assess_anchorage, forecast_to_steps, lee_shore_shift
from pilotbook_mcp.vault import Vault

FIXTURE = Path(__file__).parent / "fixtures" / "vault"


def _hour(h: int, wind_dir: int, wind_kn: float) -> MarineForecastHour:
    return MarineForecastHour(
        utc=datetime(2026, 6, 14, h, tzinfo=timezone.utc),
        wind=WindObs(speed_kn=wind_kn, dir_deg=wind_dir, gust_kn=wind_kn + 5),
        swell=WaveObs(height_m=0.5, dir_deg=wind_dir, period_s=6.0),
        wind_wave=WaveObs(height_m=None, dir_deg=None, period_s=None),
        combined_wave=WaveObs(height_m=0.5, dir_deg=wind_dir, period_s=6.0),
        pressure_hpa=1012.0,
    )


def _null_wind_hour(h: int) -> MarineForecastHour:
    """Hour with no wind data at all (dir and speed both None)."""
    return MarineForecastHour(
        utc=datetime(2026, 6, 14, h, tzinfo=timezone.utc),
        wind=WindObs(speed_kn=None, dir_deg=None, gust_kn=None),
        swell=WaveObs(height_m=None, dir_deg=None, period_s=None),
        wind_wave=WaveObs(height_m=None, dir_deg=None, period_s=None),
        combined_wave=WaveObs(height_m=None, dir_deg=None, period_s=None),
        pressure_hpa=None,
    )


def _null_speed_hour(h: int, wind_dir: int) -> MarineForecastHour:
    """Hour with wind direction but null speed — the Fix 1 bug vector."""
    return MarineForecastHour(
        utc=datetime(2026, 6, 14, h, tzinfo=timezone.utc),
        wind=WindObs(speed_kn=None, dir_deg=wind_dir, gust_kn=None),
        swell=WaveObs(height_m=None, dir_deg=None, period_s=None),
        wind_wave=WaveObs(height_m=None, dir_deg=None, period_s=None),
        combined_wave=WaveObs(height_m=None, dir_deg=None, period_s=None),
        pressure_hpa=None,
    )


# ---------------------------------------------------------------------------
# forecast_to_steps
# ---------------------------------------------------------------------------

def test_forecast_to_steps_maps_fields_and_skips_none_wind():
    hours = [_hour(0, 180, 12.0),
             MarineForecastHour(utc=datetime(2026, 6, 14, 1, tzinfo=timezone.utc),
                                wind=WindObs(None, None, None),
                                swell=WaveObs(None, None, None),
                                wind_wave=WaveObs(None, None, None),
                                combined_wave=WaveObs(None, None, None),
                                pressure_hpa=None)]
    steps = forecast_to_steps(hours)
    assert steps == [{"wind_from_deg": 180, "wind_kn": 12.0,
                      "swell_from_deg": 180, "swell_m": 0.5}]


# ---------------------------------------------------------------------------
# lee_shore_shift — Fix 1: null speed_kn must not trigger the flag
# ---------------------------------------------------------------------------

def test_lee_shore_shift_flags_first_hour_wind_enters_exposed_sector():
    # Anchorage exposed to the South. Wind starts NW (safe), veers S at hour 2.
    hours = [_hour(0, 315, 10.0), _hour(1, 300, 12.0), _hour(2, 180, 18.0)]
    flag = lee_shore_shift(["S"], hours)
    assert flag is not None
    assert flag["sector"] == "S"
    assert flag["utc"] == "2026-06-14T02:00:00+00:00"


def test_lee_shore_shift_none_when_wind_never_in_sector():
    hours = [_hour(0, 315, 10.0), _hour(1, 300, 12.0)]
    assert lee_shore_shift(["S"], hours) is None


def test_lee_shore_shift_none_for_fully_enclosed():
    hours = [_hour(0, 180, 20.0)]
    assert lee_shore_shift([], hours) is None


def test_lee_shore_shift_null_speed_in_exposed_sector_does_not_trigger():
    """Fix 1: dir is in an exposed sector but speed_kn is None → skip the hour.
    If it's the only hour, the result must be None (not a flag with wind_kn: None)."""
    hours = [_null_speed_hour(0, wind_dir=180)]  # S sector, but no speed
    result = lee_shore_shift(["S"], hours)
    assert result is None


def test_lee_shore_shift_null_speed_skipped_then_real_hour_flags():
    """Null-speed hour in exposed sector is skipped; the next real hour still flags."""
    hours = [_null_speed_hour(0, wind_dir=180), _hour(1, 180, 15.0)]
    result = lee_shore_shift(["S"], hours)
    assert result is not None
    assert result["wind_kn"] == 15.0
    assert result["utc"] == "2026-06-14T01:00:00+00:00"


# ---------------------------------------------------------------------------
# assess_anchorage — Fix 2/3: graceful degradation + consistent shape
# ---------------------------------------------------------------------------

@pytest.fixture
def vault():
    return Vault.load(FIXTURE)


async def test_assess_anchorage_empty_steps_returns_degraded(vault):
    """Fix 2: when forecast_to_steps returns [] (all-null wind) we must NOT rank.
    Fix 3: degraded result has the same keys as the success path."""
    # _hour series with all-null wind so forecast_to_steps returns []
    null_hours = [_null_wind_hour(h) for h in range(3)]

    with patch("pilotbook_mcp.assess.fetch_forecast", new=AsyncMock(return_value=null_hours)):
        result = await assess_anchorage(vault, lat=48.51, lon=-123.40, radius_nm=20.0)

    assert "anchorages" in result
    assert "forecast_hours" in result
    assert "summary_display" in result
    assert result["forecast_hours"] == 0
    assert "not ranked" in result["summary_display"].lower() or \
           "unavailable" in result["summary_display"].lower()
    # Must not have ranked: none of the anchorages should have a score field
    # (they come from find_anchorages_near, not rank_anchorages)
    for a in result["anchorages"]:
        assert "score" not in a, "degraded path must not produce a comfort score"


async def test_assess_anchorage_forecast_exception_returns_degraded(vault):
    """Fix 2: network error in fetch_forecast → degraded result, not an exception."""
    with patch("pilotbook_mcp.assess.fetch_forecast",
               new=AsyncMock(side_effect=Exception("network error"))):
        result = await assess_anchorage(vault, lat=48.51, lon=-123.40, radius_nm=20.0)

    assert result["forecast_hours"] == 0
    assert "summary_display" in result
    assert "unavailable" in result["summary_display"].lower()


async def test_assess_anchorage_no_candidates_has_forecast_hours_key(vault):
    """Fix 3: no-candidates path must include forecast_hours key."""
    result = await assess_anchorage(vault, lat=0.0, lon=0.0, radius_nm=0.01)
    assert "forecast_hours" in result
    assert result["forecast_hours"] == 0
    assert "anchorages" in result
    assert "summary_display" in result


async def test_assess_anchorage_success_path_shape(vault):
    """Fix 3: success path returns all three keys including summary_display."""
    good_hours = [_hour(h, 315, 10.0) for h in range(3)]

    with patch("pilotbook_mcp.assess.fetch_forecast", new=AsyncMock(return_value=good_hours)):
        result = await assess_anchorage(vault, lat=48.51, lon=-123.40, radius_nm=20.0)

    assert "anchorages" in result
    assert "forecast_hours" in result
    assert "summary_display" in result
    assert result["forecast_hours"] == 3
    assert len(result["anchorages"]) > 0


# ---------------------------------------------------------------------------
# Fix 4: client lifecycle — assess_anchorage must create and close its own client
# ---------------------------------------------------------------------------

async def test_assess_anchorage_creates_and_closes_client(vault):
    """Fix 4: assess_anchorage must aclose() its own RateLimitedClient."""
    closed = []

    class FakeClient:
        async def aclose(self):
            closed.append(True)

    good_hours = [_hour(h, 315, 10.0) for h in range(2)]

    with patch("pilotbook_mcp.assess.RateLimitedClient", return_value=FakeClient()), \
         patch("pilotbook_mcp.assess.fetch_forecast", new=AsyncMock(return_value=good_hours)):
        await assess_anchorage(vault, lat=48.51, lon=-123.40, radius_nm=20.0)

    assert closed == [True], "RateLimitedClient.aclose() must be called exactly once"


async def test_assess_anchorage_closes_client_even_on_forecast_exception(vault):
    """Fix 4: client is closed even when fetch_forecast raises."""
    closed = []

    class FakeClient:
        async def aclose(self):
            closed.append(True)

    with patch("pilotbook_mcp.assess.RateLimitedClient", return_value=FakeClient()), \
         patch("pilotbook_mcp.assess.fetch_forecast",
               new=AsyncMock(side_effect=Exception("boom"))):
        await assess_anchorage(vault, lat=48.51, lon=-123.40, radius_nm=20.0)

    assert closed == [True], "Client must be closed even when forecast fetch raises"
