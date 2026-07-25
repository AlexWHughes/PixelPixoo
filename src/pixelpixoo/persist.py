"""Persist and serialize PixelPixoo configuration (YAML + .env secrets)."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pixelpixoo.config import (
    AppConfig,
    COUNTDOWN_LABEL_MAX,
    F1_SESSION_IDS,
    LABEL_MAX,
    load_config,
)
from pixelpixoo.schedule import schedule_public_dict
from pixelpixoo.screens.bins import LABEL_MAX as BIN_LABEL_MAX

logger = logging.getLogger(__name__)

_WEEKDAY_YAML = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

SECRET_KEYS = ("PIXOO_IP", "GOOGLE_MAPS_API_KEY", "SENSIBO_API_KEY", "PIXELPIXOO_PREVIEW")
EXPORT_FORMAT = "pixelpixoo-config"
EXPORT_VERSION = 3
_IMPORT_DROP_KEYS = frozenset(
    {
        "tile_options",
        "google_maps_api_key_set",
        "google_maps_api_key_hint",
        "sensibo_api_key_set",
        "sensibo_api_key_hint",
        "session_options",
        "clear_google_maps_api_key",
        "clear_sensibo_api_key",
        "yaml",
        "format",
        "version",
        "exported_at",
    }
)


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
        "bins": _bins_public(loaded, raw),
        "display": {
            "text_scale": loaded.display.text_scale,
            "layout": loaded.display.layout,
            "show_header": loaded.display.show_header,
            "show_borders": loaded.display.show_borders,
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
                "show_borders": v.show_borders,
                "tiles": list(v.tiles),
                "row_pattern": list(v.row_pattern),
            }
            for v in loaded.views
        ],
        "schedule": schedule_public_dict(loaded.schedule),
    }


def export_config_bundle(form_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Full portable backup of the **saved** config (UI shape + raw secrets).

    Prefer saving the live form via PUT ``/api/config`` first, then calling this
    (GET ``/api/config/export``). Optional ``form_payload`` still builds a bundle
    without writing disk — used as a fallback.
    """
    env = read_env_file()
    google = os.environ.get("GOOGLE_MAPS_API_KEY") or env.get("GOOGLE_MAPS_API_KEY", "")
    sensibo = os.environ.get("SENSIBO_API_KEY") or env.get("SENSIBO_API_KEY", "")

    if form_payload and isinstance(form_payload, dict) and form_payload.get("pixoo_ip"):
        config = _export_config_from_form(form_payload, google=google, sensibo=sensibo)
        yaml_snapshot = None
    else:
        config = _export_config_from_saved(google=google, sensibo=sensibo)
        yaml_snapshot = raw_yaml()

    if not str(config.get("pixoo_ip", "")).strip():
        raise ValueError("pixoo_ip is required for export")

    bundle: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
    }
    if yaml_snapshot is not None:
        bundle["yaml"] = yaml_snapshot
    return bundle


def _usable_secret(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip() and not value.startswith("••••"):
        return value.strip()
    return fallback


def _normalize_display_export(display: Any) -> dict[str, Any]:
    d = display if isinstance(display, dict) else {}
    tiles = [str(t).strip() for t in (d.get("tiles") or []) if str(t).strip()]
    row_pattern = [
        int(n)
        for n in (d.get("row_pattern") or [])
        if str(n).strip() in ("1", "2") or n in (1, 2)
    ]
    return {
        "text_scale": str(d.get("text_scale") or "normal"),
        "layout": str(d.get("layout") or "focus"),
        "show_header": bool(d.get("show_header", True)),
        "show_borders": bool(d.get("show_borders", True)),
        "tiles": tiles,
        "row_pattern": row_pattern,
    }


def _normalize_views_export(views: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in views or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        row_pattern = [
            int(n)
            for n in (item.get("row_pattern") or [])
            if str(n).strip() in ("1", "2") or n in (1, 2)
        ]
        out.append(
            {
                "name": str(item["name"])[:10],
                "layout": str(item.get("layout", "list")),
                "text_scale": str(item.get("text_scale", "compact")),
                "show_header": bool(item.get("show_header", True)),
                "show_borders": bool(item.get("show_borders", True)),
                "tiles": [
                    str(t).strip() for t in (item.get("tiles") or []) if str(t).strip()
                ],
                "row_pattern": row_pattern,
            }
        )
    return out


def _export_config_from_form(
    form_payload: dict[str, Any], *, google: str, sensibo: str
) -> dict[str, Any]:
    config = dict(form_payload)
    for key in _IMPORT_DROP_KEYS:
        config.pop(key, None)

    f1 = config.get("f1")
    if isinstance(f1, dict):
        f1 = dict(f1)
        f1.pop("session_options", None)
        config["f1"] = f1

    config["display"] = _normalize_display_export(config.get("display"))
    config["views"] = _normalize_views_export(config.get("views"))
    config["countdown"] = [
        {"label": str(c.get("label", "")), "at": str(c.get("at", ""))}
        for c in (config.get("countdown") or [])
        if isinstance(c, dict) and c.get("label") and c.get("at")
    ]
    config["bins"] = dict(config.get("bins") or {}) if isinstance(config.get("bins"), dict) else {}
    config["schedule"] = (
        dict(config.get("schedule") or {})
        if isinstance(config.get("schedule"), dict)
        else {}
    )
    config["weather"] = (
        dict(config.get("weather") or {})
        if isinstance(config.get("weather"), dict)
        else {}
    )
    config["traffic"] = (
        dict(config.get("traffic") or {})
        if isinstance(config.get("traffic"), dict)
        else {}
    )
    sensibo_block = (
        dict(config.get("sensibo") or {})
        if isinstance(config.get("sensibo"), dict)
        else {}
    )
    # Explicit device pins must survive backup/restore
    devices = [
        d
        for d in (sensibo_block.get("devices") or [])
        if isinstance(d, dict) and (d.get("pod_id") or d.get("room") or d.get("label"))
    ]
    sensibo_block["devices"] = devices
    sensibo_block["auto_discover"] = not bool(devices)
    config["sensibo"] = sensibo_block
    config["google_maps_api_key"] = _usable_secret(
        config.get("google_maps_api_key"), google
    )
    config["sensibo_api_key"] = _usable_secret(config.get("sensibo_api_key"), sensibo)
    config["pixoo_ip"] = str(config.get("pixoo_ip") or "").strip()
    config["preview_mode"] = bool(config.get("preview_mode"))
    config["preview_dir"] = str(config.get("preview_dir") or "/preview")
    config["enable_f1"] = bool(config.get("enable_f1", True))
    config["rotate_seconds"] = float(config.get("rotate_seconds", 18))
    config["brightness"] = int(config.get("brightness", 80))
    return config


def _export_config_from_saved(*, google: str, sensibo: str) -> dict[str, Any]:
    """Build export payload from on-disk YAML + live secrets (source of truth)."""
    pub = public_config_dict()
    raw = raw_yaml()
    f1 = dict(pub.get("f1") or {})
    f1.pop("session_options", None)

    # Prefer raw YAML for layout/views so nothing is lost through UI shaping
    display = _normalize_display_export(raw.get("display") or pub.get("display"))
    views = _normalize_views_export(raw.get("views") if "views" in raw else pub.get("views"))

    weather = dict(pub.get("weather") or {})
    if isinstance(raw.get("weather"), dict):
        # Keep enabled flag + coords from disk when present
        weather = {**weather, **{k: v for k, v in raw["weather"].items() if k != "api_key"}}

    traffic = dict(pub.get("traffic") or {})
    if isinstance(raw.get("traffic"), dict):
        traffic["enabled"] = raw["traffic"].get("enabled", traffic.get("enabled", True))
        if raw["traffic"].get("routes") is not None:
            traffic["routes"] = raw["traffic"]["routes"]

    sensibo_block = dict(pub.get("sensibo") or {})
    if isinstance(raw.get("sensibo"), dict):
        sensibo_block = {
            **sensibo_block,
            **{k: v for k, v in raw["sensibo"].items() if k != "api_key"},
        }
    devices = [
        d
        for d in (sensibo_block.get("devices") or [])
        if isinstance(d, dict)
    ]
    sensibo_block["devices"] = devices
    sensibo_block["auto_discover"] = not bool(devices)

    bins = dict(pub.get("bins") or {})
    if isinstance(raw.get("bins"), dict):
        bins = {**bins, **raw["bins"]}

    schedule = dict(pub.get("schedule") or {})
    if isinstance(raw.get("schedule"), dict):
        schedule = {**schedule, **raw["schedule"]}

    countdown = pub.get("countdown") or []
    if isinstance(raw.get("countdown"), list):
        countdown = raw["countdown"]

    return {
        "pixoo_ip": str(raw.get("pixoo_ip") or pub.get("pixoo_ip") or "").strip(),
        "rotate_seconds": raw.get("rotate_seconds", pub.get("rotate_seconds", 18)),
        "brightness": raw.get("brightness", pub.get("brightness", 80)),
        "preview_mode": bool(pub.get("preview_mode")),
        "preview_dir": pub.get("preview_dir") or "/preview",
        "enable_f1": bool(raw.get("enable_f1", pub.get("enable_f1", True))),
        "f1": f1 if not isinstance(raw.get("f1"), dict) else {**f1, **raw["f1"]},
        "weather": weather,
        "traffic": traffic,
        "sensibo": sensibo_block,
        "countdown": countdown,
        "bins": bins,
        "display": display,
        "views": views,
        "schedule": schedule,
        "google_maps_api_key": google,
        "sensibo_api_key": sensibo,
    }


def normalize_import_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Accept a bundle or a raw UI-shaped config object."""
    if not isinstance(body, dict):
        raise ValueError("Import payload must be a JSON object")

    if body.get("format") == EXPORT_FORMAT:
        config = body.get("config")
        if not isinstance(config, dict):
            # Fall back to yaml snapshot + secrets if present
            if isinstance(body.get("yaml"), dict):
                config = _payload_from_yaml_snapshot(
                    body["yaml"],
                    google=str(body.get("google_maps_api_key") or ""),
                    sensibo=str(body.get("sensibo_api_key") or ""),
                )
            else:
                raise ValueError("Bundle missing config object")
        else:
            config = dict(config)
            # Fill gaps from yaml snapshot when config is partial
            if isinstance(body.get("yaml"), dict):
                config = _merge_yaml_into_config(config, body["yaml"])
        payload = config
    elif "config" in body and isinstance(body.get("config"), dict) and "pixoo_ip" not in body:
        payload = dict(body["config"])
    else:
        payload = dict(body)

    for key in _IMPORT_DROP_KEYS:
        payload.pop(key, None)

    f1 = payload.get("f1")
    if isinstance(f1, dict):
        f1 = dict(f1)
        f1.pop("session_options", None)
        payload["f1"] = f1

    payload["display"] = _normalize_display_export(payload.get("display"))
    payload["views"] = _normalize_views_export(payload.get("views"))

    sensibo_block = payload.get("sensibo")
    if isinstance(sensibo_block, dict):
        sensibo_block = dict(sensibo_block)
        devices = [
            d
            for d in (sensibo_block.get("devices") or [])
            if isinstance(d, dict) and (d.get("pod_id") or d.get("room") or d.get("label"))
        ]
        sensibo_block["devices"] = devices
        # Never wipe pinned devices during restore
        sensibo_block["auto_discover"] = not bool(devices)
        payload["sensibo"] = sensibo_block

    # Full replace for secrets when keys are present (empty ⇒ clear)
    if "google_maps_api_key" in payload:
        key = payload.get("google_maps_api_key")
        if not (isinstance(key, str) and key.strip() and not str(key).startswith("••••")):
            payload["clear_google_maps_api_key"] = True
            payload["google_maps_api_key"] = ""
    if "sensibo_api_key" in payload:
        key = payload.get("sensibo_api_key")
        if not (isinstance(key, str) and key.strip() and not str(key).startswith("••••")):
            payload["clear_sensibo_api_key"] = True
            payload["sensibo_api_key"] = ""

    if not str(payload.get("pixoo_ip", "")).strip():
        raise ValueError("Import config requires pixoo_ip")
    return payload


def _merge_yaml_into_config(config: dict[str, Any], yaml_data: dict[str, Any]) -> dict[str, Any]:
    """Ensure display/views/screens from yaml fill any holes in config."""
    merged = dict(config)
    if not merged.get("display") and yaml_data.get("display"):
        merged["display"] = yaml_data["display"]
    if not merged.get("views") and yaml_data.get("views") is not None:
        merged["views"] = yaml_data["views"]
    for key in (
        "weather",
        "traffic",
        "sensibo",
        "countdown",
        "bins",
        "schedule",
        "f1",
        "enable_f1",
        "rotate_seconds",
        "brightness",
        "pixoo_ip",
    ):
        if key not in merged or merged[key] in (None, {}, []):
            if key in yaml_data:
                merged[key] = yaml_data[key]
    return merged


def _payload_from_yaml_snapshot(
    yaml_data: dict[str, Any], *, google: str, sensibo: str
) -> dict[str, Any]:
    return {
        "pixoo_ip": str(yaml_data.get("pixoo_ip") or "").strip(),
        "rotate_seconds": yaml_data.get("rotate_seconds", 18),
        "brightness": yaml_data.get("brightness", 80),
        "preview_mode": False,
        "preview_dir": "/preview",
        "enable_f1": bool(yaml_data.get("enable_f1", True)),
        "f1": yaml_data.get("f1") or {},
        "weather": yaml_data.get("weather") or {},
        "traffic": yaml_data.get("traffic") or {},
        "sensibo": yaml_data.get("sensibo") or {},
        "countdown": yaml_data.get("countdown") or [],
        "bins": yaml_data.get("bins") or {},
        "display": yaml_data.get("display") or {},
        "views": yaml_data.get("views") or [],
        "schedule": yaml_data.get("schedule") or {},
        "google_maps_api_key": google,
        "sensibo_api_key": sensibo,
    }


def _bins_public(loaded: AppConfig, raw: dict[str, Any]) -> dict[str, Any]:
    bins_raw = raw.get("bins") if isinstance(raw.get("bins"), dict) else {}
    if loaded.bins:
        streams = [
            {
                "label": s.label,
                "weekday": _WEEKDAY_YAML[s.weekday],
                "every_weeks": s.every_weeks,
                "anchor": s.anchor,
            }
            for s in loaded.bins.streams
        ]
        return {
            "enabled": True,
            "timezone": loaded.bins.timezone,
            "lead_days": loaded.bins.lead_days,
            "eve_before": loaded.bins.eve_before,
            "streams": streams,
        }
    streams = []
    for item in bins_raw.get("streams") or []:
        if not isinstance(item, dict):
            continue
        streams.append(
            {
                "label": str(item.get("label", ""))[:BIN_LABEL_MAX],
                "weekday": str(item.get("weekday", item.get("day", "wed"))),
                "every_weeks": int(item.get("every_weeks", item.get("every", 1)) or 1),
                "anchor": str(item.get("anchor", "") or ""),
            }
        )
    return {
        "enabled": bool(bins_raw.get("enabled", False)),
        "timezone": str(bins_raw.get("timezone", "Australia/Sydney")),
        "lead_days": int(bins_raw.get("lead_days", 1)),
        "eve_before": bool(bins_raw.get("eve_before", True)),
        "streams": streams,
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
    if loaded.bins:
        options.append({"id": "bins", "label": "Bin night (conditional)"})
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
        ("bins", "Bin night"),
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
    # auto_discover with no pins ⇒ empty list; explicit devices always kept
    if devices:
        pass
    elif sensibo.get("auto_discover", True):
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
        label = str(item.get("label", "")).strip()[:COUNTDOWN_LABEL_MAX]
        at = str(item.get("at", "")).strip()
        if label and at:
            countdown.append({"label": label, "at": at})
    yaml_data["countdown"] = countdown

    bins = payload.get("bins") or {}
    bin_streams = []
    for item in bins.get("streams") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip().upper()[:BIN_LABEL_MAX]
        weekday = str(item.get("weekday", item.get("day", ""))).strip().lower()
        if not label or not weekday:
            continue
        every = max(1, min(8, int(item.get("every_weeks", item.get("every", 1)) or 1)))
        anchor = str(item.get("anchor", "") or "").strip()[:10]
        entry: dict[str, Any] = {
            "label": label,
            "weekday": weekday,
            "every_weeks": every,
        }
        if anchor:
            entry["anchor"] = anchor
        bin_streams.append(entry)
    yaml_data["bins"] = {
        "enabled": bool(bins.get("enabled", True)) and bool(bin_streams),
        "timezone": str(bins.get("timezone", "Australia/Sydney")),
        "lead_days": max(0, min(6, int(bins.get("lead_days", 1)))),
        "eve_before": bool(bins.get("eve_before", True)),
        "streams": bin_streams,
    }

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
        "show_borders": bool(display.get("show_borders", True)),
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
                "show_borders": bool(item.get("show_borders", display.get("show_borders", True))),
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
