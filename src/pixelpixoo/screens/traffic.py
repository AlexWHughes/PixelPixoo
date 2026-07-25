"""Commute drive-time screens via Google Directions API."""

from __future__ import annotations

import logging
from dataclasses import dataclass

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


@dataclass
class RouteEta:
    name: str
    duration_traffic_min: int
    duration_min: int
    summary: str


def _fetch_route(
    route: TrafficRoute, api_key: str, client: httpx.Client
) -> RouteEta:
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY not set")
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
    return RouteEta(
        name=route.name,
        duration_traffic_min=max(1, round(traffic / 60)),
        duration_min=max(1, round(duration / 60)),
        summary=summary,
    )


def _eta_color(traffic_min: int, base_min: int) -> tuple[int, int, int]:
    if traffic_min <= base_min + 2:
        return GREEN
    if traffic_min <= base_min + 10:
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
    ) -> None:
        self.route = route
        self.cfg = cfg
        self.theme = theme or theme_for("normal")
        self.name = f"traffic:{route.name}"
        self._client = client or httpx.Client(timeout=20.0)
        self._owns_client = client is None
        self._last: Image.Image | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def render(self) -> Image.Image:
        try:
            eta = _fetch_route(self.route, self.cfg.api_key, self._client)
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
        color = _eta_color(eta.duration_traffic_min, eta.duration_min)
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

        delay = eta.duration_traffic_min - eta.duration_min
        note = f"+{delay}M VS TYP" if delay > 0 else "ON TIME"
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
