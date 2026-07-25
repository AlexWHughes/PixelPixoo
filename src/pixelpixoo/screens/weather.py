"""Weather screen via Open-Meteo (current + multi-day forecast)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, ImageDraw

from pixelpixoo.config import WeatherConfig
from pixelpixoo.renderer import (
    BLACK,
    BLUE,
    CYAN,
    GRAY,
    ORANGE,
    WHITE,
    YELLOW,
    draw_centered,
    draw_label_bar,
    draw_text,
    error_frame,
    fit_scale,
    new_canvas,
    set_pixel,
)
from pixelpixoo.theme import Theme, theme_for

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class DayForecast:
    day: date
    high: float
    low: float
    weather_code: int


@dataclass
class WeatherData:
    temperature: float
    weather_code: int
    high: float
    low: float
    forecast: list[DayForecast] = field(default_factory=list)


def _fetch(cfg: WeatherConfig, client: httpx.Client) -> WeatherData:
    days = max(1, min(7, cfg.forecast_days))
    params = {
        "latitude": cfg.latitude,
        "longitude": cfg.longitude,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": cfg.timezone,
        "forecast_days": days,
    }
    response = client.get(OPEN_METEO_URL, params=params)
    response.raise_for_status()
    data = response.json()
    current = data["current"]
    daily = data["daily"]
    forecast: list[DayForecast] = []
    dates = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []
    for i, day_str in enumerate(dates):
        forecast.append(
            DayForecast(
                day=date.fromisoformat(str(day_str)[:10]),
                high=float(highs[i]),
                low=float(lows[i]),
                weather_code=int(codes[i]) if i < len(codes) else 0,
            )
        )
    return WeatherData(
        temperature=float(current["temperature_2m"]),
        weather_code=int(current["weather_code"]),
        high=float(highs[0]) if highs else float(current["temperature_2m"]),
        low=float(lows[0]) if lows else float(current["temperature_2m"]),
        forecast=forecast,
    )


def _code_label(code: int) -> str:
    if code == 0:
        return "CLEAR"
    if code in (1, 2):
        return "FAIR"
    if code == 3:
        return "CLOUD"
    if code in (45, 48):
        return "FOG"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "RAIN"
    if code in (71, 73, 75, 77, 85, 86):
        return "SNOW"
    if code in (95, 96, 99):
        return "STORM"
    return "WX"


def _code_short(code: int) -> str:
    label = _code_label(code)
    return {
        "CLEAR": "CLR",
        "FAIR": "FAIR",
        "CLOUD": "CLD",
        "FOG": "FOG",
        "RAIN": "RAIN",
        "SNOW": "SNOW",
        "STORM": "STM",
    }.get(label, "WX")


def _weekday(d: date) -> str:
    return d.strftime("%a").upper()[:2]


def _draw_icon(img: Image.Image, code: int, ox: int, oy: int) -> None:
    draw = ImageDraw.Draw(img)
    if code == 0:
        draw.ellipse([ox + 4, oy + 4, ox + 16, oy + 16], fill=YELLOW)
        for dx, dy in ((10, 0), (10, 20), (0, 10), (20, 10), (3, 3), (17, 3), (3, 17), (17, 17)):
            set_pixel(img, ox + dx, oy + dy, ORANGE)
    elif code in (1, 2, 3):
        draw.ellipse([ox + 2, oy + 2, ox + 12, oy + 12], fill=YELLOW)
        draw.ellipse([ox + 6, oy + 8, ox + 20, oy + 18], fill=GRAY)
        draw.ellipse([ox + 10, oy + 6, ox + 22, oy + 16], fill=(140, 140, 150))
    elif code in (45, 48):
        for y in range(oy + 4, oy + 18, 3):
            for x in range(ox + 2, ox + 20, 2):
                set_pixel(img, x, y, GRAY)
    elif code in (71, 73, 75, 77, 85, 86):
        for i, (x, y) in enumerate(
            ((4, 4), (10, 2), (16, 5), (6, 10), (12, 12), (18, 9), (8, 16), (14, 18))
        ):
            color = WHITE if i % 2 == 0 else CYAN
            set_pixel(img, ox + x, oy + y, color)
            set_pixel(img, ox + x + 1, oy + y, color)
    elif code in (95, 96, 99):
        draw.ellipse([ox + 4, oy + 2, ox + 18, oy + 12], fill=GRAY)
        draw.polygon(
            [(ox + 10, oy + 10), (ox + 6, oy + 20), (ox + 12, oy + 14), (ox + 16, oy + 22)],
            fill=YELLOW,
        )
    else:
        draw.ellipse([ox + 4, oy + 2, ox + 18, oy + 12], fill=GRAY)
        for x in (ox + 6, ox + 10, ox + 14):
            draw.line([(x, oy + 14), (x - 1, oy + 20)], fill=BLUE)


class WeatherScreen:
    name = "weather"

    def __init__(
        self,
        cfg: WeatherConfig,
        client: httpx.Client | None = None,
        theme: Theme | None = None,
    ) -> None:
        self.cfg = cfg
        self.theme = theme or theme_for("normal")
        self._client = client or httpx.Client(timeout=15.0)
        self._owns_client = client is None
        self._last: Image.Image | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def render(self) -> Image.Image:
        try:
            data = _fetch(self.cfg, self._client)
            img = self._paint(data)
            self._last = img.copy()
            return img
        except Exception:
            logger.exception("Weather fetch failed")
            if self._last is not None:
                return self._last
            return error_frame("WX")

    def _paint(self, data: WeatherData) -> Image.Image:
        t = self.theme
        img = new_canvas(BLACK)
        draw_label_bar(
            img,
            self.cfg.label.upper(),
            CYAN,
            height=t.header_h,
            tiny=t.use_tiny_font,
        )
        y = t.header_h + 2

        if self.cfg.show_current:
            if t.text_scale in ("normal", "large") and not self.cfg.show_forecast:
                _draw_icon(img, data.weather_code, 4, t.header_h + 4)
                temp = f"{int(round(data.temperature))}°"
                scale = fit_scale(temp, 34, prefer=t.hero, tiny=t.use_tiny_font)
                draw_text(
                    img,
                    temp,
                    28,
                    t.header_h + 6,
                    WHITE,
                    scale=scale,
                    spacing=t.spacing,
                    tiny=t.use_tiny_font,
                )
                draw_text(
                    img,
                    _code_label(data.weather_code),
                    28,
                    t.header_h + 6 + t.hero_h + t.line_gap,
                    GRAY,
                    spacing=t.spacing,
                    tiny=t.use_tiny_font,
                )
                hi_lo = f"H{int(round(data.high))} L{int(round(data.low))}"
                draw_centered(
                    img,
                    hi_lo,
                    52,
                    ORANGE,
                    tiny=t.use_tiny_font,
                    spacing=t.spacing,
                )
                return img

            temp = f"{int(round(data.temperature))}° {_code_short(data.weather_code)}"
            draw_text(
                img,
                temp,
                2,
                y,
                WHITE,
                scale=t.hero if t.text_scale != "tiny" else 1,
                spacing=t.spacing,
                tiny=t.use_tiny_font,
            )
            y += t.hero_h + t.line_gap
            hi_lo = f"H{int(round(data.high))} L{int(round(data.low))}"
            draw_text(
                img,
                hi_lo,
                2,
                y,
                ORANGE,
                spacing=t.spacing,
                tiny=t.use_tiny_font,
            )
            y += t.body_h + t.line_gap + 1

        if self.cfg.show_forecast and data.forecast:
            # Skip today if we already showed current; show upcoming days
            try:
                today = datetime.now(ZoneInfo(self.cfg.timezone)).date()
            except Exception:
                today = datetime.now().date()
            days = [
                d
                for d in data.forecast
                if not self.cfg.show_current or d.day > today
            ]
            if not days:
                days = data.forecast[1:] if len(data.forecast) > 1 else data.forecast
            line_h = t.body_h + t.line_gap
            max_rows = max(1, (62 - y) // max(1, line_h))
            for day in days[:max_rows]:
                row = (
                    f"{_weekday(day.day)} "
                    f"{int(round(day.high))}/{int(round(day.low))} "
                    f"{_code_short(day.weather_code)}"
                )
                draw_text(
                    img,
                    row,
                    2,
                    y,
                    WHITE,
                    spacing=t.spacing,
                    tiny=t.use_tiny_font,
                )
                y += line_h
        return img
