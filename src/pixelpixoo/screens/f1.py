"""F1 weekend sessions via Jolpica (practice, quali, sprint, race)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from PIL import Image

from pixelpixoo.config import F1Config, F1_SESSION_IDS
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
    error_frame,
    fit_scale,
    new_canvas,
    text_width,
)
from pixelpixoo.theme import Theme, theme_for

logger = logging.getLogger(__name__)

JOLPICA_NEXT = "https://api.jolpi.ca/ergast/f1/current/next.json"

# Jolpica field name → session id
_SESSION_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("FirstPractice", "fp1", "FP1"),
    ("SecondPractice", "fp2", "FP2"),
    ("ThirdPractice", "fp3", "FP3"),
    ("SprintQualifying", "sq", "SQ"),
    ("Sprint", "sprint", "SPR"),
    ("Qualifying", "quali", "Q"),
    ("Race", "race", "RACE"),
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


def _shorten(name: str, max_len: int = 10) -> str:
    cleaned = (
        name.upper()
        .replace("GRAND PRIX", "GP")
        .replace("FORMULA 1", "")
        .replace("  ", " ")
        .strip()
    )
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len]


def _parse_session_dt(block: dict) -> datetime | None:
    date = block.get("date")
    if not date:
        return None
    time_str = block.get("time") or "12:00:00Z"
    if time_str.endswith("Z"):
        time_str = time_str[:-1] + "+00:00"
    try:
        start = datetime.fromisoformat(f"{date}T{time_str}")
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start


def _fetch(client: httpx.Client) -> NextRace:
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
    return NextRace(
        race_name=str(race["raceName"]),
        circuit=str(circuit["circuitName"]),
        country=str(circuit["Location"]["country"]),
        start=race_start,
        sessions=sessions,
    )


def _countdown(start: datetime) -> str:
    now = datetime.now(timezone.utc)
    seconds = (start - now).total_seconds()
    if seconds <= 0:
        return "LIVE"
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        return f"{days}D {hours}H"
    if hours >= 1:
        return f"{hours}H {minutes}M"
    return f"{minutes}M"


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


class F1Screen:
    name = "f1"

    def __init__(
        self,
        client: httpx.Client | None = None,
        theme: Theme | None = None,
        cfg: F1Config | None = None,
    ) -> None:
        self.cfg = cfg or F1Config()
        self.theme = theme or theme_for("normal")
        self._client = client or httpx.Client(timeout=15.0)
        self._owns_client = client is None
        self._last: Image.Image | None = None
        self._cached: NextRace | None = None
        self._cached_at: datetime | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get_race(self) -> NextRace:
        now = datetime.now(timezone.utc)
        if (
            self._cached is not None
            and self._cached_at is not None
            and (now - self._cached_at).total_seconds() < 3600
        ):
            return self._cached
        race = _fetch(self._client)
        self._cached = race
        self._cached_at = now
        return race

    def render(self) -> Image.Image:
        try:
            race = self._get_race()
            img = self._paint(race)
            self._last = img.copy()
            return img
        except Exception:
            logger.exception("F1 fetch failed")
            if self._last is not None:
                return self._last
            return error_frame("F1")

    def _paint(self, race: NextRace) -> Image.Image:
        t = self.theme
        cfg = self.cfg
        img = new_canvas(BLACK)
        draw_label_bar(
            img, "F1", RED, height=t.header_h, tiny=t.use_tiny_font
        )
        y = t.header_h + 2
        sessions = filter_sessions(race, cfg)

        if cfg.show_race_name:
            title = _shorten(race.race_name, 12 if t.use_tiny_font else 10)
            draw_centered(
                img, title, y, WHITE, tiny=t.use_tiny_font, spacing=t.spacing
            )
            y += t.body_h + t.line_gap
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
                parts: list[str] = [sess.label]
                if cfg.show_countdown:
                    parts.append(_countdown(sess.start))
                if cfg.show_datetime:
                    parts.append(sess.start.astimezone().strftime("%m/%d %H%M"))
                row = " ".join(parts)
                draw_text(
                    img,
                    row,
                    2,
                    y,
                    CYAN if sess.session_id != "race" else RED,
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
            when = sess.start.astimezone().strftime("%m/%d %H:%M")
            if text_width(when, tiny=t.use_tiny_font, spacing=t.spacing) > 60:
                when = sess.start.astimezone().strftime("%m/%d %H%M")
            if y + t.body_h <= 62:
                draw_centered(
                    img, when, y, WHITE, tiny=t.use_tiny_font, spacing=t.spacing
                )
        return img
