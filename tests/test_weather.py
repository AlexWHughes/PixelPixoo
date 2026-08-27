"""Tests for pixelpixoo.screens.weather parsing and forecast helpers."""

from __future__ import annotations

from datetime import date, timedelta

from pixelpixoo.screens.weather import (
    DayForecast,
    _daily_rain_chance,
    _parse_payload,
    upcoming_forecast_days,
)

TODAY = date(2026, 8, 24)


def _sample_payload(*, mean: list[int | None], max_: list[int | None]) -> dict:
    return {
        "current": {"temperature_2m": 18.0, "weather_code": 0},
        "daily": {
            "time": ["2026-08-24", "2026-08-25", "2026-08-26"],
            "temperature_2m_max": [20.5, 19.2, 17.7],
            "temperature_2m_min": [11.9, 13.7, 14.3],
            "weather_code": [3, 53, 53],
            "precipitation_probability_mean": mean,
            "precipitation_probability_max": max_,
        },
    }


class TestDailyRainChance:
    def test_prefers_mean_over_max(self) -> None:
        assert _daily_rain_chance([44], [91], 0) == 44

    def test_falls_back_to_max(self) -> None:
        assert _daily_rain_chance([], [91], 0) == 91

    def test_missing_returns_none(self) -> None:
        assert _daily_rain_chance([], [], 0) is None


class TestParsePayload:
    def test_uses_mean_pop_for_forecast_days(self) -> None:
        data = _parse_payload(_sample_payload(mean=[0, 44, 31], max_=[0, 91, 84]))
        assert data.rain_chance == 0
        assert [d.rain_chance for d in data.forecast] == [0, 44, 31]

    def test_parses_dates_and_temps(self) -> None:
        data = _parse_payload(_sample_payload(mean=[0, 44, 31], max_=[0, 91, 84]))
        assert data.forecast[1].day == date(2026, 8, 25)
        assert data.forecast[1].high == 19.2
        assert data.forecast[1].weather_code == 53


class TestUpcomingForecastDays:
    def _days(self, n: int) -> list[DayForecast]:
        return [
            DayForecast(TODAY + timedelta(days=i), 20, 10, 3, 10)
            for i in range(n)
        ]

    def test_skips_today_when_showing_current(self) -> None:
        forecast = self._days(3)
        days = upcoming_forecast_days(forecast, TODAY, show_current=True)
        assert [d.day for d in days] == [TODAY + timedelta(days=1), TODAY + timedelta(days=2)]

    def test_includes_today_when_forecast_only(self) -> None:
        forecast = self._days(3)
        days = upcoming_forecast_days(forecast, TODAY, show_current=False)
        assert [d.day for d in days] == [TODAY, TODAY + timedelta(days=1), TODAY + timedelta(days=2)]
