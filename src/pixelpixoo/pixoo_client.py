"""Minimal Divoom Pixoo local HTTP API client."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

SIZE = 64


class PixooClient:
    def __init__(self, ip: str, timeout: float = 10.0) -> None:
        self.base_url = f"http://{ip}/post"
        self._client = httpx.Client(timeout=timeout)
        self._pic_id = 1

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

    def set_brightness(self, brightness: int) -> None:
        self.send("Channel/SetBrightness", Brightness=int(brightness))

    def set_custom_channel(self) -> None:
        # Channel index 3 = custom / DIY
        self.send("Channel/SetIndex", SelectIndex=3)

    def reset_gif(self) -> None:
        self.send("Draw/ResetHttpGifId")
        self._pic_id = 1

    def push_image(self, image: Image.Image) -> None:
        if image.size != (SIZE, SIZE):
            image = image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.NEAREST)
        else:
            image = image.convert("RGB")

        raw = image.tobytes()
        pic_data = base64.b64encode(raw).decode("ascii")

        try:
            self.send(
                "Draw/SendHttpGif",
                PicNum=1,
                PicWidth=SIZE,
                PicOffset=0,
                PicID=self._pic_id,
                PicSpeed=1000,
                PicData=pic_data,
            )
        except RuntimeError:
            # Device GIF id counter can wrap / desync — reset and retry once.
            logger.warning("SendHttpGif failed; resetting GIF id and retrying")
            self.reset_gif()
            self.send(
                "Draw/SendHttpGif",
                PicNum=1,
                PicWidth=SIZE,
                PicOffset=0,
                PicID=self._pic_id,
                PicSpeed=1000,
                PicData=pic_data,
            )

        self._pic_id += 1
        if self._pic_id > 1000:
            self.reset_gif()

    def set_screen(self, on: bool) -> None:
        # Divoom local API: 1 = on, 0 = off
        self.send("Channel/OnOffScreen", OnOff=1 if on else 0)

    def bootstrap(self, brightness: int) -> None:
        self.set_screen(True)
        self.set_brightness(brightness)
        self.set_custom_channel()
        self.reset_gif()
