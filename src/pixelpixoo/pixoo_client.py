"""Minimal Divoom Pixoo local HTTP API client.

Talks to ``POST http://<ip>/post`` using Divoom command names
(http://doc.divoom-gz.com/web/#/12?page_id=196).

GIF PicID sync/reset and same-LAN discovery follow behaviour documented by
https://github.com/SomethingWithComputers/pixoo (CC BY-NC-SA 4.0) — this module
does not copy that library.
"""

from __future__ import annotations

import base64
import ipaddress
import logging
import re
from typing import Any

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

SIZE = 64
# Firmware can stop accepting frames after a few hundred PicIDs; reset often.
GIF_ID_LIMIT = 32
LAN_DISCOVER_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"
# Dotted decimal only — no hostnames, ports, octal, or shortened forms.
_IPV4_DOTTED = re.compile(
    r"^(?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}$"
)
_LAN_V4 = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def require_lan_ipv4(host: str) -> str:
    """Return a RFC1918 dotted IPv4 address, or raise ValueError.

    Rejects hostnames, ports, URLs, loopback, link-local (incl. cloud
    metadata), multicast, unspecified, and public addresses.
    """
    text = str(host).strip()
    if not text:
        raise ValueError("Pixoo IP is required")
    if not _IPV4_DOTTED.fullmatch(text):
        raise ValueError("Pixoo IP must be a dotted LAN IPv4 address")
    try:
        addr = ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Pixoo IP must be a dotted LAN IPv4 address") from exc
    if (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
        or not any(addr in net for net in _LAN_V4)
    ):
        raise ValueError("Pixoo IP must be a private LAN address")
    return str(addr)


class PixooClient:
    def __init__(self, ip: str, timeout: float = 10.0) -> None:
        self.ip = ip
        self.base_url = f"http://{ip}/post"
        self._client = httpx.Client(timeout=timeout)
        self._pic_id = 0

    def close(self) -> None:
        self._client.close()

    def send(self, command: str, **params: Any) -> dict[str, Any]:
        payload = {"Command": command, **params}
        response = self._client.post(self.base_url, json=payload)
        response.raise_for_status()
        data = response.json()
        error_code = data.get("error_code", 0)
        if error_code not in (0, None):
            raise RuntimeError(f"Pixoo error {error_code} for {command}: {data}")
        return data

    def get_all_conf(self) -> dict[str, Any]:
        return self.send("Channel/GetAllConf")

    def get_http_gif_id(self) -> int:
        data = self.send("Draw/GetHttpGifId")
        raw = data.get("PicId", data.get("PicID", 0))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def sync_gif_id(self) -> int:
        """Align PicID with the device; reset if the counter is already high."""
        try:
            self._pic_id = self.get_http_gif_id()
        except Exception:
            logger.warning("GetHttpGifId failed; starting PicID at 0")
            self._pic_id = 0
        if self._pic_id >= GIF_ID_LIMIT:
            self.reset_gif()
        return self._pic_id

    def set_brightness(self, brightness: int) -> None:
        self.send("Channel/SetBrightness", Brightness=int(brightness))

    def set_custom_channel(self) -> None:
        # Channel index 3 = custom / DIY
        self.send("Channel/SetIndex", SelectIndex=3)

    def reset_gif(self) -> None:
        self.send("Draw/ResetHttpGifId")
        self._pic_id = 0

    def _next_pic_id(self) -> int:
        self._pic_id += 1
        if self._pic_id >= GIF_ID_LIMIT:
            self.reset_gif()
            self._pic_id = 1
        return self._pic_id

    def push_image(self, image: Image.Image) -> None:
        if image.size != (SIZE, SIZE):
            image = image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.NEAREST)
        else:
            image = image.convert("RGB")

        raw = image.tobytes()
        pic_data = base64.b64encode(raw).decode("ascii")
        pic_id = self._next_pic_id()

        try:
            self.send(
                "Draw/SendHttpGif",
                PicNum=1,
                PicWidth=SIZE,
                PicOffset=0,
                PicID=pic_id,
                PicSpeed=1000,
                PicData=pic_data,
            )
        except RuntimeError:
            # Device GIF id counter can wrap / desync — reset and retry once.
            logger.warning("SendHttpGif failed; resetting GIF id and retrying")
            self.reset_gif()
            pic_id = self._next_pic_id()
            self.send(
                "Draw/SendHttpGif",
                PicNum=1,
                PicWidth=SIZE,
                PicOffset=0,
                PicID=pic_id,
                PicSpeed=1000,
                PicData=pic_data,
            )

    def set_screen(self, on: bool) -> None:
        # Divoom local API: 1 = on, 0 = off
        self.send("Channel/OnOffScreen", OnOff=1 if on else 0)

    def bootstrap(self, brightness: int) -> None:
        self.set_screen(True)
        self.set_brightness(brightness)
        self.set_custom_channel()
        self.sync_gif_id()


def discover_lan_devices(*, timeout: float = 8.0) -> list[dict[str, str]]:
    """Ask Divoom which Pixoo devices share this public IP (same LAN)."""
    with httpx.Client(timeout=timeout) as client:
        response = client.post(LAN_DISCOVER_URL)
        response.raise_for_status()
        data = response.json()
    if data.get("ReturnCode") not in (0, None):
        raise RuntimeError(f"Divoom discover failed: {data}")
    devices: list[dict[str, str]] = []
    for item in data.get("DeviceList") or []:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("DevicePrivateIP") or "").strip()
        try:
            ip = require_lan_ipv4(ip)
        except ValueError:
            continue
        devices.append(
            {
                "name": str(item.get("DeviceName") or "Pixoo"),
                "ip": ip,
                "id": str(item.get("DeviceId") or ""),
            }
        )
    return devices


def summarize_conf(conf: dict[str, Any], *, ip: str, pic_id: int | None = None) -> str:
    light = conf.get("LightSwitch")
    brightness = conf.get("Brightness")
    parts = [f"Pixoo at {ip}"]
    if light is not None:
        parts.append("screen on" if int(light) == 1 else "screen off")
    if brightness is not None:
        parts.append(f"brightness {brightness}")
    if pic_id is not None:
        parts.append(f"gif id {pic_id}")
    return " · ".join(parts)
