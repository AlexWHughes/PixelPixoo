# PixelPixoo

Push-loop dashboard for a [Divoom Pixoo 64](https://divoom.com/) — weather, commute times, climate, F1, countdowns, and more — with a built-in web UI.

Frames are rendered as 64×64 RGB and POSTed to the device on your LAN. No cloud middleman for the display path.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Docker](https://img.shields.io/badge/deploy-docker-2496ED)

## Features

| Screen | Source | API key |
|--------|--------|---------|
| Weather + multi-day forecast | [Open-Meteo](https://open-meteo.com/) | No |
| Traffic / commute ETA | [Google Directions](https://developers.google.com/maps/documentation/directions) | Yes (`GOOGLE_MAPS_API_KEY`) |
| Sensibo room climate | [Sensibo API](https://sensibo.github.io/) | Yes (`SENSIBO_API_KEY`) |
| Next F1 session | [Jolpica](https://api.jolpi.ca/) (Ergast-compatible) | No |
| Countdown | Config dates | No |
| Bin night | Weekly / fortnightly schedule | No (conditional tile) |

Also included:

- Custom multi-tile layouts on a single 64×64 frame (`row_pattern`, tile picker)
- Tiny / compact / normal text scales for dense dashboards
- Crossfade between frames, brightness + rotate interval
- Optional on/off schedule (timezone-aware windows)
- Config web UI with live previews, secret masking, export/import
- Docker + Portainer-friendly deploy (named volumes; no secrets in git)

## Quick start

### Requirements

- Docker (recommended), or Python **3.11+**
- A Pixoo 64 reachable on your LAN (for live push)
- Optional: Google Maps + Sensibo API keys for those screens

### Docker (local bind mounts)

```bash
git clone https://github.com/AlexWHughes/PixelPixoo.git
cd PixelPixoo

cp config.example.yaml config.yaml
cp .env.example .env
# Edit .env — at least PIXOO_IP. Add API keys as needed.
# Edit config.yaml — weather lat/lon (example is Sydney CBD).

docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
open http://localhost:8787
```

### Docker (named volumes — Portainer / GitHub)

Use `docker-compose.yml` alone. On first boot the entrypoint seeds `config.example.yaml` into the `pixelpixoo_config` volume.

1. Deploy the stack from this repository.
2. Set environment variables in the UI (or Compose):
   - `PIXOO_IP` (required for live push)
   - `GOOGLE_MAPS_API_KEY` (traffic)
   - `SENSIBO_API_KEY` (Sensibo)
   - `PIXELPIXOO_WEB_PORT=8787` (optional host port)
3. Open the web UI and finish setup (tiles, routes, devices).
4. Use **Export** / **Import** to back up or move a full config (includes secrets — treat the file carefully).

Default Compose uses **bridge** networking (published web port only). If the container cannot reach the Pixoo on your LAN that way, switch to **host** networking: uncomment `network_mode: host` in Compose and drop the `ports:` mapping (host mode binds the container’s ports directly on the host).

### Preview mode (no device)

```bash
# in .env
PIXELPIXOO_PREVIEW=/preview
# PIXELPIXOO_ONCE=true   # render once and exit (optional)
```

Or toggle preview in the web UI. PNGs land under the preview volume / `./preview`.

### Python (without Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
cp .env.example .env
# edit both files

export PIXELPIXOO_CONFIG=./config.yaml PIXELPIXOO_ENV=./.env
PYTHONPATH=src python -m pixelpixoo
```

Open the UI at [http://localhost:8080](http://localhost:8080) (override with `PIXELPIXOO_WEB_PORT`).

## Configuration

| File | Purpose | In git? |
|------|---------|---------|
| `config.yaml` | Screens, layout, schedule | **No** (gitignored) — start from `config.example.yaml` |
| `.env` | `PIXOO_IP`, API keys | **No** (gitignored) — start from `.env.example` |

The example weather location is **Sydney, Australia** (`-33.8688, 151.2093`). Change lat/lon/timezone to yours.

### Layout tips

- `display.layout: custom` + `row_pattern: [1, 2, 2, 2]` = one full-width row, then three split rows
- Tile ids: `weather`, `sensibo`, `sensibo:Living`, `traffic:WORK`, `f1`, `countdown`, `bins`, …
- `text_scale: tiny` packs the most onto 64×64

### Web UI

- Save & apply — writes config + secrets and hot-reloads the push loop
- Backup / Restore — saves live UI then downloads/restores full JSON (display, views, screens, secrets)
- Sensibo discover + pin, Pixoo connection test, live frame previews

## HTTP API

Base URL: the web UI host (e.g. `http://localhost:8787`). OpenAPI: `/api/docs`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/status` | Loop health |
| GET/PUT | `/api/config` | Read/write config (secrets masked on GET) |
| GET | `/api/config/export` | Download full **saved** backup (config, views, yaml snapshot, API keys) |
| POST | `/api/config/export` | Build backup from a live UI form body (no disk write) |
| POST | `/api/config/import` | Restore full config from backup JSON |
| POST | `/api/reload` | Reload push loop |
| POST | `/api/pixoo/test` | Ping device |
| GET | `/api/sensibo/discover` | List pods |
| GET | `/api/preview/{name}` | PNG frame |

## Security notes

- Never commit `.env` or `config.yaml` — they are gitignored for a reason.
- Export JSON contains **raw API keys**. Store backups privately.
- The web UI has **no authentication**. Bind it to a trusted LAN/VPN only (or put it behind a reverse proxy with auth).
- Rotate Google / Sensibo keys if they were ever pushed to a remote or shared in an export.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m pixelpixoo
```

Package layout lives under `src/pixelpixoo/`. License: [MIT](LICENSE).

## Disclaimer

PixelPixoo is an independent project and is not affiliated with Divoom, Sensibo, Google, or Formula 1. Use third-party APIs according to their terms and rate limits.
