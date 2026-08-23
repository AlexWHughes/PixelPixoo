"""Tests for pixelpixoo.schedule."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from pixelpixoo.schedule import (
    ScheduleConfig,
    ScheduleWindow,
    _day_numbers,
    _parse_hhmm,
    is_schedule_active,
    parse_schedule,
    schedule_public_dict,
)

SYD = ZoneInfo("Australia/Sydney")


def _dt(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SYD)


class TestParseHhmm:
    def test_basic(self) -> None:
        assert _parse_hhmm("09:30") == time(9, 30)

    def test_hour_only(self) -> None:
        assert _parse_hhmm("22") == time(22, 0)

    @pytest.mark.parametrize("bad", ["", "abc", "25:00", "12:99", "-1:00"])
    def test_invalid_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            _parse_hhmm(bad)


class TestDayNumbers:
    def test_aliases(self) -> None:
        assert _day_numbers(["mon", "Wednesday"]) == [0, 2]

    def test_wildcards_return_every_day(self) -> None:
        assert _day_numbers(["all"]) == []
        assert _day_numbers(["*"]) == []

    def test_ints_are_kept_in_range(self) -> None:
        assert _day_numbers([0, 6, 9]) == [0, 6]

    def test_unknown_only_raises(self) -> None:
        with pytest.raises(ValueError):
            _day_numbers(["funday"])

    def test_partial_typos_keep_known_days(self) -> None:
        assert _day_numbers(["mon", "funday"]) == [0]

    def test_empty(self) -> None:
        assert _day_numbers(None) == []


class TestParseSchedule:
    def test_defaults(self) -> None:
        cfg = parse_schedule(None)
        assert cfg.enabled is False
        assert cfg.windows == []
        assert cfg.outside == "off"
        assert cfg.sun_pad_minutes == 20

    def test_windows_and_outside(self) -> None:
        cfg = parse_schedule(
            {
                "enabled": True,
                "windows": [
                    {"days": ["mon", "tue"], "start": "07:00", "end": "09:00"},
                    {"start": "", "end": ""},  # skipped
                    "not-a-dict",  # skipped
                ],
                "outside": "pause",
            }
        )
        assert len(cfg.windows) == 1
        assert cfg.windows[0].days == [0, 1]
        assert cfg.outside == "pause"

    def test_bad_outside_and_pad_clamped(self) -> None:
        cfg = parse_schedule({"outside": "nonsense", "sun_pad_minutes": 999})
        assert cfg.outside == "off"
        assert cfg.sun_pad_minutes == 180


class TestIsScheduleActive:
    def test_disabled_is_always_active(self) -> None:
        cfg = ScheduleConfig(enabled=False)
        assert is_schedule_active(cfg) is True

    def test_enabled_without_windows_is_active(self) -> None:
        cfg = ScheduleConfig(enabled=True)
        assert is_schedule_active(cfg) is True

    def test_inside_window(self) -> None:
        cfg = ScheduleConfig(
            enabled=True,
            timezone="Australia/Sydney",
            windows=[ScheduleWindow(days=[], start="06:00", end="22:00")],
        )
        assert is_schedule_active(cfg, now=_dt(2025, 6, 4, 12, 0)) is True  # Wed noon
        assert is_schedule_active(cfg, now=_dt(2025, 6, 4, 23, 0)) is False

    def test_day_filter(self) -> None:
        cfg = ScheduleConfig(
            enabled=True,
            timezone="Australia/Sydney",
            windows=[ScheduleWindow(days=[4], start="00:00", end="23:59")],  # Fri
        )
        friday = _dt(2025, 6, 6, 10, 0)
        saturday = _dt(2025, 6, 7, 10, 0)
        assert is_schedule_active(cfg, now=friday) is True
        assert is_schedule_active(cfg, now=saturday) is False

    def test_overnight_window(self) -> None:
        cfg = ScheduleConfig(
            enabled=True,
            timezone="UTC",
            windows=[ScheduleWindow(days=[], start="22:00", end="06:00")],
        )
        utc = UTC
        late = datetime(2025, 6, 4, 23, 0, tzinfo=utc)
        early = datetime(2025, 6, 5, 5, 0, tzinfo=utc)
        midday = datetime(2025, 6, 4, 12, 0, tzinfo=utc)
        assert is_schedule_active(cfg, now=late) is True
        assert is_schedule_active(cfg, now=early) is True
        assert is_schedule_active(cfg, now=midday) is False

    def test_bad_window_fails_open(self) -> None:
        cfg = ScheduleConfig(
            enabled=True,
            timezone="UTC",
            windows=[ScheduleWindow(days=[], start="nope", end="06:00")],
        )
        assert is_schedule_active(cfg) is True


def test_public_dict_uses_weekday_names() -> None:
    cfg = ScheduleConfig(
        enabled=True,
        timezone="UTC",
        outside="pause",
        follow_sun=True,
        sun_pad_minutes=30,
        follow_sensibo=True,
        windows=[ScheduleWindow(days=[0, 5], start="07:00", end="09:00")],
    )
    pub = schedule_public_dict(cfg)
    assert pub["windows"] == [
        {"days": ["mon", "sat"], "start": "07:00", "end": "09:00"}
    ]
    assert pub["outside"] == "pause"
    assert pub["sun_pad_minutes"] == 30
