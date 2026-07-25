"""Kerbside bin-night reminders from a simple weekly / fortnightly schedule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pixelpixoo.schedule import DAY_ALIASES

WEEKDAYS_SHORT = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
LABEL_MAX = 12


@dataclass(frozen=True)
class BinDue:
    label: str
    put_out: date
    days_until: int  # 0 = tonight, 1 = tomorrow, …


def parse_weekday(value: object) -> int | None:
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    key = str(value or "").strip().lower()
    if not key:
        return None
    if key.isdigit():
        n = int(key)
        return n if 0 <= n <= 6 else None
    return DAY_ALIASES.get(key)


def _parse_anchor(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def put_out_weekday(collection_weekday: int, *, eve_before: bool) -> int:
    if eve_before:
        return (collection_weekday - 1) % 7
    return collection_weekday


def _next_on_weekday(today: date, weekday: int) -> date:
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta)


def _normalize_collection_anchor(anchor: date, collection_weekday: int) -> date:
    """Snap an anchor date back to the stream's collection weekday if needed."""
    delta = (anchor.weekday() - collection_weekday) % 7
    return anchor - timedelta(days=delta)


def _fortnight_hit(put_out: date, anchor: date, every_weeks: int) -> bool:
    if every_weeks <= 1:
        return True
    weeks_apart = (put_out - anchor).days // 7
    return weeks_apart % every_weeks == 0


def next_due_for_stream(
    *,
    label: str,
    collection_weekday: int,
    today: date,
    every_weeks: int = 1,
    anchor: date | None = None,
    eve_before: bool = True,
    horizon_days: int = 14,
) -> BinDue | None:
    """Return the next put-out day for a stream within horizon_days, or None."""
    out_wd = put_out_weekday(collection_weekday, eve_before=eve_before)
    weeks = max(1, every_weeks)
    # Anchor is a known *collection* date; put-out is the evening before when eve_before.
    put_anchor: date | None = None
    if anchor is not None:
        collection_anchor = _normalize_collection_anchor(anchor, collection_weekday)
        put_anchor = (
            collection_anchor - timedelta(days=1)
            if eve_before
            else collection_anchor
        )

    start = _next_on_weekday(today, out_wd)
    for week in range(0, max(horizon_days // 7 + weeks + 2, weeks + 2)):
        candidate = start + timedelta(weeks=week)
        if (candidate - today).days > horizon_days:
            break
        if weeks > 1 and put_anchor is not None and not _fortnight_hit(
            candidate, put_anchor, weeks
        ):
            continue
        return BinDue(
            label=label[:LABEL_MAX],
            put_out=candidate,
            days_until=(candidate - today).days,
        )
    return None


def upcoming_dues(
    streams: list[tuple[str, int, int, date | None]],
    today: date,
    *,
    eve_before: bool = True,
    lead_days: int = 1,
    horizon_days: int | None = None,
) -> list[BinDue]:
    """
    streams: (label, collection_weekday, every_weeks, anchor_collection_date)
    """
    limit = lead_days if horizon_days is None else horizon_days
    dues: list[BinDue] = []
    for label, weekday, every_weeks, anchor in streams:
        due = next_due_for_stream(
            label=label,
            collection_weekday=weekday,
            today=today,
            every_weeks=every_weeks,
            anchor=anchor,
            eve_before=eve_before,
            horizon_days=max(limit, 14),
        )
        if due is not None and due.days_until <= limit:
            dues.append(due)
    dues.sort(key=lambda d: (d.days_until, d.label))
    return dues


_SHORT_LABELS = {
    "LANDFILL": "RUB",
    "RUBBISH": "RUB",
    "GARBAGE": "RUB",
    "GENERAL": "RUB",
    "RECYCLE": "REC",
    "RECYCLING": "REC",
    "GREEN": "GRN",
    "GARDEN": "GRN",
    "FOGO": "FOGO",
    "FOOD": "FOGO",
}


def when_phrase(days_until: int, put_out: date) -> str:
    if days_until <= 0:
        return "TONIGHT"
    if days_until == 1:
        return "TOMORROW"
    return WEEKDAYS_SHORT[put_out.weekday()]


def _short_label(label: str) -> str:
    key = label.upper().strip()
    return _SHORT_LABELS.get(key, key[:4])


def format_bin_lines(dues: list[BinDue]) -> tuple[str, str, int]:
    """
    Compact two-line summary for a 64×64 tile.
    Returns (line1, line2, urgency) where urgency 0=tonight, 1=tomorrow, 2=later.
    """
    if not dues:
        return ("BINS", "NONE", 2)

    soonest = dues[0].days_until
    group = [d for d in dues if d.days_until == soonest]
    labels = [d.label.upper() for d in group]
    when = when_phrase(soonest, group[0].put_out)

    if len(labels) == 1:
        line1 = labels[0]
    else:
        joined = "+".join(_short_label(lab) for lab in labels)
        line1 = joined if len(joined) <= 14 else "BINS"

    return (line1, when, soonest if soonest <= 2 else 2)


def local_today(timezone: str) -> date:
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("Australia/Melbourne")
    return datetime.now(tz).date()


__all__ = [
    "BinDue",
    "LABEL_MAX",
    "WEEKDAYS_SHORT",
    "format_bin_lines",
    "local_today",
    "next_due_for_stream",
    "parse_weekday",
    "put_out_weekday",
    "upcoming_dues",
    "when_phrase",
    "_parse_anchor",
]
