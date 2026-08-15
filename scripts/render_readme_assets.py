"""Render README gallery frames from the real Pixoo painters (no live APIs)."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pixelpixoo.config import (
    CountdownTarget,
    F1Config,
    SensiboConfig,
    TrafficConfig,
    TrafficRoute,
    WeatherConfig,
)
from pixelpixoo.renderer import draw_text, text_width
from pixelpixoo.screens.countdown import CountdownScreen
from pixelpixoo.screens.f1 import F1Screen, NextRace, SessionEvent
from pixelpixoo.screens.sensibo import SensiboScreen, SensiboSnapshot
from pixelpixoo.screens.traffic import RouteEta, TrafficScreen
from pixelpixoo.screens.weather import DayForecast, WeatherData, WeatherScreen
from pixelpixoo.theme import theme_for

DOCS = ROOT / "docs"
SCALE = 6
GAP = 16
LABEL_H = 28
LABEL_SCALE = 3
BG = (11, 13, 16)
ACCENT = (61, 224, 198)
LABEL = (232, 238, 246)


def _upscale(img: Image.Image) -> Image.Image:
    return img.resize((64 * SCALE, 64 * SCALE), Image.Resampling.NEAREST)


def _weather() -> Image.Image:
    today = date.today()
    data = WeatherData(
        temperature=22.4,
        weather_code=2,
        high=26.0,
        low=18.0,
        rain_chance=20,
        forecast=[
            DayForecast(today, 26, 18, 2, 20),
            DayForecast(today + timedelta(days=1), 24, 17, 61, 40),
            DayForecast(today + timedelta(days=2), 21, 15, 3, 10),
            DayForecast(today + timedelta(days=3), 23, 16, 0, 0),
            DayForecast(today + timedelta(days=4), 25, 17, 1, 5),
        ],
    )
    screen = WeatherScreen(
        WeatherConfig(
            latitude=-33.8688,
            longitude=151.2093,
            label="SYD",
            timezone="Australia/Sydney",
            forecast_days=5,
            show_current=True,
            show_forecast=True,
        ),
        theme=theme_for("normal"),
    )
    return screen._paint(data)


def _traffic() -> Image.Image:
    screen = TrafficScreen(
        TrafficRoute(name="WORK", origin="A", destination="B"),
        TrafficConfig(),
        theme=theme_for("normal"),
    )
    return screen._paint(
        RouteEta(
            name="WORK",
            duration_traffic_min=28,
            duration_min=22,
            summary="M1",
            avg_traffic_min=24,
        )
    )


def _sensibo() -> Image.Image:
    screen = SensiboScreen(
        "LIVING",
        "pod",
        SensiboConfig(api_key="x"),
        theme=theme_for("normal"),
    )
    return screen._paint(
        SensiboSnapshot(
            pod_id="pod",
            room="Living",
            temperature_c=23.2,
            humidity=48.0,
            ac_on=True,
            mode="cool",
            target_c=22,
            occupancy="occupied",
        )
    )


def _f1() -> Image.Image:
    start = datetime.now(timezone.utc) + timedelta(days=2, hours=4)
    race = NextRace(
        race_name="Australian Grand Prix",
        circuit="Albert Park",
        country="Australia",
        start=start + timedelta(days=2),
        sessions=[
            SessionEvent("quali", "Q", start),
            SessionEvent("race", "R", start + timedelta(days=1)),
        ],
    )
    screen = F1Screen(
        theme=theme_for("normal"),
        cfg=F1Config(mode="next", show_race_name=True, show_country=True),
    )
    return screen._paint(race)


def _countdown() -> Image.Image:
    at = (datetime.now(timezone.utc) + timedelta(days=126)).replace(
        hour=13, minute=0, second=0, microsecond=0
    )
    screen = CountdownScreen(
        CountdownTarget(label="HOLIDAY", at=at.isoformat()),
        theme=theme_for("normal"),
    )
    return screen._render()


def _compose(frames: list[tuple[str, Image.Image]]) -> Image.Image:
    cell = 64 * SCALE
    width = GAP + len(frames) * (cell + GAP)
    height = GAP + cell + GAP + LABEL_H
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    x = GAP
    for label, frame in frames:
        tile = _upscale(frame.convert("RGB"))
        # 1px cyan hairline around the matrix
        draw.rectangle(
            [x - 2, GAP - 2, x + cell + 1, GAP + cell + 1],
            outline=ACCENT,
        )
        canvas.paste(tile, (x, GAP))
        caption = label.upper()
        tw = text_width(caption, scale=LABEL_SCALE, spacing=1)
        draw_text(
            canvas,
            caption,
            x + max(0, (cell - tw) // 2),
            GAP + cell + 6,
            LABEL,
            scale=LABEL_SCALE,
            spacing=1,
        )
        x += cell + GAP
    return canvas


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    frames = [
        ("Weather", _weather()),
        ("Traffic", _traffic()),
        ("Climate", _sensibo()),
        ("F1", _f1()),
        ("Countdown", _countdown()),
    ]
    gallery = _compose(frames)
    out = DOCS / "screens.png"
    gallery.save(out, optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
