from __future__ import annotations

from datetime import datetime, timezone

import pytest
from marine_forecast.openmeteo import MarineForecastHour, WaveObs, WindObs

from pilotbook_mcp.assess import forecast_to_steps, lee_shore_shift


def _hour(h: int, wind_dir: int, wind_kn: float) -> MarineForecastHour:
    return MarineForecastHour(
        utc=datetime(2026, 6, 14, h, tzinfo=timezone.utc),
        wind=WindObs(speed_kn=wind_kn, dir_deg=wind_dir, gust_kn=wind_kn + 5),
        swell=WaveObs(height_m=0.5, dir_deg=wind_dir, period_s=6.0),
        wind_wave=WaveObs(height_m=None, dir_deg=None, period_s=None),
        combined_wave=WaveObs(height_m=0.5, dir_deg=wind_dir, period_s=6.0),
        pressure_hpa=1012.0,
    )


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
