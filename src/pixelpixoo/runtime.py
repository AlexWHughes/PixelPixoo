"""Hot-reloadable push-loop runtime shared by CLI and web UI."""

from __future__ import annotations

import io
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from pixelpixoo.config import AppConfig, load_config
from pixelpixoo.pixoo_client import PixooClient
from pixelpixoo.renderer import error_frame
from pixelpixoo.schedule import is_schedule_active
from pixelpixoo.screens.composite import build_view_screens
from pixelpixoo.screens.countdown import CountdownScreen
from pixelpixoo.screens.f1 import F1Screen
from pixelpixoo.screens.sensibo import build_sensibo_screens
from pixelpixoo.screens.traffic import TrafficScreen
from pixelpixoo.screens.weather import WeatherScreen
from pixelpixoo.theme import theme_for

logger = logging.getLogger(__name__)


def build_screens(cfg: AppConfig, http: httpx.Client) -> list[Any]:
    # Explicit custom views always win
    if cfg.views:
        return build_view_screens(cfg, http)

    # Auto composite layouts
    if cfg.display.layout != "focus":
        composite = build_view_screens(cfg, http)
        if composite:
            return composite

    theme = theme_for(cfg.display.text_scale)
    traffic_tz = "Australia/Sydney"
    if cfg.weather and cfg.weather.timezone:
        traffic_tz = cfg.weather.timezone
    elif cfg.schedule and cfg.schedule.timezone:
        traffic_tz = cfg.schedule.timezone
    screens: list[Any] = []
    if cfg.weather is not None:
        screens.append(WeatherScreen(cfg.weather, client=http, theme=theme))
    if cfg.traffic is not None:
        for route in cfg.traffic.routes:
            screens.append(
                TrafficScreen(
                    route,
                    cfg.traffic,
                    client=http,
                    theme=theme,
                    timezone=traffic_tz,
                )
            )
    if cfg.sensibo is not None:
        screens.extend(build_sensibo_screens(cfg.sensibo, http, theme=theme))
    if cfg.enable_f1 and cfg.f1.enabled:
        screens.append(F1Screen(client=http, theme=theme, cfg=cfg.f1))
    for target in cfg.countdown:
        screens.append(CountdownScreen(target, theme=theme))
    return screens


@dataclass
class RuntimeStatus:
    running: bool = False
    preview_mode: bool = False
    pixoo_ip: str = ""
    screen_count: int = 0
    screen_names: list[str] = field(default_factory=list)
    current_screen: str | None = None
    last_screen: str | None = None
    last_push_at: str | None = None
    last_error: str | None = None
    pushes: int = 0
    errors: int = 0
    rotate_seconds: float = 18.0
    brightness: int = 80
    started_at: str | None = None
    reloads: int = 0
    schedule_active: bool = True
    schedule_enabled: bool = False


class PixelRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._reload = threading.Event()
        self._thread: threading.Thread | None = None
        self._cfg: AppConfig | None = None
        self._preview_dir: Path | None = None
        self._once = False
        self._status = RuntimeStatus()
        self._last_frames: dict[str, bytes] = {}
        self._last_images: dict[str, Image.Image] = {}

    @property
    def status(self) -> RuntimeStatus:
        with self._lock:
            return RuntimeStatus(**self._status.__dict__)

    def start(
        self,
        cfg: AppConfig | None = None,
        *,
        preview_dir: Path | None = None,
        once: bool = False,
    ) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Runtime already started")
            self._cfg = cfg or load_config()
            self._preview_dir = preview_dir
            self._once = once
            self._stop.clear()
            self._reload.clear()
            self._thread = threading.Thread(
                target=self._loop, name="pixelpixoo-loop", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def request_reload(self, cfg: AppConfig | None = None) -> None:
        with self._lock:
            # Always re-read disk when no cfg passed (UI Reload / external edits)
            self._cfg = cfg if cfg is not None else load_config()
            preview = os_environ_preview()
            self._preview_dir = Path(preview) if preview else None
        self._reload.set()

    def status_dict(self) -> dict[str, Any]:
        s = self.status
        return {
            "running": s.running,
            "preview_mode": s.preview_mode,
            "pixoo_ip": s.pixoo_ip,
            "screen_count": s.screen_count,
            "screen_names": s.screen_names,
            "current_screen": s.current_screen,
            "last_screen": s.last_screen,
            "last_push_at": s.last_push_at,
            "last_error": s.last_error,
            "pushes": s.pushes,
            "errors": s.errors,
            "rotate_seconds": s.rotate_seconds,
            "brightness": s.brightness,
            "started_at": s.started_at,
            "reloads": s.reloads,
            "schedule_active": s.schedule_active,
            "schedule_enabled": s.schedule_enabled,
        }

    def render_screen_png(self, name: str, *, scale: int = 8) -> bytes:
        cfg = self._cfg or load_config()
        with httpx.Client(timeout=20.0) as http:
            screens = build_screens(cfg, http)
            match = next((s for s in screens if getattr(s, "name", "") == name), None)
            if match is None and screens:
                # allow partial match e.g. sensibo:BED
                match = next(
                    (s for s in screens if name in getattr(s, "name", "")), None
                )
            if match is None:
                raise KeyError(f"Unknown screen: {name}")
            frame = match.render()
        return _png_bytes(frame, scale=scale)

    def render_all_previews(self, *, scale: int = 4) -> dict[str, bytes]:
        cfg = self._cfg or load_config()
        out: dict[str, bytes] = {}
        with httpx.Client(timeout=20.0) as http:
            for screen in build_screens(cfg, http):
                name = getattr(screen, "name", "screen")
                try:
                    frame = screen.render()
                    out[name] = _png_bytes(frame, scale=scale)
                    with self._lock:
                        self._last_frames[name] = out[name]
                except Exception as exc:
                    logger.exception("Preview failed for %s", name)
                    out[name] = _png_bytes(error_frame(str(exc)[:8]), scale=scale)
        return out

    def cached_frame(self, name: str) -> bytes | None:
        with self._lock:
            return self._last_frames.get(name)

    def test_pixoo(self) -> dict[str, Any]:
        cfg = self._cfg or load_config()
        client = PixooClient(cfg.pixoo_ip, timeout=5.0)
        try:
            client.send("Channel/GetIndex")
            return {"ok": True, "ip": cfg.pixoo_ip, "message": "Pixoo responded"}
        except Exception as exc:
            return {"ok": False, "ip": cfg.pixoo_ip, "message": str(exc)}
        finally:
            client.close()

    def _update_status(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._status, key, value)

    def _loop(self) -> None:
        self._update_status(
            running=True,
            started_at=datetime.now(timezone.utc).isoformat(),
            last_error=None,
        )
        http = httpx.Client(timeout=20.0)
        pixoo: PixooClient | None = None
        screens: list[Any] = []
        index = 0
        screen_was_off = False

        try:
            while not self._stop.is_set():
                with self._lock:
                    cfg = self._cfg or load_config()
                    preview_dir = self._preview_dir
                    once = self._once

                active = is_schedule_active(cfg.schedule)
                self._update_status(
                    schedule_active=active,
                    schedule_enabled=cfg.schedule.enabled,
                )
                if cfg.schedule.enabled and not active:
                    self._update_status(current_screen="(scheduled off)")
                    if preview_dir is None:
                        if pixoo is None:
                            pixoo = PixooClient(cfg.pixoo_ip)
                        if not screen_was_off and cfg.schedule.outside == "off":
                            try:
                                pixoo.set_screen(False)
                                screen_was_off = True
                                logger.info("Schedule inactive — Pixoo screen off")
                            except Exception:
                                logger.exception("Failed to turn Pixoo screen off")
                    self._interruptible_sleep(min(60.0, max(15.0, cfg.rotate_seconds)))
                    continue

                if screen_was_off and pixoo is not None and preview_dir is None:
                    try:
                        pixoo.bootstrap(cfg.brightness)
                        screen_was_off = False
                        logger.info("Schedule active — Pixoo screen on")
                    except Exception:
                        logger.exception("Failed to restore Pixoo after schedule")

                # Rebuild screens / client on reload or first pass
                if self._reload.is_set() or not screens:
                    self._reload.clear()
                    for screen in screens:
                        close = getattr(screen, "close", None)
                        if callable(close):
                            try:
                                close()
                            except Exception:
                                pass
                    if pixoo is not None:
                        pixoo.close()
                        pixoo = None
                        screen_was_off = False

                    screens = build_screens(cfg, http)
                    names = [getattr(s, "name", "?") for s in screens]
                    with self._lock:
                        self._last_images.clear()
                    self._update_status(
                        pixoo_ip=cfg.pixoo_ip,
                        screen_count=len(screens),
                        screen_names=names,
                        rotate_seconds=cfg.rotate_seconds,
                        brightness=cfg.brightness,
                        preview_mode=preview_dir is not None,
                        reloads=self._status.reloads + (1 if names else 0),
                    )
                    index = 0
                    if not screens:
                        self._update_status(
                            last_error="No screens enabled",
                            current_screen=None,
                        )
                        self._interruptible_sleep(5.0)
                        continue

                    if preview_dir is None:
                        pixoo = PixooClient(cfg.pixoo_ip)
                        try:
                            pixoo.bootstrap(cfg.brightness)
                        except Exception as exc:
                            logger.exception("Pixoo bootstrap failed")
                            self._update_status(last_error=f"Bootstrap: {exc}")
                    logger.info(
                        "Loop ready → %s with %d screen(s), preview=%s",
                        cfg.pixoo_ip,
                        len(screens),
                        bool(preview_dir),
                    )

                screen = screens[index % len(screens)]
                index += 1
                name = getattr(screen, "name", "?")
                self._update_status(current_screen=name)

                try:
                    frame = screen.render()
                except Exception as exc:
                    logger.exception("Screen %s crashed", name)
                    frame = error_frame("CRASH")
                    self._update_status(
                        last_error=f"{name}: {exc}",
                        errors=self._status.errors + 1,
                    )

                fade_spent = 0.0
                try:
                    if preview_dir is not None:
                        preview_dir.mkdir(parents=True, exist_ok=True)
                        out = preview_dir / f"{name.replace(':', '_')}.png"
                        frame.save(out)
                        logger.info("Wrote preview %s", out)
                    else:
                        assert pixoo is not None
                        prev = self._last_images.get(name)
                        fade_spent = self._push_crossfade(pixoo, prev, frame)
                        logger.info("Pushed %s", name)
                    with self._lock:
                        self._last_frames[name] = _png_bytes(frame, scale=8)
                        self._last_images[name] = frame.copy()
                    self._update_status(
                        last_screen=name,
                        last_push_at=datetime.now(timezone.utc).isoformat(),
                        pushes=self._status.pushes + 1,
                        last_error=None,
                    )
                except Exception as exc:
                    logger.exception("Failed to deliver frame for %s", name)
                    self._update_status(
                        last_error=f"push {name}: {exc}",
                        errors=self._status.errors + 1,
                    )

                if once and index >= len(screens):
                    break

                hold = max(1.0, cfg.rotate_seconds - fade_spent)
                self._interruptible_sleep(hold)
        finally:
            if pixoo is not None:
                pixoo.close()
            http.close()
            for screen in screens:
                close = getattr(screen, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            self._update_status(running=False, current_screen=None)

    def _push_crossfade(
        self,
        pixoo: PixooClient,
        prev: Image.Image | None,
        frame: Image.Image,
        *,
        steps: int = 2,
        step_sec: float = 0.04,
    ) -> float:
        """Quick blend from prev → frame. Returns wall time spent fading/pushing."""
        frame_rgb = frame.convert("RGB")
        started = time.monotonic()
        if prev is None or prev.size != frame_rgb.size:
            if self._stop.is_set() or self._reload.is_set():
                return time.monotonic() - started
            pixoo.push_image(frame_rgb)
            return time.monotonic() - started
        prev_rgb = prev.convert("RGB")
        # One mid-frame then final — keeps transition soft without stuttering
        for i in range(1, steps):
            if self._stop.is_set() or self._reload.is_set():
                return time.monotonic() - started
            blended = Image.blend(prev_rgb, frame_rgb, i / steps)
            pixoo.push_image(blended)
            self._interruptible_sleep(step_sec)
        if not self._stop.is_set() and not self._reload.is_set():
            pixoo.push_image(frame_rgb)
        return time.monotonic() - started

    def _interruptible_sleep(self, seconds: float) -> None:
        remaining = max(0.0, seconds)
        while remaining > 0 and not self._stop.is_set() and not self._reload.is_set():
            step = min(0.25, remaining)
            time.sleep(step)
            remaining -= step


def os_environ_preview() -> str:
    return os.environ.get("PIXELPIXOO_PREVIEW", "").strip()


def _png_bytes(image: Image.Image, *, scale: int = 1) -> bytes:
    img = image.convert("RGB")
    if scale > 1:
        img = img.resize(
            (img.width * scale, img.height * scale), Image.Resampling.NEAREST
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# Process-wide singleton
runtime = PixelRuntime()
