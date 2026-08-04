"""F1 weekend sessions via Jolpica (practice, quali, sprint, race)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from PIL import Image

from pixelpixoo.cache import TtlCache
from pixelpixoo.config import F1_SESSION_IDS, F1Config
from pixelpixoo.renderer import (
    BLACK,
    CYAN,
    ORANGE,
    RED,
    WHITE,
    YELLOW,
    draw_centered,
    draw_label_bar,
    draw_text,
    fit_scale,
    new_canvas,
    text_width,
)
from pixelpixoo.screens.base import BaseScreen
from pixelpixoo.theme import Theme, theme_for
from pixelpixoo.timeutil import format_remaining, parse_session_datetime

logger = logging.getLogger(__name__)

JOLPICA_NEXT = "https://api.jolpi.ca/ergast/f1/current/next.json"
_F1_TTL_SEC = 3600.0

# Jolpica field name → session id → short label
_SESSION_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("FirstPractice", "fp1", "FP1"),
    ("SecondPractice", "fp2", "FP2"),
    ("ThirdPractice", "fp3", "FP3"),
    ("SprintQualifying", "sq", "SQ"),
    ("Sprint", "sprint", "S"),
    ("Qualifying", "quali", "Q"),
    ("Race", "race", "R"),
)


@dataclass
class SessionEvent:
    session_id: str
    label: str
    start: datetime


@dataclass
class NextRace:
    race_name: str
    circuit: str
    country: str
    start: datetime  # race start
    sessions: list[SessionEvent] = field(default_factory=list)


_race_cache = TtlCache[NextRace]()


def _shorten(name: str, max_len: int = 10) -> str:
    cleaned = (
        name.upper()
        .replace("GRAND PRIX", "GP")
        .replace("FORMULA 1", "")
        .replace("FORMULA1", "")
        .replace("  ", " ")
        .strip()
    )
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len]


def race_title(name: str, max_len: int = 12) -> str:
    """Format as '<NAME> GP' — never 'F1 …'."""
    raw = (
        name.upper()
        .replace("FORMULA 1", "")
        .replace("FORMULA1", "")
        .strip()
    )
    raw = " ".join(raw.split())
    base = raw.replace("GRAND PRIX", " ").replace(" GP", " ").replace("GP", " ")
    base = " ".join(base.split()).strip()
    if not base:
        title = "GP"
    else:
        title = f"{base} GP"
    if len(title) <= max_len:
        return title
    # Keep the GP suffix; truncate the place name
    budget = max(2, max_len - 3)  # room for " GP"
    return f"{base[:budget].rstrip()} GP"


def _parse_session_dt(block: dict) -> datetime | None:
    return parse_session_datetime(str(block.get("date") or ""), block.get("time"))


def _fetch(client: httpx.Client) -> NextRace:
    cached = _race_cache.get("next", _F1_TTL_SEC)
    if cached is not None:
        return cached

    response = client.get(JOLPICA_NEXT)
    response.raise_for_status()
    races = response.json()["MRData"]["RaceTable"]["Races"]
    if not races:
        raise RuntimeError("No upcoming F1 race in Jolpica response")
    race = races[0]
    race_start = _parse_session_dt(
        {"date": race["date"], "time": race.get("time", "12:00:00Z")}
    )
    if race_start is None:
        raise RuntimeError("Invalid race start time")
    circuit = race["Circuit"]
    sessions: list[SessionEvent] = []
    for field_name, sid, label in _SESSION_FIELDS:
        if field_name == "Race":
            sessions.append(SessionEvent(session_id=sid, label=label, start=race_start))
            continue
        block = race.get(field_name)
        if not isinstance(block, dict):
            continue
        start = _parse_session_dt(block)
        if start is None:
            continue
        sessions.append(SessionEvent(session_id=sid, label=label, start=start))
    sessions.sort(key=lambda s: s.start)
    result = NextRace(
        race_name=str(race["raceName"]),
        circuit=str(circuit["circuitName"]),
        country=str(circuit["Location"]["country"]),
        start=race_start,
        sessions=sessions,
    )
    _race_cache.set("next", result)
    return result


def _countdown(start: datetime) -> str:
    now = datetime.now(timezone.utc)
    seconds = (start - now).total_seconds()
    return format_remaining(seconds, zero_label="LIVE", pad_hours=False)


def _when_short(start: datetime) -> str:
    """Compact local date/time that stays readable on a 64px tile."""
    local = start.astimezone()
    return local.strftime("%d %b").upper() + local.strftime(" %H:%M")


def _when_date(start: datetime) -> str:
    return start.astimezone().strftime("%d %b").upper()


def _when_time(start: datetime) -> str:
    return start.astimezone().strftime("%H:%M")


def filter_sessions(race: NextRace, cfg: F1Config) -> list[SessionEvent]:
    allowed = {s for s in cfg.sessions if s in F1_SESSION_IDS}
    now = datetime.now(timezone.utc)
    upcoming = [
        s for s in race.sessions if s.session_id in allowed and s.start >= now
    ]
    # If all finished, still show race as LIVE/past
    if not upcoming:
        race_sessions = [s for s in race.sessions if s.session_id in allowed]
        return race_sessions[-1:] if race_sessions else []
    return upcoming


class F1Screen(BaseScreen):
    name = "f1"
    error_label = "F1"

    def __init__(
        self,
        client: httpx.Client | None = None,
        theme: Theme | None = None,
        cfg: F1Config | None = None,
    ) -> None:
        super().__init__(client, timeout=15.0)
        self.cfg = cfg or F1Config()
        self.theme = theme or theme_for("normal")

    def _render(self) -> Image.Image:
        race = _fetch(self._client)
        return self._paint(race)

    def _paint(self, race: NextRace) -> Image.Image:
        t = self.theme
        cfg = self.cfg
        img = new_canvas(BLACK)
        header = (
            race_title(race.race_name, 12 if t.use_tiny_font else 10)
            if cfg.show_race_name
            else "F1"
        )
        draw_label_bar(
            img, header, RED, height=t.header_h, tiny=t.use_tiny_font
        )
        y = t.header_h + 2
        sessions = filter_sessions(race, cfg)

        if cfg.show_country:
            country = _shorten(race.country, 12 if t.use_tiny_font else 10)
            draw_centered(
                img, country, y, YELLOW, tiny=t.use_tiny_font, spacing=t.spacing
            )
            y += t.body_h + t.line_gap

        if not sessions:
            draw_centered(
                img, "NO SESS", y, ORANGE, tiny=t.use_tiny_font, spacing=t.spacing
            )
            return img

        if cfg.mode == "list":
            line_h = t.body_h + t.line_gap
            max_rows = max(1, (62 - y) // max(1, line_h))
            for sess in sessions[:max_rows]:
                left = sess.label
                if cfg.show_countdown:
                    left = f"{sess.label} {_countdown(sess.start)}"
                draw_text(
                    img,
                    left,
                    2,
                    y,
                    CYAN if sess.session_id != "race" else RED,
                    spacing=t.spacing,
                    tiny=t.use_tiny_font,
                )
                if cfg.show_datetime:
                    when = _when_time(sess.start)
                    wx = 62 - text_width(when, tiny=t.use_tiny_font, spacing=t.spacing)
                    if wx > text_width(left, tiny=t.use_tiny_font, spacing=t.spacing) + 4:
                        draw_text(
                            img,
                            when,
                            max(2, wx),
                            y,
                            WHITE,
                            spacing=t.spacing,
                            tiny=t.use_tiny_font,
                        )
                y += line_h
            return img

        # mode == next
        sess = sessions[0]
        draw_centered(
            img,
            sess.label,
            y,
            CYAN if sess.session_id != "race" else RED,
            tiny=t.use_tiny_font,
            spacing=t.spacing,
        )
        y += t.body_h + t.line_gap

        if cfg.show_countdown:
            cd = _countdown(sess.start)
            scale = fit_scale(cd, 60, prefer=t.hero, tiny=t.use_tiny_font)
            draw_centered(
                img, cd, y, RED, scale=scale, tiny=t.use_tiny_font, spacing=t.spacing
            )
            y += (7 * scale if not t.use_tiny_font else 5) + t.line_gap

        if cfg.show_datetime:
            when = _when_short(sess.start)
            if text_width(when, tiny=t.use_tiny_font, spacing=t.spacing) > 60:
                when = _when_time(sess.start)
            if y + t.body_h <= 62:
                draw_centered(
                    img, when, y, WHITE, tiny=t.use_tiny_font, spacing=t.spacing
                )
        return img
