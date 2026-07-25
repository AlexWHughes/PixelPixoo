FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIXELPIXOO_CONFIG=/config/config.yaml

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

# Config is mounted at /config/config.yaml by compose / Portainer
CMD ["python", "-m", "pixelpixoo"]
