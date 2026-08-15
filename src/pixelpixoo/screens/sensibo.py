"""Sensibo climate screens (room temp, humidity, AC state)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from PIL import Image

from pixelpixoo.cache import TtlCache
from pixelpixoo.config import LABEL_MAX, AppConfig, SensiboConfig
from pixelpixoo.renderer import (
    BLACK,
    BLUE,
    CYAN,
    GREEN,
    ORANGE,
    RED,
    WHITE,
    draw_centered,
    draw_label_bar,
    draw_text,
    fit_scale,
    new_canvas,
)
from pixelpixoo.screens.base import BaseScreen
from pixelpixoo.theme import Theme, theme_for

logger = logging.getLogger(__name__)

SENSIBO_BASE = "https://home.sensibo.com/api/v2"
POD_FIELDS = "id,room,acState,measurements"
# Sensibo rate limits are tight (~10 req / 10s with gzip). Prefer one bulk
# /users/me/pods call and reuse it across tiles/frames.
_POD_CACHE_TTL = 120.0
_pod_cache: TtlCache[list[dict]] = TtlCache()
_rate_limited_until: float = 0.0


@dataclass
class SensiboSnapshot:
    pod_id: str
    room: str
    temperature_c: float | None
    humidity: float | None
    ac_on: bool | None
    mode: str | None
    target_c: int | None
    occupancy: str | None = None  # occupied | vacant


_snapshot_cache: TtlCache[SensiboSnapshot] = TtlCache()


def _short_room(name: str, max_len: int = 8) -> str:
    cleaned = name.upper().strip()
    for word in ("ROOM", "THE", "BEDROOM", "LIVING"):
        cleaned = cleaned.replace(word, "").strip()
    cleaned = " ".join(cleaned.split()) or name.upper()
    return cleaned[:max_len]


def _snapshot_key(api_key: str, pod_id: str) -> str:
    return f"{api_key}:{pod_id}"


def _store_snapshots_from_pods(api_key: str, pods: list[dict]) -> None:
    """Warm per-pod snapshot cache from a bulk pods response."""
    for raw in pods:
        snap = _parse_pod(raw)
        if snap.pod_id:
            _snapshot_cache.set(_snapshot_key(api_key, snap.pod_id), snap)


def _cached_snapshot(api_key: str, pod_id: str) -> SensiboSnapshot | None:
    return _snapshot_cache.get(_snapshot_key(api_key, pod_id), _POD_CACHE_TTL)


def _stale_snapshot(api_key: str, pod_id: str) -> SensiboSnapshot | None:
    return _snapshot_cache.get_stale(_snapshot_key(api_key, pod_id))


def _mark_rate_limited(retry_after: float | None = None) -> None:
    global _rate_limited_until
    wait = retry_after if retry_after is not None else 60.0
    _rate_limited_until = max(_rate_limited_until, time.monotonic() + max(5.0, wait))
    logger.warning("Sensibo rate limited; backing off for %.0fs", wait)


def _under_rate_limit() -> bool:
    return time.monotonic() < _rate_limited_until


def _list_pods(api_key: str, client: httpx.Client) -> list[dict]:
    global _rate_limited_until
    fresh = _pod_cache.get(api_key, _POD_CACHE_TTL)
    if fresh is not None:
        return fresh
    stale = _pod_cache.get_stale(api_key)
    if _under_rate_limit() and stale is not None:
        return stale

    try:
        response = client.get(
            f"{SENSIBO_BASE}/users/me/pods",
            params={"apiKey": api_key, "fields": POD_FIELDS},
            headers={"Accept-Encoding": "gzip"},
        )
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            _mark_rate_limited(float(retry) if retry else None)
            if stale is not None:
                return stale
            response.raise_for_status()
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            retry = exc.response.headers.get("Retry-After")
            _mark_rate_limited(float(retry) if retry else None)
            if stale is not None:
                return stale
        raise

    payload = response.json()
    if payload.get("status") not in (None, "success"):
        raise RuntimeError(f"Sensibo status={payload.get('status')}")
    result = payload.get("result", payload)
    if not isinstance(result, list):
        raise RuntimeError("Unexpected Sensibo pods response")
    _pod_cache.set(api_key, result)
    _store_snapshots_from_pods(api_key, result)
    _rate_limited_until = 0.0
    logger.debug("Sensibo pods refresh (%d devices, ttl %.0fs)", len(result), _POD_CACHE_TTL)
    return result


def _measurement_dict(raw: object) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return raw[0]
    return None


def _parse_pod(raw: dict) -> SensiboSnapshot:
    pod_id = str(raw.get("id") or raw.get("uid") or "")
    room_obj = raw.get("room") or {}
    room = str(room_obj.get("name") or "ROOM")

    measurements = _measurement_dict(raw.get("measurements"))
    temperature: float | None = None
    humidity: float | None = None
    if measurements:
        if measurements.get("temperature") is not None:
            temperature = float(measurements["temperature"])
        if measurements.get("humidity") is not None:
            humidity = float(measurements["humidity"])

    ac = raw.get("acState") or {}
    ac_on = bool(ac["on"]) if "on" in ac else None
    mode = str(ac["mode"]).upper() if ac.get("mode") else None
    target = int(ac["targetTemperature"]) if ac.get("targetTemperature") is not None else None
    occupancy = _parse_occupancy(measurements)

    return SensiboSnapshot(
        pod_id=pod_id,
        room=room,
        temperature_c=temperature,
        humidity=humidity,
        ac_on=ac_on,
        mode=mode,
        target_c=target,
        occupancy=occupancy,
    )


def _parse_occupancy(measurements: dict | None) -> str | None:
    if not measurements:
        return None
    raw = measurements.get("occupancy")
    if raw is None:
        raw = measurements.get("roomOccupancy")
    if isinstance(raw, dict):
        raw = raw.get("status") or raw.get("type") or raw.get("state")
    if isinstance(raw, bool):
        return "occupied" if raw else "vacant"
    if raw is None and "motion" in measurements:
        return "occupied" if bool(measurements.get("motion")) else "vacant"
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("occupied", "present", "true", "1"):
        return "occupied"
    if text in ("vacant", "unoccupied", "empty", "away", "false", "0"):
        return "vacant"
    return None


def climate_suggests_home(cfg: AppConfig, client: httpx.Client) -> bool | None:
    """True if someone seems home (occupancy or any AC on). None if unknown."""
    if cfg.sensibo is None:
        logger.warning("follow_sensibo is on but Sensibo is not configured; ignoring")
        return None
    try:
        pods = _list_pods(cfg.sensibo.api_key, client)
    except Exception:
        logger.exception("Sensibo presence check failed")
        return None
    snaps = [s for s in (_parse_pod(p) for p in pods) if s.pod_id]
    if cfg.sensibo.devices:
        wanted = {d.pod_id for d in cfg.sensibo.devices if d.pod_id}
        rooms = {d.room.lower() for d in cfg.sensibo.devices if d.room}
        labels = {d.label.lower() for d in cfg.sensibo.devices if d.label}
        if wanted or rooms or labels:
            snaps = [
                s
                for s in snaps
                if s.pod_id in wanted
                or s.room.lower() in rooms
                or _short_room(s.room).lower() in labels
            ]
    if not snaps:
        return None
    occupied = [s.occupancy for s in snaps if s.occupancy]
    if occupied and any(flag == "occupied" for flag in occupied):
        return True
    ons = [s.ac_on for s in snaps if s.ac_on is not None]
    if ons:
        return any(ons)
    if occupied:
        return False
    return None


def resolve_devices(cfg: SensiboConfig, client: httpx.Client) -> list[tuple[str, str]]:
    """Return list of (label, pod_id) to display."""
    pods = _list_pods(cfg.api_key, client)
    parsed = [_parse_pod(p) for p in pods]
    by_id = {p.pod_id: p for p in parsed if p.pod_id}
    by_room = {p.room.lower(): p for p in parsed}

    if not cfg.devices:
        return [(_short_room(p.room), p.pod_id) for p in parsed if p.pod_id]

    resolved: list[tuple[str, str]] = []
    for device in cfg.devices:
        snap: SensiboSnapshot | None = None
        if device.pod_id and device.pod_id in by_id:
            snap = by_id[device.pod_id]
        elif device.room and device.room.lower() in by_room:
            snap = by_room[device.room.lower()]
        elif device.label:
            # Match label against room name loosely
            label_l = device.label.lower()
            for p in parsed:
                if label_l in p.room.lower() or _short_room(p.room).lower() == label_l:
                    snap = p
                    break
        if snap is None:
            logger.warning("Sensibo device not found: %s", device)
            continue
        label = device.label or _short_room(snap.room)
        resolved.append((label[:LABEL_MAX], snap.pod_id))
    return resolved


def fetch_snapshot(api_key: str, pod_id: str, client: httpx.Client) -> SensiboSnapshot:
    """Return pod state, preferring the cached bulk pods list over per-pod GETs."""
    cached = _cached_snapshot(api_key, pod_id)
    if cached is not None:
        return cached

    # Bulk list already includes measurements + acState for every pod.
    try:
        pods = _list_pods(api_key, client)
    except Exception:
        stale = _stale_snapshot(api_key, pod_id)
        if stale is not None:
            logger.warning("Sensibo list failed; using stale snapshot for %s", pod_id)
            return stale
        raise

    for raw in pods:
        snap = _parse_pod(raw)
        if snap.pod_id == pod_id:
            _snapshot_cache.set(_snapshot_key(api_key, pod_id), snap)
            return snap

    if _under_rate_limit():
        stale = _stale_snapshot(api_key, pod_id)
        if stale is not None:
            return stale
        raise RuntimeError("Sensibo rate limited and no cached data")

    # Unknown / new pod — one targeted fetch, then cache.
    try:
        response = client.get(
            f"{SENSIBO_BASE}/pods/{pod_id}",
            params={"apiKey": api_key, "fields": POD_FIELDS},
            headers={"Accept-Encoding": "gzip"},
        )
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            _mark_rate_limited(float(retry) if retry else None)
            stale = _stale_snapshot(api_key, pod_id)
            if stale is not None:
                return stale
            response.raise_for_status()
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            retry = exc.response.headers.get("Retry-After")
            _mark_rate_limited(float(retry) if retry else None)
            stale = _stale_snapshot(api_key, pod_id)
            if stale is not None:
                return stale
        raise

    payload = response.json()
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected Sensibo pod response")
    snap = _parse_pod(result)
    if snap.temperature_c is None or snap.humidity is None:
        # Fallback to dedicated measurements endpoint (rare)
        try:
            m = client.get(
                f"{SENSIBO_BASE}/pods/{pod_id}/measurements",
                params={"apiKey": api_key},
                headers={"Accept-Encoding": "gzip"},
            )
            if m.status_code != 429:
                m.raise_for_status()
                rows = m.json().get("result") or []
                if rows:
                    if snap.temperature_c is None and rows[0].get("temperature") is not None:
                        snap.temperature_c = float(rows[0]["temperature"])
                    if snap.humidity is None and rows[0].get("humidity") is not None:
                        snap.humidity = float(rows[0]["humidity"])
            else:
                _mark_rate_limited()
        except Exception:
            logger.debug("Sensibo measurements fallback failed for %s", pod_id, exc_info=True)
    _snapshot_cache.set(_snapshot_key(api_key, pod_id), snap)
    return snap


class SensiboScreen(BaseScreen):
    error_label = "AC"

    def __init__(
        self,
        label: str,
        pod_id: str,
        cfg: SensiboConfig,
        client: httpx.Client | None = None,
        theme: Theme | None = None,
    ) -> None:
        super().__init__(client, timeout=20.0)
        self.label = label
        self.pod_id = pod_id
        self.cfg = cfg
        self.theme = theme or theme_for("normal")
        self.name = f"sensibo:{label}"
        self.error_label = label[:8] or "AC"

    def _render(self) -> Image.Image:
        snap = fetch_snapshot(self.cfg.api_key, self.pod_id, self._client)
        return self._paint(snap)

    def _paint(self, snap: SensiboSnapshot) -> Image.Image:
        t = self.theme
        cfg = self.cfg
        img = new_canvas(BLACK)
        draw_label_bar(
            img, self.label.upper(), CYAN, height=t.header_h, tiny=t.use_tiny_font
        )
        left_y = t.header_h + 4
        right_y = t.header_h + 4

        if cfg.show_temp:
            if snap.temperature_c is not None:
                temp = f"{int(round(snap.temperature_c))}°"
                scale = fit_scale(temp, 36, prefer=t.hero, tiny=t.use_tiny_font)
                draw_text(
                    img,
                    temp,
                    4,
                    left_y,
                    WHITE,
                    scale=scale,
                    spacing=t.spacing,
                    tiny=t.use_tiny_font,
                )
                left_y += (7 * scale if not t.use_tiny_font else 5) + t.line_gap
            else:
                draw_text(
                    img,
                    "--°",
                    4,
                    left_y,
                    WHITE,
                    scale=t.hero,
                    spacing=t.spacing,
                    tiny=t.use_tiny_font,
                )
                left_y += t.hero_h + t.line_gap

        if cfg.show_humidity and snap.humidity is not None:
            hum = f"{int(round(snap.humidity))}%"
            draw_text(
                img, hum, 4, left_y, BLUE, spacing=t.spacing, tiny=t.use_tiny_font
            )
            left_y += t.body_h + t.line_gap

        if cfg.show_power:
            if snap.ac_on is True:
                status, color = "ON", GREEN
            elif snap.ac_on is False:
                status, color = "OFF", RED
            else:
                status, color = "AC", ORANGE
            draw_text(
                img,
                status,
                40,
                right_y,
                color,
                spacing=t.spacing,
                tiny=t.use_tiny_font,
            )
            right_y += t.body_h + t.line_gap

        if cfg.show_mode and snap.mode:
            draw_text(
                img,
                snap.mode[:6],
                40,
                right_y,
                WHITE,
                spacing=t.spacing,
                tiny=t.use_tiny_font,
            )
            right_y += t.body_h + t.line_gap

        if cfg.show_target and snap.target_c is not None:
            draw_text(
                img,
                f">{snap.target_c}C",
                40,
                right_y,
                ORANGE,
                spacing=t.spacing,
                tiny=t.use_tiny_font,
            )

        if cfg.show_room:
            room = _short_room(snap.room, 10)
            draw_centered(
                img, room, 54, WHITE, tiny=t.use_tiny_font, spacing=t.spacing
            )
        return img


def discover_pods(api_key: str, client: httpx.Client) -> list[dict]:
    """Return UI-friendly pod summaries for discovery."""
    pods = _list_pods(api_key, client)
    devices = []
    for raw in pods:
        snap = _parse_pod(raw)
        devices.append(
            {
                "pod_id": snap.pod_id,
                "room": snap.room,
                "temperature_c": snap.temperature_c,
                "humidity": snap.humidity,
                "ac_on": snap.ac_on,
                "mode": snap.mode,
                "target_c": snap.target_c,
            }
        )
    return devices


def build_sensibo_screens(
    cfg: SensiboConfig,
    client: httpx.Client,
    theme: Theme | None = None,
) -> list[SensiboScreen]:
    try:
        devices = resolve_devices(cfg, client)
    except Exception:
        logger.exception("Sensibo device discovery failed")
        return []
    if not devices:
        logger.warning("No Sensibo devices resolved")
        return []
    return [
        SensiboScreen(
            label=label, pod_id=pod_id, cfg=cfg, client=client, theme=theme
        )
        for label, pod_id in devices
    ]


__all__ = ["SensiboScreen", "build_sensibo_screens", "discover_pods"]
