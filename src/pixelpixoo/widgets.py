"""Tile painters that draw into a rectangular region of a 64×64 canvas."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, ImageDraw

from pixelpixoo.config import AppConfig, resolve_app_timezone
from pixelpixoo.renderer import (
    CYAN,
    DIM,
    GREEN,
    ORANGE,
    RED,
    WHITE,
    YELLOW,
    draw_text,
    fit_scale,
    text_width,
)
from pixelpixoo.screens.bins import BinDue
from pixelpixoo.screens.bins import (
    _parse_anchor,
    format_bin_lines,
    local_today,
    upcoming_dues,
)
from pixelpixoo.screens.countdown import _format_remaining, _parse_target
from pixelpixoo.screens.f1 import (
    _countdown,
    _when_short,
    filter_sessions,
    race_title,
)
from pixelpixoo.screens.f1 import _fetch as _fetch_f1
from pixelpixoo.screens.sensibo import fetch_snapshot, resolve_devices
from pixelpixoo.screens.traffic import _eta_baseline, _eta_color, _fetch_route
from pixelpixoo.screens.weather import (
    _WEEKDAYS_SHORT,
    _code_label,
    _day_label,
    draw_tiny_rain_cloud,
)
from pixelpixoo.screens.weather import _fetch as _fetch_weather
from pixelpixoo.theme import Theme

logger = logging.getLogger(__name__)

Rect = tuple[int, int, int, int]  # x, y, w, h
WEATHER_PAGE_SECONDS = 8.0


def _traffic_timezone(cfg: AppConfig) -> str:
    return resolve_app_timezone(cfg)


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
    """Paint one logical tile into rect. tile examples: weather, f1, sensibo, sensibo:BED, traffic, traffic:WORK, countdown, countdown:HOL, bins."""
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
        elif kind == "bins":
            _paint_bins(img, rect, cfg, theme)
        else:
            _line(img, rect, theme, f"?{kind}", RED, 0)
    except Exception:
        logger.exception("Tile %s failed", tile)
        _line(img, rect, theme, "ERR", RED, 0)


def tile_is_visible(tile: str, cfg: AppConfig) -> bool:
    """Conditional tiles return False when they should leave the layout."""
    kind = tile.partition(":")[0].strip().lower()
    if kind == "bins":
        return bins_are_due(cfg)
    return True


def visible_tiles(cfg: AppConfig, tiles: list[str]) -> list[str]:
    return [t for t in tiles if tile_is_visible(t, cfg)]


def bins_are_due(cfg: AppConfig) -> bool:
    return bool(_bins_dues(cfg))


def _bins_dues(cfg: AppConfig) -> list[BinDue]:
    bins = cfg.bins
    if bins is None or not bins.enabled or not bins.streams:
        return []
    streams = [
        (
            s.label,
            s.weekday,
            s.every_weeks,
            _parse_anchor(s.anchor),
        )
        for s in bins.streams
    ]
    today = local_today(bins.timezone)
    return upcoming_dues(
        streams,
        today,
        eve_before=bins.eve_before,
        lead_days=bins.lead_days,
    )


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
    try:
        tz = ZoneInfo(cfg.weather.timezone)
        now = datetime.now(tz)
        today = now.date()
    except Exception:
        now = datetime.now()
        today = now.date()

    clock = now.strftime("%H:%M")
    label_raw = cfg.weather.label.strip()[:4]
    label_prefix = f"{label_raw} " if label_raw else ""

    def _top_line(day: date, low: float, high: float) -> str:
        lo, hi = int(round(low)), int(round(high))
        tiny = theme.use_tiny_font
        spacing = theme.spacing
        limit = rect[2] - 2
        prefix_w = (
            text_width(label_prefix.upper(), tiny=tiny, spacing=spacing)
            if label_prefix
            else 0
        )
        avail = max(8, limit - prefix_w)
        candidates = [
            f"{_day_label(day)} {clock} {lo}° / {hi}°",
            f"{_day_label(day)} {clock} {lo}°/{hi}°",
            f"{_day_label(day, short=True)} {clock} {lo}°/{hi}°",
            f"{_WEEKDAYS_SHORT[day.weekday()]} {day.day} {clock} {lo}°/{hi}°",
        ]
        for candidate in candidates:
            if text_width(candidate.upper(), tiny=tiny, spacing=spacing) <= avail:
                return f"{label_prefix}{candidate}" if label_prefix else candidate
        chosen = candidates[-1]
        return f"{label_prefix}{chosen}" if label_prefix else chosen

    # Pages: "Sat 25th 21:16 10° / 14°" / "Cloudy 4%" + rain icon
    pages: list[tuple[str, str, int | None]] = []
    if cfg.weather.show_current:
        pages.append(
            (
                _top_line(today, data.low, data.high),
                _code_label(data.weather_code).title(),
                data.rain_chance,
            )
        )
    if cfg.weather.show_forecast and data.forecast:
        for day in data.forecast:
            if cfg.weather.show_current and day.day == today:
                continue
            pages.append(
                (
                    _top_line(day.day, day.low, day.high),
                    _code_label(day.weather_code).title(),
                    day.rain_chance,
                )
            )
    if not pages:
        _line(img, rect, theme, "NO WX", DIM, 0)
        return

    idx = int(time.time() // WEATHER_PAGE_SECONDS) % len(pages)
    top, cond, rain = pages[idx]

    x, y, w, h = rect
    tiny = theme.use_tiny_font
    spacing = theme.spacing
    line_h = theme.body_h + theme.line_gap
    yy = y + 1

    top_u = top.upper()
    while top_u and text_width(top_u, tiny=tiny, spacing=spacing) > w - 2:
        top_u = top_u[:-1]
    draw_text(img, top_u, x + 1, yy, CYAN, tiny=tiny, spacing=spacing)

    if line_h < h:
        yy2 = y + 1 + line_h
        # Cloudy 4% [rain icon]
        left = cond.upper()
        cursor = x + 1
        if rain is not None:
            left = f"{left} {rain}%"
        max_w = (w - 10) if rain is not None else (w - 2)
        while left and text_width(left, tiny=tiny, spacing=spacing) > max_w:
            left = left[:-1]
        cursor += draw_text(img, left, cursor, yy2, WHITE, tiny=tiny, spacing=spacing)
        if rain is not None:
            cursor += 2
            if cursor + 5 < x + w - 1:
                draw_tiny_rain_cloud(img, cursor, yy2)


def _paint_f1(
    img: Image.Image, rect: Rect, theme: Theme, http: httpx.Client, cfg: AppConfig
) -> None:
    race = _fetch_f1(http)
    f1 = cfg.f1
    sessions = filter_sessions(race, f1)
    max_title = 10 if rect[2] >= 40 else 8
    title = race_title(race.race_name, max_title)
    row = 0
    if f1.show_race_name:
        _line(img, rect, theme, title, RED, row)
        row += 1
    if not sessions:
        _line(img, rect, theme, "NO SESS", ORANGE, row)
        return

    line_h = theme.body_h + theme.line_gap
    rows_left = max(0, (rect[3] - 2) // max(1, line_h) - row)
    show_dt = f1.show_datetime and rect[2] >= 40 and rows_left >= 3

    if f1.mode == "list":
        for sess in sessions[: max(1, rows_left)]:
            if f1.show_countdown:
                _line(
                    img,
                    rect,
                    theme,
                    f"{sess.label} {_countdown(sess.start)}",
                    WHITE,
                    row,
                )
            else:
                _line(img, rect, theme, sess.label, WHITE, row)
            row += 1
            rows_left -= 1
            if show_dt and rows_left > 0:
                _line(img, rect, theme, _when_short(sess.start), YELLOW, row)
                row += 1
                rows_left -= 1
                if rows_left <= 1:
                    break
        return

    sess = sessions[0]
    # Tight half-tile: "Q 3H 4M" on one line under the GP name
    if rows_left <= 1 or rect[3] < 22:
        bits = [sess.label]
        if f1.show_countdown:
            bits.append(_countdown(sess.start))
        _line(img, rect, theme, " ".join(bits), CYAN, row)
        return

    _line(img, rect, theme, sess.label, CYAN, row)
    row += 1
    if f1.show_countdown:
        _line(img, rect, theme, _countdown(sess.start), WHITE, row)
        row += 1
    if show_dt:
        _line(img, rect, theme, _when_short(sess.start), YELLOW, row)


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
    # Line 1: name · Line 2: temp + humidity
    _line(img, rect, theme, label, CYAN, 0)
    bits: list[str] = []
    if show.show_temp and snap.temperature_c is not None:
        bits.append(f"{int(round(snap.temperature_c))}°")
    if show.show_humidity and snap.humidity is not None:
        bits.append(f"{int(round(snap.humidity))} %")
    if show.show_power:
        if snap.ac_on is True:
            bits.append("ON")
        elif snap.ac_on is False:
            bits.append("OFF")
    if bits:
        if snap.ac_on is True:
            color = GREEN
        elif snap.ac_on is False:
            color = ORANGE
        else:
            color = WHITE
        # Explicit gap between temp and humidity: "24°  60 %"
        _line(img, rect, theme, "  ".join(bits), color, 1)
    detail: list[str] = []
    if show.show_mode and snap.mode:
        detail.append(snap.mode[:4])
    if show.show_target and snap.target_c is not None:
        detail.append(f">{snap.target_c}C")
    if detail and rect[3] >= 22:
        _line(img, rect, theme, " ".join(detail), WHITE, 2)


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
        eta = _fetch_route(
            routes[0],
            cfg.traffic.api_key,
            http,
            timezone=_traffic_timezone(cfg),
        )
        color = _eta_color(eta.duration_traffic_min, _eta_baseline(eta))
        _line(img, rect, theme, eta.name.upper(), CYAN, 0)
        _line(img, rect, theme, f"{eta.duration_traffic_min}M", color, 1)
        return

    line_h = theme.body_h + theme.line_gap
    max_rows = max(1, (rect[3] - 2) // line_h)
    for i, route in enumerate(routes[:max_rows]):
        eta = _fetch_route(
            route,
            cfg.traffic.api_key,
            http,
            timezone=_traffic_timezone(cfg),
        )
        color = _eta_color(eta.duration_traffic_min, _eta_baseline(eta))
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
    target = targets[0]
    remaining = (_parse_target(target.at) - now).total_seconds()
    primary, _ = _format_remaining(remaining)
    # Compact remaining for narrow cells: "147D" instead of "147D 03H"
    if remaining > 86400:
        days = int(remaining) // 86400
        primary = f"{days}D"
    color = GREEN if remaining <= 0 else (RED if remaining < 86400 else ORANGE)
    # Line 1 label (neutral), line 2 countdown coloured by urgency
    _line(img, rect, theme, target.label, WHITE, 0)
    _line(img, rect, theme, primary, color, 1)


def _paint_bins(
    img: Image.Image,
    rect: Rect,
    cfg: AppConfig,
    theme: Theme,
) -> None:
    dues = _bins_dues(cfg)
    if not dues:
        _line(img, rect, theme, "BINS", DIM, 0)
        _line(img, rect, theme, "CLEAR", DIM, 1)
        return
    line1, line2, urgency = format_bin_lines(dues)
    if urgency <= 0:
        color = ORANGE
    elif urgency == 1:
        color = YELLOW
    else:
        color = WHITE
    _line(img, rect, theme, line1, color, 0)
    _line(img, rect, theme, line2, WHITE, 1)


def default_tiles(cfg: AppConfig) -> list[str]:
    tiles: list[str] = []
    if cfg.weather:
        tiles.append("weather")
    if cfg.bins:
        tiles.append("bins")
    if cfg.traffic:
        tiles.append("traffic")
    if cfg.sensibo:
        tiles.append("sensibo")
    if cfg.enable_f1:
        tiles.append("f1")
    if cfg.countdown:
        tiles.append("countdown")
    return visible_tiles(cfg, tiles)
