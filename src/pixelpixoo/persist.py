"""Persist and serialize PixelPixoo configuration (YAML + .env secrets)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from pixelpixoo.config import (
    AppConfig,
    F1_SESSION_IDS,
    LABEL_MAX,
    load_config,
)
from pixelpixoo.schedule import schedule_public_dict

logger = logging.getLogger(__name__)

SECRET_KEYS = ("PIXOO_IP", "GOOGLE_MAPS_API_KEY", "SENSIBO_API_KEY", "PIXELPIXOO_PREVIEW")


def config_path() -> Path:
    return Path(os.environ.get("PIXELPIXOO_CONFIG", "config.yaml"))


def env_path() -> Path:
    return Path(os.environ.get("PIXELPIXOO_ENV", ".env"))


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return f"••••{value[-4:]}"


def read_env_file(path: Path | None = None) -> dict[str, str]:
    target = path or env_path()
    values: dict[str, str] = {}
    if not target.is_file():
        return values
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def write_env_updates(updates: dict[str, str | None], path: Path | None = None) -> None:
    """Update keys in .env. None means leave unchanged; '' clears the value."""
    target = path or env_path()
    existing_lines: list[str] = []
    if target.is_file():
        existing_lines = target.read_text(encoding="utf-8").splitlines()

    keys_done: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                val = updates[key]
                keys_done.add(key)
                if val is None:
                    new_lines.append(line)
                else:
                    new_lines.append(f"{key}={val}")
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key in keys_done or val is None:
            continue
        new_lines.append(f"{key}={val}")

    target.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(new_lines).rstrip() + "\n"
    target.write_text(text, encoding="utf-8")

    # Keep process env in sync for immediate reload
    for key, val in updates.items():
        if val is None:
            continue
        if val == "":
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def raw_yaml(path: Path | None = None) -> dict[str, Any]:
    target = path or config_path()
    if not target.is_file():
        return {}
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping")
    return data


def save_yaml(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    target.write_text(dumped, encoding="utf-8")


def public_config_dict(cfg: AppConfig | None = None) -> dict[str, Any]:
    """UI-safe config view (secrets masked, never raw)."""
    env = read_env_file()
    # Prefer live env, fall back to .env file
    google = os.environ.get("GOOGLE_MAPS_API_KEY") or env.get("GOOGLE_MAPS_API_KEY", "")
    sensibo = os.environ.get("SENSIBO_API_KEY") or env.get("SENSIBO_API_KEY", "")
    preview = os.environ.get("PIXELPIXOO_PREVIEW") or env.get("PIXELPIXOO_PREVIEW", "")

    loaded = cfg or load_config()
    raw = raw_yaml()

    weather_raw = raw.get("weather") if isinstance(raw.get("weather"), dict) else {}
    traffic_raw = raw.get("traffic") if isinstance(raw.get("traffic"), dict) else {}
    sensibo_raw = raw.get("sensibo") if isinstance(raw.get("sensibo"), dict) else {}

    weather_enabled = bool(loaded.weather) or bool(weather_raw.get("enabled", False))
    if weather_raw and weather_raw.get("enabled") is False:
        weather_enabled = False

    traffic_routes = []
    if loaded.traffic:
        traffic_routes = [
            {"name": r.name, "origin": r.origin, "destination": r.destination}
            for r in loaded.traffic.routes
        ]
    elif traffic_raw.get("routes"):
        traffic_routes = [
            {
                "name": str(r.get("name", ""))[:8],
                "origin": str(r.get("origin", "")),
                "destination": str(r.get("destination", "")),
            }
            for r in traffic_raw.get("routes", [])
            if isinstance(r, dict)
        ]

    sensibo_devices = []
    if loaded.sensibo:
        sensibo_devices = [
            {"label": d.label, "pod_id": d.pod_id, "room": d.room}
            for d in loaded.sensibo.devices
        ]
    elif sensibo_raw.get("devices"):
        sensibo_devices = [
            {
                "label": str(d.get("label", ""))[:LABEL_MAX],
                "pod_id": str(d.get("pod_id", "")),
                "room": str(d.get("room", "")),
            }
            for d in sensibo_raw.get("devices", [])
            if isinstance(d, dict)
        ]

    weather_block = {
        "enabled": weather_enabled,
        "latitude": loaded.weather.latitude if loaded.weather else weather_raw.get("latitude", -33.8688),
        "longitude": loaded.weather.longitude if loaded.weather else weather_raw.get("longitude", 151.2093),
        "label": loaded.weather.label if loaded.weather else weather_raw.get("label", "HOME"),
        "timezone": loaded.weather.timezone if loaded.weather else weather_raw.get("timezone", "Australia/Sydney"),
        "forecast_days": loaded.weather.forecast_days if loaded.weather else int(weather_raw.get("forecast_days", 1)),
        "show_current": loaded.weather.show_current if loaded.weather else bool(weather_raw.get("show_current", True)),
        "show_forecast": loaded.weather.show_forecast if loaded.weather else bool(weather_raw.get("show_forecast", False)),
    }

    return {
        "pixoo_ip": loaded.pixoo_ip,
        "rotate_seconds": loaded.rotate_seconds,
        "brightness": loaded.brightness,
        "preview_mode": bool(preview),
        "preview_dir": preview or "/preview",
        "enable_f1": loaded.enable_f1,
        "f1": {
            "enabled": loaded.f1.enabled,
            "sessions": list(loaded.f1.sessions),
            "mode": loaded.f1.mode,
            "show_countdown": loaded.f1.show_countdown,
            "show_datetime": loaded.f1.show_datetime,
            "show_race_name": loaded.f1.show_race_name,
            "show_country": loaded.f1.show_country,
            "session_options": list(F1_SESSION_IDS),
        },
        "weather": weather_block,
        "traffic": {
            "enabled": bool(traffic_routes) and (
                traffic_raw.get("enabled", True) is not False
            ),
            "routes": traffic_routes,
        },
        "google_maps_api_key_set": bool(google),
        "google_maps_api_key_hint": mask_secret(google),
        "sensibo": {
            "enabled": (
                False
                if sensibo_raw.get("enabled") is False
                else bool(loaded.sensibo)
            ),
            "devices": sensibo_devices,
            "auto_discover": len(sensibo_devices) == 0,
            "show_temp": loaded.sensibo.show_temp if loaded.sensibo else bool(sensibo_raw.get("show_temp", True)),
            "show_humidity": loaded.sensibo.show_humidity if loaded.sensibo else bool(sensibo_raw.get("show_humidity", True)),
            "show_power": loaded.sensibo.show_power if loaded.sensibo else bool(sensibo_raw.get("show_power", True)),
            "show_mode": loaded.sensibo.show_mode if loaded.sensibo else bool(sensibo_raw.get("show_mode", True)),
            "show_target": loaded.sensibo.show_target if loaded.sensibo else bool(sensibo_raw.get("show_target", True)),
            "show_room": loaded.sensibo.show_room if loaded.sensibo else bool(sensibo_raw.get("show_room", True)),
        },
        "sensibo_api_key_set": bool(sensibo),
        "sensibo_api_key_hint": mask_secret(sensibo),
        "countdown": [{"label": c.label, "at": c.at} for c in loaded.countdown],
        "display": {
            "text_scale": loaded.display.text_scale,
            "layout": loaded.display.layout,
            "show_header": loaded.display.show_header,
            "tiles": list(loaded.display.tiles),
            "row_pattern": list(loaded.display.row_pattern),
        },
        "tile_options": _tile_options(loaded, sensibo_devices, traffic_routes),
        "views": [
            {
                "name": v.name,
                "layout": v.layout,
                "text_scale": v.text_scale,
                "show_header": v.show_header,
                "tiles": list(v.tiles),
                "row_pattern": list(v.row_pattern),
            }
            for v in loaded.views
        ],
        "schedule": schedule_public_dict(loaded.schedule),
    }


def _tile_options(
    loaded: AppConfig,
    sensibo_devices: list[dict[str, str]],
    traffic_routes: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Checkbox catalog for the display tile picker."""
    options: list[dict[str, str]] = []
    if loaded.weather:
        options.append({"id": "weather", "label": "Weather"})
    if loaded.sensibo or sensibo_devices:
        options.append({"id": "sensibo", "label": "Sensibo (first)"})
        for d in sensibo_devices:
            label = (d.get("label") or d.get("room") or "AC")[:LABEL_MAX]
            if label:
                options.append({"id": f"sensibo:{label}", "label": f"Sensibo · {label}"})
    if loaded.traffic or traffic_routes:
        options.append({"id": "traffic", "label": "Traffic (first)"})
        for r in traffic_routes:
            name = (r.get("name") or "")[:8]
            if name:
                options.append({"id": f"traffic:{name}", "label": f"Traffic · {name}"})
    if loaded.enable_f1 and loaded.f1.enabled:
        options.append({"id": "f1", "label": "Next F1"})
    if loaded.countdown:
        options.append({"id": "countdown", "label": "Countdown (first)"})
        for c in loaded.countdown:
            options.append({"id": f"countdown:{c.label}", "label": f"Countdown · {c.label}"})
    # Always offer base ids so users can pre-select before enabling screens
    base = [
        ("weather", "Weather"),
        ("sensibo", "Sensibo"),
        ("traffic", "Traffic"),
        ("f1", "Next F1"),
        ("countdown", "Countdown"),
    ]
    seen = {o["id"] for o in options}
    for tid, label in base:
        if tid not in seen:
            options.append({"id": tid, "label": label})
    return options


def apply_config_payload(payload: dict[str, Any]) -> AppConfig:
    """Write YAML + optional secrets from UI payload, then reload."""
    if not isinstance(payload, dict):
        raise ValueError("Payload must be an object")

    rotate = float(payload.get("rotate_seconds", 18))
    brightness = int(payload.get("brightness", 80))
    enable_f1 = bool(payload.get("enable_f1", True))
    pixoo_ip = str(payload.get("pixoo_ip", "")).strip()
    if not pixoo_ip:
        raise ValueError("pixoo_ip is required")

    yaml_data: dict[str, Any] = {
        "pixoo_ip": pixoo_ip,
        "rotate_seconds": max(15.0, rotate),
        "brightness": max(0, min(100, brightness)),
        "enable_f1": enable_f1,
    }

    weather = payload.get("weather") or {}
    if weather.get("enabled", True):
        forecast_days = max(1, min(7, int(weather.get("forecast_days", 1))))
        yaml_data["weather"] = {
            "enabled": True,
            "latitude": float(weather.get("latitude", 0)),
            "longitude": float(weather.get("longitude", 0)),
            "label": str(weather.get("label", "HOME"))[:LABEL_MAX],
            "timezone": str(weather.get("timezone", "UTC")),
            "forecast_days": forecast_days,
            "show_current": bool(weather.get("show_current", True)),
            "show_forecast": bool(weather.get("show_forecast", forecast_days > 1)),
        }
    else:
        yaml_data["weather"] = {"enabled": False}

    f1 = payload.get("f1") or {}
    sessions = [
        str(s).lower().strip()
        for s in (f1.get("sessions") or [])
        if str(s).lower().strip() in F1_SESSION_IDS
    ]
    yaml_data["f1"] = {
        "enabled": bool(f1.get("enabled", enable_f1)),
        "sessions": sessions or list(F1_SESSION_IDS),
        "mode": str(f1.get("mode", "next")),
        "show_countdown": bool(f1.get("show_countdown", True)),
        "show_datetime": bool(f1.get("show_datetime", True)),
        "show_race_name": bool(f1.get("show_race_name", True)),
        "show_country": bool(f1.get("show_country", True)),
    }
    yaml_data["enable_f1"] = yaml_data["f1"]["enabled"]

    traffic = payload.get("traffic") or {}
    routes_in = traffic.get("routes") or []
    routes = []
    for r in routes_in:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", "")).strip()[:8]
        origin = str(r.get("origin", "")).strip()
        destination = str(r.get("destination", "")).strip()
        if name and origin and destination:
            routes.append({"name": name, "origin": origin, "destination": destination})
    yaml_data["traffic"] = {
        "enabled": bool(traffic.get("enabled", True)) and bool(routes),
        "routes": routes,
    }

    sensibo = payload.get("sensibo") or {}
    devices = []
    for d in sensibo.get("devices") or []:
        if not isinstance(d, dict):
            continue
        devices.append(
            {
                "label": str(d.get("label", ""))[:LABEL_MAX],
                "pod_id": str(d.get("pod_id", "")),
                "room": str(d.get("room", "")),
            }
        )
    # auto_discover => empty devices list
    if sensibo.get("auto_discover", len(devices) == 0):
        devices = []
    yaml_data["sensibo"] = {
        "enabled": bool(sensibo.get("enabled", True)),
        "devices": devices,
        "show_temp": bool(sensibo.get("show_temp", True)),
        "show_humidity": bool(sensibo.get("show_humidity", True)),
        "show_power": bool(sensibo.get("show_power", True)),
        "show_mode": bool(sensibo.get("show_mode", True)),
        "show_target": bool(sensibo.get("show_target", True)),
        "show_room": bool(sensibo.get("show_room", True)),
    }

    countdown = []
    for item in payload.get("countdown") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()[:LABEL_MAX]
        at = str(item.get("at", "")).strip()
        if label and at:
            countdown.append({"label": label, "at": at})
    yaml_data["countdown"] = countdown

    display = payload.get("display") or {}
    tiles = [
        str(t).strip()
        for t in (display.get("tiles") or [])
        if str(t).strip()
    ]
    row_pattern = [
        int(n)
        for n in (display.get("row_pattern") or [])
        if str(n).strip() in ("1", "2") or n in (1, 2)
    ]
    yaml_data["display"] = {
        "text_scale": str(display.get("text_scale", "normal")),
        "layout": str(display.get("layout", "focus")),
        "show_header": bool(display.get("show_header", True)),
        "tiles": tiles,
        "row_pattern": row_pattern,
    }

    views_out = []
    for item in payload.get("views") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        view_pattern = [
            int(n)
            for n in (item.get("row_pattern") or [])
            if str(n).strip() in ("1", "2") or n in (1, 2)
        ]
        views_out.append(
            {
                "name": str(item["name"])[:10],
                "layout": str(item.get("layout", "list")),
                "text_scale": str(item.get("text_scale", display.get("text_scale", "compact"))),
                "show_header": bool(item.get("show_header", True)),
                "tiles": [
                    str(t).strip()
                    for t in (item.get("tiles") or [])
                    if str(t).strip()
                ],
                "row_pattern": view_pattern,
            }
        )
    yaml_data["views"] = views_out

    schedule = payload.get("schedule") or {}
    windows = []
    for item in schedule.get("windows") or []:
        if not isinstance(item, dict):
            continue
        start = str(item.get("start", "")).strip()
        end = str(item.get("end", "")).strip()
        if not start or not end:
            continue
        days = item.get("days") or ["all"]
        if isinstance(days, str):
            days = [d.strip() for d in days.split(",") if d.strip()]
        windows.append({"days": days, "start": start, "end": end})
    yaml_data["schedule"] = {
        "enabled": bool(schedule.get("enabled", False)),
        "timezone": str(schedule.get("timezone", "Australia/Sydney")),
        "outside": str(schedule.get("outside", "off")),
        "windows": windows,
    }

    save_yaml(yaml_data)

    env_updates: dict[str, str | None] = {
        "PIXOO_IP": pixoo_ip,
    }

    # Secrets: omit / null / empty string with keep_secrets => unchanged;
    # explicit new value updates; clear_google / clear_sensibo flags wipe.
    if payload.get("clear_google_maps_api_key"):
        env_updates["GOOGLE_MAPS_API_KEY"] = ""
    elif "google_maps_api_key" in payload:
        key = payload.get("google_maps_api_key")
        if isinstance(key, str) and key.strip() and not key.startswith("••••"):
            env_updates["GOOGLE_MAPS_API_KEY"] = key.strip()

    if payload.get("clear_sensibo_api_key"):
        env_updates["SENSIBO_API_KEY"] = ""
    elif "sensibo_api_key" in payload:
        key = payload.get("sensibo_api_key")
        if isinstance(key, str) and key.strip() and not key.startswith("••••"):
            env_updates["SENSIBO_API_KEY"] = key.strip()

    if payload.get("preview_mode"):
        env_updates["PIXELPIXOO_PREVIEW"] = str(
            payload.get("preview_dir") or "/preview"
        )
    else:
        env_updates["PIXELPIXOO_PREVIEW"] = ""

    write_env_updates(env_updates)
    return load_config()


def configure_logging(*, verbose: bool = False) -> None:
    """Install logging filters that redact API keys from URLs."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    redactor = _SecretRedactFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)


class _SecretRedactFilter(logging.Filter):
    _patterns = (
        re.compile(r"(apiKey=)([^&\s]+)", re.I),
        re.compile(r"(key=)([^&\s]+)", re.I),
        re.compile(r"(GOOGLE_MAPS_API_KEY=)(\S+)", re.I),
        re.compile(r"(SENSIBO_API_KEY=)(\S+)", re.I),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = msg
        for pattern in self._patterns:
            redacted = pattern.sub(r"\1••••", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True
