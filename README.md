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

## Quick start (local Docker)

```bash
cp config.example.yaml config.yaml
cp .env.example .env
# edit .env: PIXOO_IP, SENSIBO_API_KEY, GOOGLE_MAPS_API_KEY

docker compose up --build -d
open http://localhost:8787
```

Web UI features:
- Device IP, brightness, rotate interval, preview vs live push
- Weather / traffic routes / Sensibo pins / F1 / countdowns
- Masked secrets (paste to replace; clear checkbox to wipe)
- Sensibo discover + pin
- Pixoo connection test
- Live loop status + nearest-neighbour screen previews
- **Save & apply** hot-reloads the push loop (no container restart)

`.env` is gitignored. Config + `.env` are mounted read/write so the UI can persist changes.

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
| POST | `/api/reload` | Reload loop |
| POST | `/api/pixoo/test` | Ping device |
| GET | `/api/sensibo/discover` | List pods |
| GET | `/api/preview/{name}` | PNG frame |

OpenAPI: `/api/docs`

## Portainer

Same compose file. Publish host port `8787` → container `8080` (change `PIXELPIXOO_WEB_PORT` in `.env`). Ensure the stack can reach the Pixoo on the LAN (`network_mode: host` if bridge routing fails).
