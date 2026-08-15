"""Whether the Pixoo should be showing the dashboard right now.

Daylight uses Open-Meteo sunrise/sunset (https://open-meteo.com/). The Pixoo 64
does not expose a local light or occupancy sensor over LAN.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from pixelpixoo.cache import TtlCache
from pixelpixoo.config import AppConfig
from pixelpixoo.schedule import is_schedule_active
from pixelpixoo.screens.sensibo import climate_suggests_home
from pixelpixoo.screens.weather import OPEN_METEO_URL

logger = logging.getLogger(__name__)

_SUN_TTL_SEC = 6 * 60 * 60
_sun_cache: TtlCache[tuple[datetime, datetime]] = TtlCache()


@dataclass(frozen=True)
class DisplayDecision:
    active: bool
    reason: str


def evaluate_display(cfg: AppConfig, http: httpx.Client) -> DisplayDecision:
    """AND together schedule windows, daylight, and Sensibo presence."""
    sched = cfg.schedule
    if sched.enabled and not is_schedule_active(sched):
        return DisplayDecision(False, "scheduled off")

    if sched.follow_sun:
        daylight = _is_daylight(cfg, http)
        if daylight is False:
            return DisplayDecision(False, "outside daylight")

    if sched.follow_sensibo:
        home = climate_suggests_home(cfg, http)
        if home is False:
            return DisplayDecision(False, "sensibo idle")

    if sched.enabled:
        return DisplayDecision(True, "in window")
    if sched.follow_sun or sched.follow_sensibo:
        return DisplayDecision(True, "sensors on")
    return DisplayDecision(True, "on")


def _geo(cfg: AppConfig) -> tuple[float, float, str] | None:
    if cfg.weather:
        tz = cfg.weather.timezone or cfg.schedule.timezone
        return cfg.weather.latitude, cfg.weather.longitude, tz
    if cfg.location:
        return cfg.location
    return None


def _is_daylight(cfg: AppConfig, http: httpx.Client) -> bool | None:
    geo = _geo(cfg)
    if geo is None:
        logger.warning("follow_sun is on but no weather lat/lon; ignoring")
        return None
    lat, lon, tz_name = geo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    window = _sun_window(lat, lon, tz_name, tz, http)
    if window is None:
        return None
    sunrise, sunset = window
    pad = timedelta(minutes=max(0, cfg.schedule.sun_pad_minutes))
    start = sunrise - pad
    end = sunset + pad
    return start <= now <= end


def _sun_window(
    lat: float,
    lon: float,
    tz_name: str,
    tz: ZoneInfo,
    http: httpx.Client,
) -> tuple[datetime, datetime] | None:
    today = datetime.now(tz).date().isoformat()
    key = f"{lat:.4f}|{lon:.4f}|{tz_name}|{today}"
    fresh = _sun_cache.get(key, _SUN_TTL_SEC)
    if fresh is not None:
        return fresh
    stale = _sun_cache.get_stale(key)
    try:
        response = http.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "sunrise,sunset",
                "timezone": tz_name,
                "forecast_days": 1,
            },
        )
        response.raise_for_status()
        daily = response.json().get("daily") or {}
        rise_raw = (daily.get("sunrise") or [None])[0]
        set_raw = (daily.get("sunset") or [None])[0]
        if not rise_raw or not set_raw:
            raise RuntimeError("Open-Meteo omitted sunrise/sunset")
        sunrise = datetime.fromisoformat(str(rise_raw))
        sunset = datetime.fromisoformat(str(set_raw))
        if sunrise.tzinfo is None:
            sunrise = sunrise.replace(tzinfo=tz)
        if sunset.tzinfo is None:
            sunset = sunset.replace(tzinfo=tz)
        pair = (sunrise, sunset)
        _sun_cache.set(key, pair)
        return pair
    except Exception:
        logger.exception("Sunrise/sunset fetch failed")
        return stale
