"""Tests for pixelpixoo.config YAML/env loading."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from pixelpixoo.config import load_config


def write_config(tmp_path: Path, data: dict) -> None:
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(data), encoding="utf-8"
    )


BASE = {
    "pixoo_ip": "192.168.1.42",
    "weather": {"latitude": -33.86, "longitude": 151.2, "timezone": "UTC"},
}


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_non_mapping_root_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_config(path)


def test_minimal_config(tmp_path: Path) -> None:
    write_config(tmp_path, BASE)
    cfg = load_config()
    assert cfg.pixoo_ip == "192.168.1.42"
    assert cfg.weather is not None and cfg.weather.latitude == -33.86
    assert cfg.location == (-33.86, 151.2, "UTC")


def test_missing_pixoo_ip_raises(tmp_path: Path) -> None:
    write_config(tmp_path, {"rotate_seconds": 20})
    with pytest.raises(ValueError, match="pixoo_ip"):
        load_config()


class TestClamping:
    def test_brightness_and_rotate(self, tmp_path: Path) -> None:
        write_config(tmp_path, {**BASE, "brightness": 500, "rotate_seconds": 1})
        cfg = load_config()
        assert cfg.brightness == 100
        assert cfg.rotate_seconds == 15.0

    def test_forecast_days(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {**BASE, "weather": {**BASE["weather"], "forecast_days": 99}},
        )
        cfg = load_config()
        assert cfg.weather is not None and cfg.weather.forecast_days == 7

    def test_label_truncated(self, tmp_path: Path) -> None:
        long = "X" * 40
        write_config(
            tmp_path, {**BASE, "weather": {**BASE["weather"], "label": long}}
        )
        cfg = load_config()
        assert cfg.weather is not None
        assert len(cfg.weather.label) == 16


class TestFeatureSwitches:
    def test_weather_disabled(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {**BASE, "weather": {**BASE["weather"], "enabled": False}},
        )
        cfg = load_config()
        assert cfg.weather is None

    def test_countdown_disabled_flag(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {
                **BASE,
                "enable_countdown": False,
                "countdown": [{"label": "TRIP", "at": "2030-01-01T00:00:00Z"}],
            },
        )
        cfg = load_config()
        assert cfg.enable_countdown is False
        assert len(cfg.countdown) == 1  # kept but gated at runtime

    def test_traffic_without_key_is_dropped(self, tmp_path: Path, caplog) -> None:
        write_config(
            tmp_path,
            {
                **BASE,
                "traffic": {
                    "routes": [
                        {"name": "WORK", "origin": "A", "destination": "B"}
                    ]
                },
            },
        )
        with caplog.at_level(logging.WARNING):
            cfg = load_config()
        assert cfg.traffic is None
        assert any("GOOGLE_MAPS_API_KEY" in r.message for r in caplog.records)

    def test_traffic_with_env_key(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k-test")
        write_config(
            tmp_path,
            {
                **BASE,
                "traffic": {
                    "routes": [
                        {"name": "WORK", "origin": "A", "destination": "B"}
                    ]
                },
            },
        )
        cfg = load_config()
        assert cfg.traffic is not None and cfg.traffic.api_key == "k-test"

    def test_sensibo_from_env_file(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SENSIBO_API_KEY=sk-env\n", encoding="utf-8")
        write_config(tmp_path, BASE)
        cfg = load_config()
        assert cfg.sensibo is not None and cfg.sensibo.api_key == "sk-env"

    def test_sensibo_disabled_beats_key(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SENSIBO_API_KEY=sk-env\n", encoding="utf-8")
        write_config(tmp_path, {**BASE, "sensibo": {"enabled": False}})
        assert load_config().sensibo is None


class TestBins:
    def test_valid_streams(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {
                **BASE,
                "bins": {
                    "streams": [
                        {
                            "label": "recycling",
                            "weekday": "wed",
                            "every_weeks": 2,
                            "anchor": "2025-01-01",
                            "color": "#FF0000",
                        }
                    ]
                },
            },
        )
        cfg = load_config()
        bins = cfg.bins
        assert bins is not None
        stream = bins.streams[0]
        assert stream.label == "RECYCLING"
        assert stream.weekday == 2
        assert stream.every_weeks == 2
        assert stream.color == "#ff0000"

    def test_fortnightly_without_anchor_downgrades(
        self, tmp_path: Path, caplog
    ) -> None:
        write_config(
            tmp_path,
            {
                **BASE,
                "bins": {
                    "streams": [
                        {"label": "RUB", "weekday": 3, "every_weeks": 2}
                    ]
                },
            },
        )
        with caplog.at_level(logging.WARNING):
            cfg = load_config()
        bins = cfg.bins
        assert bins is not None and bins.streams[0].every_weeks == 1
        assert any("anchor" in r.message for r in caplog.records)

    def test_no_streams_means_no_bins(self, tmp_path: Path) -> None:
        write_config(tmp_path, {**BASE, "bins": {"streams": []}})
        assert load_config().bins is None

    def test_lead_days_clamped(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {
                **BASE,
                "bins": {
                    "lead_days": 50,
                    "streams": [{"label": "RUB", "weekday": 1}],
                },
            },
        )
        bins = load_config().bins
        assert bins is not None and bins.lead_days == 6


class TestLayoutParsing:
    def test_row_pattern_string_form(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {**BASE, "display": {"row_pattern": "1-2,2"}},
        )
        assert load_config().display.row_pattern == [1, 2, 2]

    def test_row_pattern_invalid_entries_skipped(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {**BASE, "display": {"row_pattern": [1, 7, 2, "x"]}},
        )
        assert load_config().display.row_pattern == [1, 2]

    def test_views_parsed_with_defaults(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {
                **BASE,
                "views": [
                    {"name": "0123456789AB", "tiles": ["weather", "f1"]},
                    {"nope": True},
                ],
            },
        )
        views = load_config().views
        assert len(views) == 1
        assert views[0].name == "0123456789"  # truncated to 10
        assert views[0].text_scale == "normal"
        assert views[0].tiles == ["weather", "f1"]

    def test_f1_sessions_filtered(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            {
                **BASE,
                "f1": {"sessions": ["race", "quali", "bogus"], "mode": "list"},
            },
        )
        f1 = load_config().f1
        assert f1.sessions == ["race", "quali"]
        assert f1.mode == "list"


def test_timezone_resolution_prefers_weather(tmp_path: Path) -> None:
    from pixelpixoo.config import resolve_app_timezone

    write_config(
        tmp_path,
        {
            **BASE,
            "schedule": {"timezone": "Europe/London"},
        },
    )
    cfg = load_config()
    assert resolve_app_timezone(cfg) == "UTC"
