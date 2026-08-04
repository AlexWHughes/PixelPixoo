"""Shared helpers for painting compact text into a tile rect."""

from __future__ import annotations

from PIL import Image

from pixelpixoo.renderer import draw_text, fit_scale, text_width
from pixelpixoo.theme import Theme

Rect = tuple[int, int, int, int]  # x, y, w, h


def clip_text(
    text: str, max_w: int, *, tiny: bool, spacing: int, scale: int = 1
) -> str:
    if text_width(text, scale=scale, tiny=tiny, spacing=spacing) <= max_w:
        return text
    out = text
    while out and text_width(out + ".", scale=scale, tiny=tiny, spacing=spacing) > max_w:
        out = out[:-1]
    return (out + ".") if out != text else out


def draw_tile_line(
    img: Image.Image,
    rect: Rect,
    theme: Theme,
    text: str,
    color: tuple[int, int, int],
    row: int,
    *,
    hero: bool = False,
) -> None:
    x, y, w, h = rect
    tiny = theme.use_tiny_font
    spacing = theme.spacing
    scale = theme.hero if hero else theme.body
    line_h = (theme.hero_h if hero else theme.body_h) + theme.line_gap
    yy = y + 1 + row * line_h
    if yy + (theme.hero_h if hero else theme.body_h) > y + h:
        return
    clip_scale = theme.body if not hero else 1
    clipped = clip_text(
        text.upper(), w - 2, tiny=tiny, spacing=spacing, scale=clip_scale
    )
    # Prefer dropping trailing period when a shorter token fits better
    if clipped.endswith(".") and len(clipped) > 2:
        alt = clipped[:-1]
        if text_width(
            alt, scale=clip_scale, tiny=tiny, spacing=spacing
        ) <= w - 2:
            clipped = alt
    if hero:
        scale = fit_scale(clipped, w - 2, prefer=theme.hero, tiny=tiny)
    draw_text(
        img,
        clipped,
        x + 1,
        yy,
        color,
        scale=scale,
        spacing=spacing,
        tiny=tiny,
    )
