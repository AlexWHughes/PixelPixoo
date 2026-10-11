"""Shared screen lifecycle: sticky last frame + optional owned HTTP client."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx
from PIL import Image

from pixelpixoo.renderer import error_frame

logger = logging.getLogger(__name__)


class BaseScreen(ABC):
    """Sticky-frame screen with optional httpx client ownership."""

    name: str = "screen"
    error_label: str = "ERR"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 15.0,
        need_client: bool = True,
    ) -> None:
        self._last: Image.Image | None = None
        if client is not None:
            self._client = client
            self._owns_client = False
        elif need_client:
            self._client = httpx.Client(timeout=timeout)
            self._owns_client = True
        else:
            self._client = None  # type: ignore[assignment]
            self._owns_client = False

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def render(self) -> Image.Image:
        try:
            img = self._render()
            self._last = img.copy()
            return img
        except Exception:
            logger.exception("%s render failed", self.name)
            if self._last is not None:
                return self._last
            return error_frame(self.error_label[:8] or "ERR")

    @abstractmethod
    def _render(self) -> Image.Image:
        """Fetch data and paint a 64×64 RGB image."""
