"""Tests for pixelpixoo.pixoo_client: IP validation, protocol retry, summaries."""

from __future__ import annotations

from typing import Any

import pytest
from PIL import Image

from pixelpixoo.pixoo_client import (
    GIF_ID_LIMIT,
    PixooClient,
    require_lan_ipv4,
    summarize_conf,
)


class TestRequireLanIpv4:
    @pytest.mark.parametrize(
        "ip", ["192.168.1.50", "10.0.0.5", "172.16.3.9", "172.31.255.254"]
    )
    def test_accepts_private_ranges(self, ip: str) -> None:
        assert require_lan_ipv4(f"  {ip}  ") == ip

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "pixoo.local",  # hostname
            "example.com",
            "http://192.168.1.5/post",  # URL
            "192.168.1.50:8080",  # port
            "192.168.1",  # shortened
            "300.1.1.1",  # out of range octet
            "0x0a.0.0.1",  # hex
            "127.0.0.1",  # loopback
            "169.254.169.254",  # link-local / cloud metadata
            "224.0.0.1",  # multicast
            "0.0.0.0",  # unspecified
            "8.8.8.8",  # public
            "100.64.0.1",  # CGNAT, outside RFC1918
        ],
    )
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(ValueError):
            require_lan_ipv4(bad)


class FlakyPixoo(PixooClient):
    """In-memory double that fails the first SendHttpGif like a desynced device."""

    def __init__(self) -> None:
        self.ip = "fake"
        self.base_url = "fake"
        self._pic_id = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.gif_failures_left = 1

    def send(self, command: str, **params: Any) -> dict[str, Any]:
        self.calls.append((command, params))
        if command == "Draw/SendHttpGif" and self.gif_failures_left > 0:
            self.gif_failures_left -= 1
            raise RuntimeError("Pixoo error -1 for Draw/SendHttpGif")
        return {}


def test_push_image_retries_after_gif_error() -> None:
    client = FlakyPixoo()
    frame = Image.new("RGB", (64, 64))
    client.push_image(frame)
    commands = [c for c, _ in client.calls]
    assert commands.count("Draw/ResetHttpGifId") == 1
    assert commands.count("Draw/SendHttpGif") == 2


def test_push_image_happy_path_has_no_reset() -> None:
    client = FlakyPixoo()
    client.gif_failures_left = 0
    client.push_image(Image.new("RGB", (64, 64)))
    assert [c for c, _ in client.calls] == ["Draw/SendHttpGif"]


def test_pic_id_wraps_at_limit() -> None:
    client = FlakyPixoo()
    client.gif_failures_left = 0
    for _ in range(GIF_ID_LIMIT + 2):
        client.push_image(Image.new("RGB", (64, 64)))
    resets = [c for c, _ in client.calls if c == "Draw/ResetHttpGifId"]
    assert len(resets) == 1
    last = client.calls[-1][1]["PicID"]
    assert last == 3


def test_push_image_resizes_foreign_sizes() -> None:
    client = FlakyPixoo()
    client.push_image(Image.new("RGB", (32, 32)))
    payload = client.calls[-1][1]
    assert payload["PicWidth"] == 64
    # 64*64*3 bytes → base64 length 16384.
    assert len(payload["PicData"]) == 16384


class TestSummarizeConf:
    def test_full_conf(self) -> None:
        text = summarize_conf(
            {"LightSwitch": 1, "Brightness": 42}, ip="192.168.0.9", pic_id=7
        )
        assert "192.168.0.9" in text
        assert "screen on" in text
        assert "brightness 42" in text
        assert "gif id 7" in text

    def test_minimal_conf(self) -> None:
        text = summarize_conf({}, ip="10.1.1.1")
        assert text == "Pixoo at 10.1.1.1"

    def test_screen_off(self) -> None:
        assert "screen off" in summarize_conf({"LightSwitch": 0}, ip="x")
