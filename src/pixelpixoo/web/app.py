"""FastAPI config UI and control plane for PixelPixoo."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from pixelpixoo.persist import (
    apply_config_payload,
    export_config_bundle,
    normalize_import_payload,
    public_config_dict,
)
from pixelpixoo.runtime import runtime
from pixelpixoo.screens.sensibo import discover_pods

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="PixelPixoo", docs_url="/api/docs", redoc_url=None)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(500, "Web UI missing")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "pixelpixoo"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    return runtime.status_dict()


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return public_config_dict()


@app.get("/api/config/export")
def export_config_get() -> Response:
    """Download full saved config JSON (includes API keys, display, views)."""
    return _export_response(None)


@app.post("/api/config/export")
def export_config_post(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> Response:
    """Download a bundle from a live UI form payload (no disk write)."""
    return _export_response(payload or None)


def _export_response(form_payload: dict[str, Any] | None) -> Response:
    try:
        bundle = export_config_bundle(form_payload)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    body = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="pixelpixoo-config-{stamp}.json"'
        },
    )


@app.post("/api/config/import")
def import_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace config from an export bundle or raw config object."""
    try:
        normalized = normalize_import_payload(payload)
        cfg = apply_config_payload(normalized)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    runtime.request_reload(cfg)
    return {"ok": True, "config": public_config_dict(cfg), "status": runtime.status_dict()}


@app.put("/api/config")
def put_config(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        cfg = apply_config_payload(payload)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    runtime.request_reload(cfg)
    return {"ok": True, "config": public_config_dict(cfg), "status": runtime.status_dict()}


@app.post("/api/reload")
def reload_runtime() -> dict[str, Any]:
    runtime.request_reload()
    return {"ok": True, "status": runtime.status_dict()}


@app.post("/api/pixoo/test")
def test_pixoo() -> dict[str, Any]:
    return runtime.test_pixoo()


@app.get("/api/preview/{screen_name:path}")
def preview_screen(
    screen_name: str,
    scale: int = Query(8, ge=1, le=16),
) -> Response:
    try:
        cached = runtime.cached_frame(screen_name)
        if cached and scale == 8:
            data = cached
        else:
            data = runtime.render_screen_png(screen_name, scale=scale)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        logger.exception("Preview failed")
        raise HTTPException(500, str(exc)) from exc
    return Response(content=data, media_type="image/png")


@app.get("/api/previews")
def list_previews(scale: int = Query(4, ge=1, le=16)) -> dict[str, Any]:
    """Render all screens; returns names + base64 is too heavy — use status names + per-screen URLs."""
    status = runtime.status_dict()
    names = status.get("screen_names") or []
    return {
        "screens": [
            {"name": n, "url": f"/api/preview/{n}?scale={scale}"} for n in names
        ]
    }


@app.get("/api/sensibo/discover")
def sensibo_discover() -> dict[str, Any]:
    api_key = os.environ.get("SENSIBO_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "SENSIBO_API_KEY not configured")
    try:
        with httpx.Client(timeout=20.0) as client:
            devices = discover_pods(api_key, client)
    except Exception as exc:
        raise HTTPException(502, f"Sensibo discover failed: {exc}") from exc
    return {"ok": True, "devices": devices}
