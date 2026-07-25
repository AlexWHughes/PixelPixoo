# PixelPixoo

Push-loop dashboard for a **Divoom Pixoo 64**, plus a local config web UI.

## Screens

| Screen | Source | Notes |
|--------|--------|--------|
| Weather | [Open-Meteo](https://open-meteo.com/) | No API key |
| Traffic | Google Directions (`departure_time=now`) | One slide per route; needs `GOOGLE_MAPS_API_KEY` |
| Sensibo | [Sensibo API v2](http://static.sensibo.com/SensiboAPI_v2.yaml) | Room temp/humidity + AC state; needs `SENSIBO_API_KEY` |
| Next F1 | [Jolpica](https://api.jolpi.ca/) | No API key |
| Countdown | Config dates | One slide per target |
| Bin night | Config weekly schedule | Conditional tile — only when put-out is within `lead_days` |

## Quick start (local Docker)

```bash
cp config.example.yaml config.yaml
cp .env.example .env
# edit .env: PIXOO_IP, SENSIBO_API_KEY, GOOGLE_MAPS_API_KEY

docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
open http://localhost:8787
```

Without `docker-compose.local.yml`, Compose uses named volumes and seeds `config.example.yaml` on first start (same path as Portainer/GitHub).

Web UI features:
- Device IP, brightness, rotate interval, preview vs live push
- Weather / traffic routes / Sensibo pins / F1 / countdowns / bin night
- Masked secrets (paste to replace; clear checkbox to wipe)
- Sensibo discover + pin
- Pixoo connection test
- Live loop status + nearest-neighbour screen previews
- **Save & apply** hot-reloads the push loop (no container restart)

`.env` and `config.yaml` are gitignored. Local bind mounts (via `docker-compose.local.yml`) or the `pixelpixoo_config` volume keep UI saves durable.

## Preview vs live

| Mode | How |
|------|-----|
| Preview PNGs | Set `PIXELPIXOO_PREVIEW=/preview` in `.env` or toggle in UI |
| Live push | Clear preview mode, set real `PIXOO_IP` |

## API (for scripting)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/status` | Loop health |
| GET/PUT | `/api/config` | Read/write config (secrets masked on GET) |
| GET | `/api/config/export` | Download full **saved** JSON backup (includes API keys) |
| POST | `/api/config/export` | Download full **live UI** JSON (tiles, text scale, layout, screens, secrets) |
| POST | `/api/config/import` | Replace config from export JSON |
| POST | `/api/reload` | Reload loop |
| POST | `/api/pixoo/test` | Ping device |
| GET | `/api/sensibo/discover` | List pods |
| GET | `/api/preview/{name}` | PNG frame |

OpenAPI: `/api/docs`

## Portainer (GitHub)

Deploy from the repo — no `.env` / `config.yaml` in git required.

1. Stack → **Repository** → this GitHub URL + `docker-compose.yml`
2. Under **Environment variables**, set at least:
   - `PIXOO_IP`
   - `GOOGLE_MAPS_API_KEY` (if using traffic)
   - `SENSIBO_API_KEY` (if using Sensibo)
   - optional: `PIXELPIXOO_WEB_PORT=8787`
3. Deploy. First boot seeds `/config` from `config.example.yaml`; further UI edits persist in the `pixelpixoo_config` volume.

Publish host port `8787` → container `8080`. Ensure the stack can reach the Pixoo on the LAN (`network_mode: host` if bridge routing fails).
