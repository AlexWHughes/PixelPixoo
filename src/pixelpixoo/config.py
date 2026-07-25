"""Load app configuration from YAML and environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pixelpixoo.schedule import ScheduleConfig, parse_schedule
from pixelpixoo.theme import coerce_layout, coerce_text_scale, coerce_view_layout

logger = logging.getLogger(__name__)

F1_SESSION_IDS = (
    "fp1",
    "fp2",
    "fp3",
    "sq",
    "sprint",
    "quali",
    "race",
)

# Stored label length; Pixoo paint clips by pixel width
LABEL_MAX = 16


@dataclass
class WeatherConfig:
    latitude: float
    longitude: float
    label: str = "HOME"
    timezone: str = "UTC"
    forecast_days: int = 1  # 1 = current only; 2–7 include upcoming days
    show_current: bool = True
    show_forecast: bool = False


@dataclass
class TrafficRoute:
    name: str
    origin: str
    destination: str


@dataclass
class TrafficConfig:
    routes: list[TrafficRoute] = field(default_factory=list)
    api_key: str = ""


@dataclass
class CountdownTarget:
    label: str
    at: str


@dataclass
class SensiboDevice:
    label: str = ""
    pod_id: str = ""
    room: str = ""


@dataclass
class SensiboConfig:
    api_key: str
    devices: list[SensiboDevice] = field(default_factory=list)
    show_temp: bool = True
    show_humidity: bool = True
    show_power: bool = True
    show_mode: bool = True
    show_target: bool = True
    show_room: bool = True


@dataclass
class F1Config:
    enabled: bool = True
    # Which session types to include
    sessions: list[str] = field(
        default_factory=lambda: ["fp1", "fp2", "fp3", "sq", "sprint", "quali", "race"]
    )
    # next = focus on next upcoming; list = pack remaining weekend sessions
    mode: str = "next"
    show_countdown: bool = True
    show_datetime: bool = True
    show_race_name: bool = True
    show_country: bool = True


@dataclass
class DisplayConfig:
    text_scale: str = "normal"  # tiny | compact | normal | large
    layout: str = "focus"  # focus | dense | split | dashboard | custom
    show_header: bool = True
    tiles: list[str] = field(default_factory=list)
    # Custom dense rows: each entry is 1 (full width) or 2 (split). Tiles fill L→R, T→B.
    row_pattern: list[int] = field(default_factory=list)


@dataclass
class ViewConfig:
    name: str
    layout: str = "list"  # focus | list | split_h | split_v | grid_4 | rows
    text_scale: str = "compact"
    show_header: bool = True
    tiles: list[str] = field(default_factory=list)
    row_pattern: list[int] = field(default_factory=list)


@dataclass
class AppConfig:
    pixoo_ip: str
    rotate_seconds: float = 18.0
    brightness: int = 80
    weather: WeatherConfig | None = None
    traffic: TrafficConfig | None = None
    countdown: list[CountdownTarget] = field(default_factory=list)
    enable_f1: bool = True
    f1: F1Config = field(default_factory=F1Config)
    sensibo: SensiboConfig | None = None
    display: DisplayConfig = field(default_factory=DisplayConfig)
    views: list[ViewConfig] = field(default_factory=list)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def _env_from_dotenv() -> dict[str, str]:
    path = Path(os.environ.get("PIXELPIXOO_ENV", ".env"))
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def _secret(name: str) -> str:
    return os.environ.get(name, "") or _env_from_dotenv().get(name, "")


def _parse_row_pattern(raw: object) -> list[int]:
    if raw is None:
        return []
    values: list[object]
    if isinstance(raw, str):
        values = [p.strip() for p in raw.replace("-", ",").split(",") if p.strip()]
    elif isinstance(raw, list):
        values = list(raw)
    else:
        return []
    out: list[int] = []
    for value in values:
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if n in (1, 2):
            out.append(n)
    return out


def _parse_f1(raw: dict[str, Any] | None, enable_f1: bool) -> F1Config:
    data = raw if isinstance(raw, dict) else {}
    enabled = bool(data.get("enabled", enable_f1))
    sessions_raw = data.get("sessions")
    if isinstance(sessions_raw, list) and sessions_raw:
        sessions = [
            str(s).lower().strip()
            for s in sessions_raw
            if str(s).lower().strip() in F1_SESSION_IDS
        ]
    else:
        sessions = list(F1_SESSION_IDS)
    mode = str(data.get("mode", "next")).lower().strip()
    if mode not in ("next", "list"):
        mode = "next"
    return F1Config(
        enabled=enabled,
        sessions=sessions or ["race"],
        mode=mode,
        show_countdown=bool(data.get("show_countdown", True)),
        show_datetime=bool(data.get("show_datetime", True)),
        show_race_name=bool(data.get("show_race_name", True)),
        show_country=bool(data.get("show_country", True)),
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.environ.get("PIXELPIXOO_CONFIG", "config.yaml"))
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    pixoo_ip = os.environ.get("PIXOO_IP") or _secret("PIXOO_IP") or str(
        _require(raw, "pixoo_ip")
    )
    rotate_seconds = float(raw.get("rotate_seconds", 18))
    brightness = int(raw.get("brightness", 80))
    enable_f1 = bool(raw.get("enable_f1", True))
    f1 = _parse_f1(raw.get("f1") if isinstance(raw.get("f1"), dict) else None, enable_f1)

    weather: WeatherConfig | None = None
    if weather_raw := raw.get("weather"):
        if isinstance(weather_raw, dict) and weather_raw.get("enabled") is False:
            weather = None
        else:
            forecast_days = int(weather_raw.get("forecast_days", 1))
            forecast_days = max(1, min(7, forecast_days))
            show_forecast = bool(weather_raw.get("show_forecast", forecast_days > 1))
            weather = WeatherConfig(
                latitude=float(_require(weather_raw, "latitude")),
                longitude=float(_require(weather_raw, "longitude")),
                label=str(weather_raw.get("label", "HOME"))[:LABEL_MAX],
                timezone=str(weather_raw.get("timezone", "UTC")),
                forecast_days=forecast_days,
                show_current=bool(weather_raw.get("show_current", True)),
                show_forecast=show_forecast,
            )

    traffic: TrafficConfig | None = None
    if traffic_raw := raw.get("traffic"):
        if isinstance(traffic_raw, dict) and traffic_raw.get("enabled") is False:
            traffic = None
        else:
            routes = [
                TrafficRoute(
                    name=str(r["name"])[:8],
                    origin=str(r["origin"]),
                    destination=str(r["destination"]),
                )
                for r in traffic_raw.get("routes", [])
                if isinstance(r, dict) and "name" in r and "origin" in r and "destination" in r
            ]
            api_key = _secret("GOOGLE_MAPS_API_KEY") or str(
                traffic_raw.get("api_key", "")
            )
            if routes and api_key:
                traffic = TrafficConfig(routes=routes, api_key=api_key)
            elif routes and not api_key:
                logger.warning(
                    "traffic.routes configured but GOOGLE_MAPS_API_KEY is unset; skipping traffic"
                )

    countdown: list[CountdownTarget] = []
    for item in raw.get("countdown") or []:
        if isinstance(item, dict) and "label" in item and "at" in item:
            countdown.append(
                CountdownTarget(label=str(item["label"])[:LABEL_MAX], at=str(item["at"]))
            )

    sensibo: SensiboConfig | None = None
    sensibo_raw = raw.get("sensibo")
    sensibo_key = _secret("SENSIBO_API_KEY")
    if sensibo_raw is not None or sensibo_key:
        if isinstance(sensibo_raw, dict) and sensibo_raw.get("enabled") is False:
            sensibo = None
        else:
            show = sensibo_raw if isinstance(sensibo_raw, dict) else {}
            if isinstance(sensibo_raw, dict):
                sensibo_key = sensibo_key or str(sensibo_raw.get("api_key", ""))
                devices = []
                for item in sensibo_raw.get("devices") or []:
                    if not isinstance(item, dict):
                        continue
                    devices.append(
                        SensiboDevice(
                            label=str(item.get("label", "") or item.get("name", ""))[
                                :LABEL_MAX
                            ],
                            pod_id=str(item.get("pod_id", "")),
                            room=str(item.get("room", "")),
                        )
                    )
            else:
                devices = []
            if sensibo_key:
                sensibo = SensiboConfig(
                    api_key=sensibo_key,
                    devices=devices,
                    show_temp=bool(show.get("show_temp", True)),
                    show_humidity=bool(show.get("show_humidity", True)),
                    show_power=bool(show.get("show_power", True)),
                    show_mode=bool(show.get("show_mode", True)),
                    show_target=bool(show.get("show_target", True)),
                    show_room=bool(show.get("show_room", True)),
                )
            else:
                logger.warning(
                    "sensibo configured but SENSIBO_API_KEY is unset; skipping sensibo"
                )

    display_raw = raw.get("display") if isinstance(raw.get("display"), dict) else {}
    row_pattern = _parse_row_pattern(display_raw.get("row_pattern"))
    display = DisplayConfig(
        text_scale=coerce_text_scale(display_raw.get("text_scale", "normal")),
        layout=coerce_layout(display_raw.get("layout", "focus")),
        show_header=bool(display_raw.get("show_header", True)),
        tiles=[str(t).strip() for t in (display_raw.get("tiles") or []) if str(t).strip()],
        row_pattern=row_pattern,
    )

    views: list[ViewConfig] = []
    for item in raw.get("views") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        views.append(
            ViewConfig(
                name=str(item["name"])[:10],
                layout=coerce_view_layout(item.get("layout", "list")),
                text_scale=coerce_text_scale(
                    item.get("text_scale", display.text_scale)
                ),
                show_header=bool(item.get("show_header", display.show_header)),
                tiles=[str(t).strip() for t in (item.get("tiles") or []) if str(t).strip()],
                row_pattern=_parse_row_pattern(item.get("row_pattern")),
            )
        )

    schedule = parse_schedule(
        raw.get("schedule") if isinstance(raw.get("schedule"), dict) else None
    )

    return AppConfig(
        pixoo_ip=pixoo_ip,
        rotate_seconds=max(15.0, rotate_seconds),
        brightness=max(0, min(100, brightness)),
        weather=weather,
        traffic=traffic,
        countdown=countdown,
        enable_f1=f1.enabled,
        f1=f1,
        sensibo=sensibo,
        display=display,
        views=views,
        schedule=schedule,
    )
