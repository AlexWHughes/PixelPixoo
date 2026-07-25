"""Active-hours schedule for showing / hiding the dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

DAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


@dataclass
class ScheduleWindow:
    days: list[int]  # 0=Mon .. 6=Sun; empty = every day
    start: str  # HH:MM
    end: str  # HH:MM


@dataclass
class ScheduleConfig:
    enabled: bool = False
    timezone: str = "UTC"
    # When enabled: only push during windows. Outside = screen off.
    windows: list[ScheduleWindow] = field(default_factory=list)
    # What to do outside windows: off = blank/turn off screen, pause = stop pushing but leave last frame
    outside: str = "off"


def _parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) < 1 or not parts[0].isdigit():
        raise ValueError(f"Invalid time: {value!r}")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time: {value!r}")
    return time(hour=hour, minute=minute)


def _day_numbers(days: list[str] | list[int] | None) -> list[int]:
    if not days:
        return []
    out: list[int] = []
    unknown: list[str] = []
    for d in days:
        if isinstance(d, int):
            if 0 <= d <= 6:
                out.append(d)
            continue
        key = str(d).strip().lower()
        if key in ("*", "all", "every"):
            return []
        if key in DAY_ALIASES:
            out.append(DAY_ALIASES[key])
        else:
            unknown.append(key)
    if unknown and not out:
        raise ValueError(f"Unknown schedule days: {', '.join(unknown)}")
    if unknown:
        # Partial typos: keep known days, ignore unknown
        pass
    return sorted(set(out))


def parse_schedule(raw: dict | None) -> ScheduleConfig:
    if not isinstance(raw, dict):
        return ScheduleConfig()
    windows: list[ScheduleWindow] = []
    for item in raw.get("windows") or []:
        if not isinstance(item, dict):
            continue
        start = str(item.get("start", "")).strip()
        end = str(item.get("end", "")).strip()
        if not start or not end:
            continue
        windows.append(
            ScheduleWindow(
                days=_day_numbers(item.get("days")),
                start=start,
                end=end,
            )
        )
    outside = str(raw.get("outside", "off")).lower().strip()
    if outside not in ("off", "pause"):
        outside = "off"
    return ScheduleConfig(
        enabled=bool(raw.get("enabled", False)),
        timezone=str(raw.get("timezone", "UTC")),
        windows=windows,
        outside=outside,
    )


def is_schedule_active(cfg: ScheduleConfig, now: datetime | None = None) -> bool:
    """Return True if the dashboard should be showing right now."""
    if not cfg.enabled:
        return True
    if not cfg.windows:
        return True
    try:
        tz = ZoneInfo(cfg.timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    current = now.astimezone(tz) if now else datetime.now(tz)
    weekday = current.weekday()
    clock = current.timetz().replace(tzinfo=None)

    try:
        for window in cfg.windows:
            if window.days and weekday not in window.days:
                continue
            start = _parse_hhmm(window.start)
            end = _parse_hhmm(window.end)
            if start <= end:
                if start <= clock <= end:
                    return True
            else:
                if clock >= start or clock <= end:
                    return True
    except ValueError:
        # Bad window config: fail open so the device keeps updating
        return True
    return False


def schedule_public_dict(cfg: ScheduleConfig) -> dict:
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return {
        "enabled": cfg.enabled,
        "timezone": cfg.timezone,
        "outside": cfg.outside,
        "windows": [
            {
                "days": [day_names[d] for d in w.days] if w.days else ["all"],
                "start": w.start,
                "end": w.end,
            }
            for w in cfg.windows
        ],
    }
