"""Composite multi-tile views for packing details onto one 64×64 frame."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from PIL import Image, ImageDraw

from pixelpixoo.config import AppConfig, ViewConfig
from pixelpixoo.renderer import BLACK, CYAN, draw_label_bar, error_frame, new_canvas
from pixelpixoo.theme import Theme, layout_rects, row_pattern_rects, theme_for
from pixelpixoo.widgets import default_tiles, paint_tile, visible_tiles

logger = logging.getLogger(__name__)


class CompositeScreen:
    def __init__(
        self,
        view: ViewConfig,
        cfg: AppConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self.view = view
        self.cfg = cfg
        self.name = f"view:{view.name}"
        self._client = client or httpx.Client(timeout=20.0)
        self._owns_client = client is None
        self._last: Image.Image | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def render(self) -> Image.Image:
        try:
            img = self._paint()
            self._last = img.copy()
            return img
        except Exception:
            logger.exception("View %s failed", self.view.name)
            if self._last is not None:
                return self._last
            return error_frame(self.view.name[:8] or "VIEW")

    def _paint(self) -> Image.Image:
        theme = theme_for(self.view.text_scale)
        img = new_canvas(BLACK)
        tiles = visible_tiles(self.cfg, self.view.tiles or default_tiles(self.cfg))
        if not tiles:
            draw_label_bar(img, self.view.name.upper()[:10], CYAN, height=theme.header_h)
            return img

        header = self.view.show_header
        if header:
            draw_label_bar(
                img,
                self.view.name.upper()[:12],
                CYAN,
                height=theme.header_h,
                tiny=theme.use_tiny_font,
            )

        layout = self.view.layout
        if layout == "list":
            self._paint_list(img, tiles, theme, header=header)
            return img

        if layout == "focus":
            paint_tile(
                img,
                (0, theme.header_h if header else 0, 64, 64 - (theme.header_h if header else 0)),
                tiles[0],
                self.cfg,
                theme,
                self._client,
                outline=False,
            )
            return img

        if layout == "rows":
            pattern = self.view.row_pattern or [1]
            rects = row_pattern_rects(
                pattern,
                header=header,
                header_h=theme.header_h,
                tile_count=len(tiles),
            )
            self._paint_rects(img, tiles, rects, theme)
            return img

        rects = layout_rects(layout, header=header, header_h=theme.header_h)
        self._paint_rects(img, tiles, rects, theme)
        return img

    def _paint_rects(
        self,
        img: Image.Image,
        tiles: list[str],
        rects: list[tuple[int, int, int, int]],
        theme: Theme,
    ) -> None:
        borders = self.view.show_borders
        draw = ImageDraw.Draw(img)
        for rect, tile in zip(rects, tiles):
            paint_tile(
                img, rect, tile, self.cfg, theme, self._client, outline=borders
            )
            if borders:
                x, y, w, h = rect
                draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(40, 48, 58))

    def _paint_list(
        self, img: Image.Image, tiles: list[str], theme: Theme, *, header: bool
    ) -> None:
        borders = self.view.show_borders
        top = theme.header_h if header else 0
        usable = 64 - top
        min_band = max(theme.body_h + theme.line_gap + 1, 8)
        max_fit = max(1, usable // min_band)
        shown = tiles[:max_fit]
        band = max(min_band, usable // max(1, len(shown)))
        for i, tile in enumerate(shown):
            y = top + i * band
            h = band if i < len(shown) - 1 else 64 - y
            paint_tile(
                img,
                (0, y, 64, h),
                tile,
                self.cfg,
                theme,
                self._client,
                outline=False,
            )
            if borders and i > 0:
                ImageDraw.Draw(img).line([(0, y), (63, y)], fill=(36, 42, 52))


def build_view_screens(
    cfg: AppConfig, http: httpx.Client
) -> list[Any]:
    """Build composite screens from explicit views or auto display.layout."""
    screens: list[Any] = []
    display = cfg.display
    if cfg.views:
        for view in cfg.views:
            screens.append(CompositeScreen(view, cfg, client=http))
        return screens

    tiles = visible_tiles(cfg, display.tiles or default_tiles(cfg))
    if not tiles:
        return []

    layout = display.layout
    scale = display.text_scale
    header = display.show_header
    borders = display.show_borders

    if layout == "focus":
        return []  # caller falls back to individual screens

    if layout == "dense":
        screens.append(
            CompositeScreen(
                ViewConfig(
                    name="HOME",
                    layout="list",
                    text_scale=scale if scale != "large" else "compact",
                    show_header=header,
                    show_borders=borders,
                    tiles=tiles,
                ),
                cfg,
                client=http,
            )
        )
        return screens

    if layout == "custom":
        pattern = display.row_pattern or [1, 1, 1, 2]
        screens.append(
            CompositeScreen(
                ViewConfig(
                    name="HOME",
                    layout="rows",
                    text_scale=scale if scale != "large" else "compact",
                    show_header=header,
                    show_borders=borders,
                    tiles=tiles,
                    row_pattern=pattern,
                ),
                cfg,
                client=http,
            )
        )
        return screens

    if layout == "split":
        pairs = [tiles[i : i + 2] for i in range(0, len(tiles), 2)]
        for idx, pair in enumerate(pairs):
            screens.append(
                CompositeScreen(
                    ViewConfig(
                        name=f"P{idx + 1}",
                        layout="split_h",
                        text_scale=scale,
                        show_header=header,
                        show_borders=borders,
                        tiles=pair,
                    ),
                    cfg,
                    client=http,
                )
            )
        return screens

    if layout == "dashboard":
        chunks = [tiles[i : i + 4] for i in range(0, len(tiles), 4)]
        dash_scale = scale if scale == "tiny" else "tiny"
        for idx, chunk in enumerate(chunks):
            screens.append(
                CompositeScreen(
                    ViewConfig(
                        name="DASH" if len(chunks) == 1 else f"D{idx + 1}",
                        layout="grid_4",
                        text_scale=dash_scale,
                        show_header=header,
                        show_borders=borders,
                        tiles=chunk,
                    ),
                    cfg,
                    client=http,
                )
            )
        return screens

    return screens
