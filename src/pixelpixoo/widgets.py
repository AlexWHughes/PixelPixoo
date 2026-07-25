"""Tile painters that draw into a rectangular region of a 64×64 canvas."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from PIL import Image, ImageDraw

from pixelpixoo.config import AppConfig
from pixelpixoo.renderer import (
    BLUE,
    CYAN,
    DIM,
    GRAY,
    GREEN,
    ORANGE,
    RED,
    WHITE,
    YELLOW,
    draw_text,
    fit_scale,
    text_width,
)
from pixelpixoo.screens.countdown import _format_remaining, _parse_target
from pixelpixoo.screens.f1 import _countdown
from pixelpixoo.screens.f1 import _fetch as _fetch_f1
from pixelpixoo.screens.f1 import _shorten, filter_sessions
from pixelpixoo.screens.sensibo import fetch_snapshot, resolve_devices
from pixelpixoo.screens.traffic import _eta_color, _fetch_route
from pixelpixoo.screens.weather import _code_short, _weekday
from pixelpixoo.screens.weather import _fetch as _fetch_weather
from pixelpixoo.theme import Theme

logger = logging.getLogger(__name__)

Rect = tuple[int, int, int, int]  # x, y, w, h


def _clip_text(text: str, max_w: int, *, tiny: bool, spacing: int) -> str:
    if text_width(text, tiny=tiny, spacing=spacing) <= max_w:
        return text
    out = text
    while out and text_width(out + ".", tiny=tiny, spacing=spacing) > max_w:
        out = out[:-1]
    return (out + ".") if out != text else out


def _pad(img: Image.Image, rect: Rect, color: tuple[int, int, int] = (16, 18, 22)) -> None:
    x, y, w, h = rect
    ImageDraw.Draw(img).rectangle([x, y, x + w - 1, y + h - 1], outline=color)


def paint_tile(
    img: Image.Image,
    rect: Rect,
    tile: str,
    cfg: AppConfig,
    theme: Theme,
    http: httpx.Client,
    *,
    outline: bool = True,
) -> None:
    """Paint one logical tile into rect. tile examples: weather, f1, sensibo, sensibo:BED, traffic, traffic:WORK, countdown, countdown:HOL."""
    if outline and (rect[2] < 64 or rect[3] < 64):
        _pad(img, rect)

    kind, _, ref = tile.partition(":")
    kind = kind.strip().lower()
    ref = ref.strip()

    try:
        if kind == "weather":
            _paint_weather(img, rect, cfg, theme, http)
        elif kind == "f1":
            _paint_f1(img, rect, theme, http, cfg)
        elif kind == "sensibo":
            _paint_sensibo(img, rect, cfg, theme, http, ref=ref)
        elif kind == "traffic":
            _paint_traffic(img, rect, cfg, theme, http, ref=ref)
        elif kind == "countdown":
            _paint_countdown(img, rect, cfg, theme, ref=ref)
        else:
            _line(img, rect, theme, f"?{kind}", RED, 0)
    except Exception:
        logger.exception("Tile %s failed", tile)
        _line(img, rect, theme, "ERR", RED, 0)


def _line(
    img: Image.Image,
    rect: Rect,
    theme: Theme,
    text: str,
    color: tuple[int, int, int],
    row: int,
    *,
    hero: bool = False,
) -> None:
    x, y, w, h = rect
    tiny = theme.use_tiny_font
    spacing = theme.spacing
    scale = theme.hero if hero else theme.body
    line_h = (theme.hero_h if hero else theme.body_h) + theme.line_gap
    yy = y + 1 + row * line_h
    if yy + (theme.hero_h if hero else theme.body_h) > y + h:
        return
    clipped = _clip_text(text.upper(), w - 2, tiny=tiny, spacing=spacing)
    # Prefer dropping trailing period when a shorter token fits better
    if clipped.endswith(".") and len(clipped) > 2:
        alt = clipped[:-1]
        if text_width(alt, scale=scale if not hero else theme.hero, tiny=tiny, spacing=spacing) <= w - 2:
            clipped = alt
    if hero:
        scale = fit_scale(clipped, w - 2, prefer=theme.hero, tiny=tiny)
    draw_text(
        img,
        clipped,
        x + 1,
        yy,
        color,
        scale=scale,
        spacing=spacing,
        tiny=tiny,
    )


def _paint_weather(
    img: Image.Image, rect: Rect, cfg: AppConfig, theme: Theme, http: httpx.Client
) -> None:
    if cfg.weather is None:
        _line(img, rect, theme, "NO WX", DIM, 0)
        return
    data = _fetch_weather(cfg.weather, http)
    label = cfg.weather.label.upper()
    row = 0
    if cfg.weather.show_current:
        temp = f"{int(round(data.temperature))}°"
        cond = _code_short(data.weather_code)
        hl = f"H{int(round(data.high))} L{int(round(data.low))}"
        if rect[3] >= 28 and theme.text_scale in ("normal", "large") and not cfg.weather.show_forecast:
            _line(img, rect, theme, f"{label} {temp}", WHITE, 0, hero=True)
            _line(img, rect, theme, cond, GRAY, 1)
            _line(img, rect, theme, hl, ORANGE, 2)
            return
        _line(img, rect, theme, f"{label} {temp}", CYAN, row)
        row += 1
        _line(img, rect, theme, f"{cond} {hl}", WHITE, row)
        row += 1
    if cfg.weather.show_forecast and data.forecast:
        today = datetime.now().date()
        days = [d for d in data.forecast if not cfg.weather.show_current or d.day > today]
        if not days:
            days = data.forecast[1:] if len(data.forecast) > 1 else data.forecast
        line_h = theme.body_h + theme.line_gap
        max_rows = max(0, (rect[3] - 2) // max(1, line_h) - row)
        for day in days[:max_rows]:
            _line(
                img,
                rect,
                theme,
                f"{_weekday(day.day)} {int(round(day.high))}/{int(round(day.low))} {_code_short(day.weather_code)}",
                WHITE,
                row,
            )
            row += 1


def _paint_f1(
    img: Image.Image, rect: Rect, theme: Theme, http: httpx.Client, cfg: AppConfig
) -> None:
    race = _fetch_f1(http)
    f1 = cfg.f1
    sessions = filter_sessions(race, f1)
    title = _shorten(race.race_name, 8 if rect[2] < 40 else 10)
    row = 0
    if f1.show_race_name:
        _line(img, rect, theme, f"F1 {title}", RED, row)
        row += 1
    if not sessions:
        _line(img, rect, theme, "NO SESS", ORANGE, row)
        return
    if f1.mode == "list":
        line_h = theme.body_h + theme.line_gap
        max_rows = max(1, (rect[3] - 2) // max(1, line_h) - row)
        for sess in sessions[:max_rows]:
            parts = [sess.label]
            if f1.show_countdown:
                parts.append(_countdown(sess.start))
            if f1.show_datetime:
                parts.append(sess.start.astimezone().strftime("%d/%H%M"))
            _line(img, rect, theme, " ".join(parts), WHITE, row)
            row += 1
        return
    sess = sessions[0]
    _line(img, rect, theme, sess.label, CYAN, row)
    row += 1
    if f1.show_countdown:
        _line(img, rect, theme, _countdown(sess.start), WHITE, row, hero=rect[3] >= 24)
        row += 1
    if f1.show_datetime:
        _line(
            img,
            rect,
            theme,
            sess.start.astimezone().strftime("%m/%d %H:%M"),
            YELLOW,
            row,
        )


def _paint_sensibo(
    img: Image.Image,
    rect: Rect,
    cfg: AppConfig,
    theme: Theme,
    http: httpx.Client,
    *,
    ref: str,
) -> None:
    if cfg.sensibo is None:
        _line(img, rect, theme, "NO AC", DIM, 0)
        return
    devices = resolve_devices(cfg.sensibo, http)
    if not devices:
        _line(img, rect, theme, "NO POD", DIM, 0)
        return
    label, pod_id = devices[0]
    if ref:
        for lab, pid in devices:
            if ref.upper() in (lab.upper(), pid.upper()):
                label, pod_id = lab, pid
                break
    snap = fetch_snapshot(cfg.sensibo.api_key, pod_id, http)
    show = cfg.sensibo
    row = 0
    head = label
    if show.show_temp and snap.temperature_c is not None:
        head = f"{label} {int(round(snap.temperature_c))}°"
    _line(img, rect, theme, head, CYAN, row)
    row += 1
    bits: list[str] = []
    if show.show_humidity and snap.humidity is not None:
        bits.append(f"{int(round(snap.humidity))}%")
    if show.show_power:
        bits.append("ON" if snap.ac_on else "OFF")
    if bits:
        color = GREEN if snap.ac_on else RED
        _line(img, rect, theme, " ".join(bits), color, row)
        row += 1
    detail: list[str] = []
    if show.show_mode and snap.mode:
        detail.append(snap.mode[:4])
    if show.show_target and snap.target_c is not None:
        detail.append(f">{snap.target_c}C")
    if detail and rect[3] >= 20:
        _line(img, rect, theme, " ".join(detail), WHITE, row)
        row += 1
    if show.show_room and rect[3] >= 24:
        _line(img, rect, theme, snap.room.upper()[:10], WHITE, row)


def _paint_traffic(
    img: Image.Image,
    rect: Rect,
    cfg: AppConfig,
    theme: Theme,
    http: httpx.Client,
    *,
    ref: str,
) -> None:
    if cfg.traffic is None or not cfg.traffic.routes:
        _line(img, rect, theme, "NO TR", DIM, 0)
        return
    routes = cfg.traffic.routes
    if ref:
        routes = [r for r in routes if r.name.upper() == ref.upper()] or routes[:1]
        eta = _fetch_route(routes[0], cfg.traffic.api_key, http)
        color = _eta_color(eta.duration_traffic_min, eta.duration_min)
        _line(img, rect, theme, eta.name.upper(), CYAN, 0)
        _line(img, rect, theme, f"{eta.duration_traffic_min}M", color, 1, hero=True)
        return

    # Pack as many routes as the rect height allows
    line_h = theme.body_h + theme.line_gap
    max_rows = max(1, (rect[3] - 2) // line_h)
    for i, route in enumerate(routes[:max_rows]):
        eta = _fetch_route(route, cfg.traffic.api_key, http)
        color = _eta_color(eta.duration_traffic_min, eta.duration_min)
        _line(
            img,
            rect,
            theme,
            f"{eta.name}:{eta.duration_traffic_min}M",
            color,
            i,
        )


def _paint_countdown(
    img: Image.Image,
    rect: Rect,
    cfg: AppConfig,
    theme: Theme,
    *,
    ref: str,
) -> None:
    if not cfg.countdown:
        _line(img, rect, theme, "NO CD", DIM, 0)
        return
    targets = cfg.countdown
    if ref:
        targets = [t for t in targets if t.label.upper() == ref.upper()] or targets[:1]
    now = datetime.now(timezone.utc)
    line_h = theme.body_h + theme.line_gap
    max_rows = max(1, (rect[3] - 2) // max(1, line_h))
    for i, target in enumerate(targets[:max_rows]):
        remaining = (_parse_target(target.at) - now).total_seconds()
        primary, _ = _format_remaining(remaining)
        color = GREEN if remaining <= 0 else (RED if remaining < 86400 else ORANGE)
        _line(img, rect, theme, f"{target.label} {primary}", color, i)


def default_tiles(cfg: AppConfig) -> list[str]:
    tiles: list[str] = []
    if cfg.weather:
        tiles.append("weather")
    if cfg.traffic:
        tiles.append("traffic")
    if cfg.sensibo:
        tiles.append("sensibo")
    if cfg.enable_f1:
        tiles.append("f1")
    if cfg.countdown:
        tiles.append("countdown")
    return tiles
