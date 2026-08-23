"""Smoke tests for the FastAPI control plane (no device / network access)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from pixelpixoo.web.app import app

MINIMAL_CONFIG = {
    "pixoo_ip": "192.168.1.42",
    "weather": {"latitude": -33.86, "longitude": 151.2, "timezone": "UTC"},
}


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(MINIMAL_CONFIG), encoding="utf-8"
    )
    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "pixelpixoo"}


def test_status_before_start(client: TestClient) -> None:
    body = client.get("/api/status").json()
    assert body["running"] is False
    assert body["screen_names"] == []


def test_index_served(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_favicon_is_png(client: TestClient) -> None:
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_config_get_masks_secrets(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "GOOGLE_MAPS_API_KEY=supersecret-key-1234\n", encoding="utf-8"
    )
    body = client.get("/api/config").json()
    flat = str(body)
    assert "supersecret" not in flat


def test_config_export_download(client: TestClient) -> None:
    r = client.get("/api/config/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    bundle = r.json()
    assert bundle["format"] == "pixelpixoo-config"


def test_sensibo_discover_requires_key(client: TestClient) -> None:
    # No key in process env or .env → 400.
    r = client.get("/api/sensibo/discover")
    assert r.status_code == 400
    assert "SENSIBO_API_KEY" in r.json()["detail"]


def test_pixoo_test_rejects_public_ip(client: TestClient) -> None:
    r = client.post("/api/pixoo/test", json={"ip": "8.8.8.8"})
    assert r.status_code == 400
