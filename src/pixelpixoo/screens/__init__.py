"""Screen plugin protocol."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from pixelpixoo.screens.base import BaseScreen

__all__ = ["BaseScreen", "Screen"]


class Screen(Protocol):
    name: str

    def render(self) -> Image.Image:
        """Fetch data and return a 64×64 RGB image."""
        ...
