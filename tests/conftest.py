"""Shared test fixtures: hermetic config/.env paths and secret scrubbing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_SECRET_VARS = (
    "PIXOO_IP",
    "GOOGLE_MAPS_API_KEY",
    "SENSIBO_API_KEY",
    "PIXELPIXOO_PREVIEW",
)


@pytest.fixture(autouse=True)
def hermetic_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every module at a temp config/.env so host state never leaks in."""
    monkeypatch.setenv("PIXELPIXOO_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("PIXELPIXOO_ENV", str(tmp_path / ".env"))
    for name in _SECRET_VARS:
        monkeypatch.delenv(name, raising=False)
