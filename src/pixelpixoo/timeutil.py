"""Shared ISO datetime parsing and countdown formatting."""

from __future__ import annotations

from datetime import datetime, timezone

from pixelpixoo.renderer import GREEN, ORANGE, PURPLE, RED


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime; bare ``Z`` and naive values become UTC."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_session_datetime(date: str, time_str: str | None = None) -> datetime | None:
    """Parse Jolpica-style date + optional time (default noon UTC)."""
    if not date:
        return None
    clock = time_str or "12:00:00Z"
    if clock.endswith("Z"):
        clock = clock[:-1] + "+00:00"
    try:
        return parse_iso_datetime(f"{date}T{clock}")
    except ValueError:
        return None


def format_remaining(
    delta_seconds: float,
    *,
    zero_label: str = "NOW",
    pad_hours: bool = True,
) -> str:
    """Compact remaining-time string (e.g. ``3D 02H``, ``LIVE``, ``NOW``)."""
    if delta_seconds <= 0:
        return zero_label
    total = int(delta_seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 100:
        return f"{days}D"
    if days >= 1:
        if pad_hours:
            return f"{days}D {hours:02d}H"
        return f"{days}D {hours}H"
    if hours >= 1:
        if pad_hours:
            return f"{hours}H {minutes:02d}M"
        return f"{hours}H {minutes}M"
    return f"{max(1, minutes)}M"


def format_remaining_pair(delta_seconds: float) -> tuple[str, str]:
    """Countdown primary + secondary labels (``LEFT`` / ``DONE``)."""
    if delta_seconds <= 0:
        return "NOW", "DONE"
    return format_remaining(delta_seconds, zero_label="NOW", pad_hours=True), "LEFT"


def remaining_seconds(target: datetime, *, now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (target - current).total_seconds()


def urgency_color(
    remaining: float,
    *,
    use_week_band: bool = True,
) -> tuple[int, int, int]:
    """Accent by urgency: done → <1d → (<7d orange / else purple) or orange."""
    if remaining <= 0:
        return GREEN
    if remaining < 86400:
        return RED
    if not use_week_band:
        return ORANGE
    if remaining < 7 * 86400:
        return ORANGE
    return PURPLE


def compact_days(remaining: float) -> str | None:
    """If more than a day remains, return ``Nd`` for narrow tiles."""
    if remaining > 86400:
        return f"{int(remaining) // 86400}D"
    return None
