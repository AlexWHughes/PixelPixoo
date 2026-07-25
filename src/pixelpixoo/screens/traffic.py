"""Commute drive-time screens via Google Directions API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from PIL import Image

from pixelpixoo.config import TrafficConfig, TrafficRoute
from pixelpixoo.renderer import (
    BLACK,
    CYAN,
    GREEN,
    ORANGE,
    RED,
    WHITE,
    draw_centered,
    draw_label_bar,
    draw_text,
    error_frame,
    fit_scale,
    new_canvas,
)
from pixelpixoo.theme import Theme, theme_for

logger = logging.getLogger(__name__)

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
# Peak commute: refresh often; overnight: slower to save Directions quota
_TRAFFIC_TTL_DAY_SEC = 15 * 60
_TRAFFIC_TTL_NIGHT_SEC = 30 * 60
_TRAFFIC_DAY_START_HOUR = 6   # 06:00 inclusive
_TRAFFIC_DAY_END_HOUR = 20    # 20:00 exclusive
_DEFAULT_TZ = "Australia/Sydney"


@dataclass
class RouteEta:
    name: str
    duration_traffic_min: int
    duration_min: int
    summary: str
    avg_traffic_min: int | None = None


_route_cache: dict[str, tuple[float, RouteEta]] = {}
# Rolling travel-time history per route (samples from successful API refreshes)
_AVG_WINDOW = 16
_AVG_MIN_SAMPLES = 3
_traffic_history: dict[str, list[int]] = {}


def _cache_key(route: TrafficRoute) -> str:
    return f"{route.name}|{route.origin}|{route.destination}"


def _rolling_avg_min(key: str) -> int | None:
    hist = _traffic_history.get(key) or []
    if len(hist) < _AVG_MIN_SAMPLES:
        return None
    return max(1, round(sum(hist) / len(hist)))


def _record_traffic_sample(key: str, traffic_min: int) -> None:
    hist = _traffic_history.setdefault(key, [])
    hist.append(max(1, int(traffic_min)))
    if len(hist) > _AVG_WINDOW:
        del hist[:-_AVG_WINDOW]


def _traffic_ttl_seconds(tz_name: str = _DEFAULT_TZ) -> float:
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        now = datetime.now(ZoneInfo(_DEFAULT_TZ))
    if _TRAFFIC_DAY_START_HOUR <= now.hour < _TRAFFIC_DAY_END_HOUR:
        return float(_TRAFFIC_TTL_DAY_SEC)
    return float(_TRAFFIC_TTL_NIGHT_SEC)


def _fetch_route(
    route: TrafficRoute,
    api_key: str,
    client: httpx.Client,
    *,
    timezone: str = _DEFAULT_TZ,
) -> RouteEta:
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY not set")

    key = _cache_key(route)
    now_mono = time.monotonic()
    cached = _route_cache.get(key)
    ttl = _traffic_ttl_seconds(timezone)
    if cached and now_mono - cached[0] < ttl:
        return cached[1]

    params = {
        "origin": route.origin,
        "destination": route.destination,
        "mode": "driving",
        "departure_time": "now",
        "traffic_model": "best_guess",
        "key": api_key,
    }
    response = client.get(DIRECTIONS_URL, params=params)
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status")
    if status != "OK":
        raise RuntimeError(f"Directions status={status}: {payload.get('error_message')}")
    leg = payload["routes"][0]["legs"][0]
    duration = int(leg["duration"]["value"])
    if "duration_in_traffic" in leg:
        traffic = int(leg["duration_in_traffic"]["value"])
    else:
        traffic = duration
    summary = str(payload["routes"][0].get("summary", ""))
    traffic_min = max(1, round(traffic / 60))
    # Compare against prior samples only, then record this refresh
    avg_min = _rolling_avg_min(key)
    eta = RouteEta(
        name=route.name,
        duration_traffic_min=traffic_min,
        duration_min=max(1, round(duration / 60)),
        summary=summary,
        avg_traffic_min=avg_min,
    )
    _record_traffic_sample(key, traffic_min)
    _route_cache[key] = (time.monotonic(), eta)
    logger.debug(
        "Traffic refresh %s → %sm (avg %s, ttl %.0fs)",
        route.name,
        eta.duration_traffic_min,
        eta.avg_traffic_min,
        ttl,
    )
    return eta


def _eta_baseline(eta: RouteEta) -> int:
    """Prefer rolling cached average; fall back to Google typical duration."""
    if eta.avg_traffic_min is not None:
        return eta.avg_traffic_min
    return eta.duration_min


def _eta_color(traffic_min: int, baseline_min: int) -> tuple[int, int, int]:
    """Green when near/below baseline; warmer as delay grows."""
    if traffic_min <= baseline_min + 2:
        return GREEN
    if traffic_min <= baseline_min + 8:
        return ORANGE
    return RED


class TrafficScreen:
    """One slide for a single configured commute route."""

    def __init__(
        self,
        route: TrafficRoute,
        cfg: TrafficConfig,
        client: httpx.Client | None = None,
        theme: Theme | None = None,
        *,
        timezone: str = _DEFAULT_TZ,
    ) -> None:
        self.route = route
        self.cfg = cfg
        self.theme = theme or theme_for("normal")
        self.timezone = timezone or _DEFAULT_TZ
        self.name = f"traffic:{route.name}"
        self._client = client or httpx.Client(timeout=20.0)
        self._owns_client = client is None
        self._last: Image.Image | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def render(self) -> Image.Image:
        try:
            eta = _fetch_route(
                self.route,
                self.cfg.api_key,
                self._client,
                timezone=self.timezone,
            )
            img = self._paint(eta)
            self._last = img.copy()
            return img
        except Exception:
            logger.exception("Traffic fetch failed for %s", self.route.name)
            if self._last is not None:
                return self._last
            return error_frame(self.route.name[:8] or "TR")

    def _paint(self, eta: RouteEta) -> Image.Image:
        t = self.theme
        img = new_canvas(BLACK)
        draw_label_bar(
            img, "TRAFFIC", CYAN, height=t.header_h, tiny=t.use_tiny_font
        )
        y = t.header_h + 2
        draw_centered(
            img,
            eta.name.upper()[:10],
            y,
            WHITE,
            tiny=t.use_tiny_font,
            spacing=t.spacing,
        )
        y += t.body_h + t.line_gap

        minutes = f"{eta.duration_traffic_min}M"
        baseline = _eta_baseline(eta)
        color = _eta_color(eta.duration_traffic_min, baseline)
        scale = fit_scale(minutes, 60, prefer=t.hero, tiny=t.use_tiny_font)
        draw_centered(
            img,
            minutes,
            y,
            color,
            scale=scale,
            tiny=t.use_tiny_font,
            spacing=t.spacing,
        )
        y += (7 * scale if not t.use_tiny_font else 5) + t.line_gap

        delay = eta.duration_traffic_min - baseline
        vs = "AVG" if eta.avg_traffic_min is not None else "TYP"
        note = f"+{delay}M VS {vs}" if delay > 0 else "ON TIME"
        note_color = ORANGE if delay > 0 else GREEN
        if y + t.body_h <= 54:
            draw_centered(
                img,
                note,
                y,
                note_color,
                tiny=t.use_tiny_font,
                spacing=t.spacing,
            )

        if eta.summary:
            road = eta.summary.upper().replace(" ", "")[:10]
            draw_text(
                img, road, 2, 56, WHITE, tiny=t.use_tiny_font, spacing=t.spacing
            )
        return img
