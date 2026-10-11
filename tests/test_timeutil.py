"""Tests for pixelpixoo.timeutil."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pixelpixoo.renderer import GREEN, ORANGE, PURPLE, RED
from pixelpixoo.timeutil import (
    compact_days,
    format_remaining,
    format_remaining_pair,
    parse_iso_datetime,
    parse_session_datetime,
    remaining_seconds,
    urgency_color,
)

UTC = UTC


class TestParseIsoDatetime:
    def test_trailing_z_becomes_utc(self) -> None:
        dt = parse_iso_datetime("2025-03-14T15:30:00Z")
        assert dt.tzinfo == UTC
        assert dt == datetime(2025, 3, 14, 15, 30, tzinfo=UTC)

    def test_offset_is_preserved(self) -> None:
        dt = parse_iso_datetime("2025-03-14T15:30:00+10:00")
        assert dt.utcoffset() == timedelta(hours=10)

    def test_naive_assumed_utc(self) -> None:
        dt = parse_iso_datetime("2025-03-14T15:30:00")
        assert dt.tzinfo == UTC


class TestParseSessionDatetime:
    def test_date_and_time(self) -> None:
        dt = parse_session_datetime("2025-03-16", "15:00:00Z")
        assert dt == datetime(2025, 3, 16, 15, 0, tzinfo=UTC)

    def test_date_defaults_to_noon_utc(self) -> None:
        dt = parse_session_datetime("2025-03-16", None)
        assert dt == datetime(2025, 3, 16, 12, 0, tzinfo=UTC)

    def test_empty_or_invalid_returns_none(self) -> None:
        assert parse_session_datetime("", "15:00:00Z") is None
        assert parse_session_datetime("not-a-date") is None


class TestFormatRemaining:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "NOW"),
            (-5, "GONE"),
            (59, "1M"),
            (3599, "59M"),
            (3600, "1H 00M"),
            (90000, "1D 01H"),
            (100 * 86400 + 3600, "100D"),
        ],
    )
    def test_branches(self, seconds: int, expected: str) -> None:
        label = "GONE" if seconds < 0 else "NOW"
        assert format_remaining(seconds, zero_label=label) == expected

    def test_unpadded_hours(self) -> None:
        assert format_remaining(90000, pad_hours=False) == "1D 1H"


def test_format_remaining_pair() -> None:
    assert format_remaining_pair(0) == ("NOW", "DONE")
    pair = format_remaining_pair(7200)
    assert pair[0] == "2H 00M" and pair[1] == "LEFT"


class TestRemainingSeconds:
    def test_positive_delta(self) -> None:
        now = datetime(2025, 3, 14, 15, 30, tzinfo=UTC)
        target = now + timedelta(minutes=90)
        assert remaining_seconds(target, now=now) == 5400

    def test_naive_now_treated_as_utc(self) -> None:
        target = datetime(2030, 1, 1, tzinfo=UTC)
        now = datetime(2029, 12, 31)  # naive
        secs = remaining_seconds(target, now=now)
        assert secs == 86400.0


class TestUrgencyColor:
    def test_done_is_green(self) -> None:
        assert urgency_color(-1) == GREEN
        assert urgency_color(0) == GREEN

    def test_under_a_day_is_red(self) -> None:
        assert urgency_color(86399) == RED

    def test_week_bands(self) -> None:
        assert urgency_color(2 * 86400) == ORANGE
        assert urgency_color(8 * 86400) == PURPLE
        # Without the week band everything pending is orange.
        assert urgency_color(8 * 86400, use_week_band=False) == ORANGE


def test_compact_days() -> None:
    assert compact_days(3 * 86400 + 1) == "3D"
    assert compact_days(86400) is None
    assert compact_days(3600) is None
