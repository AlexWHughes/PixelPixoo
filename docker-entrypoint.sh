#!/bin/sh
set -eu

CONFIG_PATH="${PIXELPIXOO_CONFIG:-/config/config.yaml}"
ENV_PATH="${PIXELPIXOO_ENV:-/config/.env}"
CONFIG_DIR=$(dirname "$CONFIG_PATH")

mkdir -p "$CONFIG_DIR" /preview

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Seeding $CONFIG_PATH from example"
  cp /app/config.example.yaml "$CONFIG_PATH"
fi

if [ ! -f "$ENV_PATH" ]; then
  echo "Seeding $ENV_PATH"
  : > "$ENV_PATH"
  [ -n "${PIXOO_IP:-}" ] && printf 'PIXOO_IP=%s\n' "$PIXOO_IP" >> "$ENV_PATH"
  [ -n "${GOOGLE_MAPS_API_KEY:-}" ] && printf 'GOOGLE_MAPS_API_KEY=%s\n' "$GOOGLE_MAPS_API_KEY" >> "$ENV_PATH"
  [ -n "${SENSIBO_API_KEY:-}" ] && printf 'SENSIBO_API_KEY=%s\n' "$SENSIBO_API_KEY" >> "$ENV_PATH"
  [ -n "${PIXELPIXOO_PREVIEW:-}" ] && printf 'PIXELPIXOO_PREVIEW=%s\n' "$PIXELPIXOO_PREVIEW" >> "$ENV_PATH"
fi

exec python -m pixelpixoo "$@"
