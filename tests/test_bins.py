"""Tests for pixelpixoo.screens.bins scheduling logic."""

from __future__ import annotations

from datetime import date

from pixelpixoo.screens.bins import (
    format_bin_lines,
    next_due_for_stream,
    parse_weekday,
    put_out_weekday,
    upcoming_dues,
    when_phrase,
)

# Wed 2025-06-04 — a neutral mid-week day.
WED = date(2025, 6, 4)


class TestParseWeekday:
    def test_names_and_numbers(self) -> None:
        assert parse_weekday("FRI") == 4
        assert parse_weekday("thursday") == 3
        assert parse_weekday(6) == 6
        assert parse_weekday("3") == 3

    def test_invalid(self) -> None:
        assert parse_weekday("sometime") is None
        assert parse_weekday("") is None
        assert parse_weekday(9) is None
        assert parse_weekday(None) is None


class TestPutOutWeekday:
    def test_eve_before_shifts_back(self) -> None:
        assert put_out_weekday(0, eve_before=True) == 6  # Mon → Sun night
        assert put_out_weekday(2, eve_before=True) == 1

    def test_morning_keeps_day(self) -> None:
        assert put_out_weekday(4, eve_before=False) == 4


def _due(**kwargs):
    return next_due_for_stream(
        label=kwargs.get("label", "RUB"),
        collection_weekday=kwargs.get("collection_weekday", 3),  # Thu collection
        today=kwargs.get("today", WED),
        every_weeks=kwargs.get("every_weeks", 1),
        anchor=kwargs.get("anchor"),
        eve_before=kwargs.get("eve_before", True),
        horizon_days=14,
    )


class TestNextDue:
    def test_tonight_is_put_out_evening(self) -> None:
        # Wednesday evening = put-out night before Thursday collection.
        due = _due()
        assert due is not None
        assert due.days_until == 0
        assert due.put_out == WED

    def test_morning_mode_points_at_collection_day(self) -> None:
        due = _due(eve_before=False)
        assert due is not None and due.days_until == 1

    def test_after_put_out_moves_to_next_week(self) -> None:
        thu = date(2025, 6, 5)  # collection day already underway
        due = _due(today=thu)
        assert due is not None and due.days_until == 6

    def test_fortnight_aligned_anchor_hits(self) -> None:
        # Anchor collection Thu 2025-06-05 → put-out Wed 2025-06-04.
        due = _due(every_weeks=2, anchor=date(2025, 6, 5))
        assert due is not None and due.days_until == 0

    def test_fortnight_off_week_skips(self) -> None:
        # Anchor one week later: 2025-06-12 → this week is an off week.
        due = _due(every_weeks=2, anchor=date(2025, 6, 12))
        assert due is not None
        assert due.days_until == 7

    def test_label_truncated_to_twelve(self) -> None:
        due = _due(label="REALLYLONGBINNAME")
        assert due is not None and due.label == "REALLYLONGBI"


class TestUpcomingDues:
    def test_lead_days_filters_far_streams(self) -> None:
        streams = [
            ("RUB", 3, 1, None, ""),  # tonight (Wed eve)
            ("REC", 4, 1, None, ""),  # tomorrow night
        ]
        dues = upcoming_dues(streams, WED, lead_days=0)
        assert [d.label for d in dues] == ["RUB"]

    def test_sorted_by_soonest_then_label(self) -> None:
        streams = [
            ("ZED", 4, 1, None, ""),
            ("ALPHA", 4, 1, None, ""),
            ("MID", 3, 1, None, ""),
        ]
        dues = upcoming_dues(streams, WED, lead_days=7)
        assert [(d.label, d.days_until) for d in dues] == [
            ("MID", 0),
            ("ALPHA", 1),
            ("ZED", 1),
        ]


class TestFormatBinLines:
    def test_empty(self) -> None:
        assert format_bin_lines([]) == ("BINS", "NONE", 2)

    def test_single_bin_tonight(self) -> None:
        dues = upcoming_dues([("RUBBISH", 3, 1, None, "")], WED)
        line1, line2, urgency = format_bin_lines(dues)
        assert (line1, line2, urgency) == ("RUBBISH", "TONIGHT", 0)

    def test_multiple_bins_share_short_labels(self) -> None:
        dues = upcoming_dues(
            [("LANDFILL", 3, 1, None, ""), ("RECYCLING", 3, 1, None, "")], WED
        )
        line1, line2, urgency = format_bin_lines(dues)
        assert line1 == "RUB+REC"
        assert line2 == "TONIGHT"
        assert urgency == 0

    def test_later_this_week_shows_weekday(self) -> None:
        mon = date(2025, 6, 2)  # Mon: Thu-night put-out is days_until 3
        dues = upcoming_dues([("GREEN", 4, 1, None, "")], mon, lead_days=6)
        line1, line2, urgency = format_bin_lines(dues)
        assert line1 == "GREEN"
        assert line2 == "THU"
        assert urgency == 2


def test_when_phrase() -> None:
    assert when_phrase(0, WED) == "TONIGHT"
    assert when_phrase(1, WED) == "TOMORROW"
    assert when_phrase(4, date(2025, 6, 6)) == "FRI"  # put_out Friday
