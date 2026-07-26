"""Display theme: text scales and layout modes for 64×64 frames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TextScale = Literal["tiny", "compact", "normal", "large"]
LayoutMode = Literal["focus", "dense", "split", "dashboard", "custom"]
ViewLayout = Literal["focus", "list", "split_h", "split_v", "grid_4", "rows"]

VALID_TEXT_SCALES: tuple[TextScale, ...] = ("tiny", "compact", "normal", "large")
VALID_LAYOUTS: tuple[LayoutMode, ...] = (
    "focus",
    "dense",
    "split",
    "dashboard",
    "custom",
)
VALID_VIEW_LAYOUTS: tuple[ViewLayout, ...] = (
    "focus",
    "list",
    "split_h",
    "split_v",
    "grid_4",
    "rows",
)


@dataclass(frozen=True)
class Theme:
    """Resolved drawing metrics for a text scale."""

    text_scale: TextScale
    # Primary hero numbers
    hero: int
    # Body / labels
    body: int
    # Micro captions (tiny font uses 3×5)
    micro: int
    spacing: int
    use_tiny_font: bool
    header_h: int
    line_gap: int

    @property
    def body_h(self) -> int:
        return 5 if self.use_tiny_font and self.body == 1 else 7 * self.body

    @property
    def hero_h(self) -> int:
        return 7 * self.hero

    @property
    def micro_h(self) -> int:
        return 5 if self.use_tiny_font else 7 * self.micro


def theme_for(scale: str | TextScale) -> Theme:
    key: TextScale = scale if scale in VALID_TEXT_SCALES else "normal"  # type: ignore[assignment]
    table: dict[TextScale, Theme] = {
        "tiny": Theme(
            text_scale="tiny",
            hero=1,
            body=1,
            micro=1,
            spacing=0,
            use_tiny_font=True,
            header_h=7,
            line_gap=1,
        ),
        "compact": Theme(
            text_scale="compact",
            hero=1,
            body=1,
            micro=1,
            spacing=1,
            use_tiny_font=False,
            header_h=8,
            line_gap=1,
        ),
        "normal": Theme(
            text_scale="normal",
            hero=2,
            body=1,
            micro=1,
            spacing=1,
            use_tiny_font=False,
            header_h=10,
            line_gap=2,
        ),
        "large": Theme(
            text_scale="large",
            hero=2,
            body=1,
            micro=1,
            spacing=1,
            use_tiny_font=False,
            header_h=10,
            line_gap=2,
        ),
    }
    return table[key]


def coerce_text_scale(value: object, default: TextScale = "normal") -> TextScale:
    text = str(value or default).lower().strip()
    return text if text in VALID_TEXT_SCALES else default  # type: ignore[return-value]


def coerce_layout(value: object, default: LayoutMode = "focus") -> LayoutMode:
    text = str(value or default).lower().strip()
    return text if text in VALID_LAYOUTS else default  # type: ignore[return-value]


def coerce_view_layout(value: object, default: ViewLayout = "list") -> ViewLayout:
    text = str(value or default).lower().strip()
    return text if text in VALID_VIEW_LAYOUTS else default  # type: ignore[return-value]


def layout_rects(
    layout: ViewLayout, *, header: bool, header_h: int = 10
) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) panes for a view layout."""
    top = header_h if header else 0
    h = 64 - top
    if layout == "focus":
        return [(0, top, 64, h)]
    if layout in ("list", "rows"):
        return [(0, top, 64, h)]
    if layout == "split_h":
        mid = top + h // 2
        return [(0, top, 64, mid - top), (0, mid, 64, 64 - mid)]
    if layout == "split_v":
        return [(0, top, 32, h), (32, top, 32, h)]
    # grid_4
    mid_y = top + h // 2
    return [
        (0, top, 32, mid_y - top),
        (32, top, 32, mid_y - top),
        (0, mid_y, 32, 64 - mid_y),
        (32, mid_y, 32, 64 - mid_y),
    ]


def pattern_pane_count(pattern: list[int]) -> int:
    return sum(n for n in pattern if n in (1, 2))


def fit_row_pattern(pattern: list[int], n_tiles: int) -> list[int]:
    """Trim/adjust a row pattern so it yields exactly ``n_tiles`` panes.

    Keeps earlier rows stable (so weather stays on top) and drops trailing
    capacity when conditional tiles leave the layout — avoiding blank bands
    that shrink every remaining tile.
    """
    if n_tiles <= 0:
        return [1]
    cleaned = [n for n in pattern if n in (1, 2)]
    if not cleaned:
        return [1] * n_tiles

    while cleaned and pattern_pane_count(cleaned) > n_tiles:
        excess = pattern_pane_count(cleaned) - n_tiles
        if cleaned[-1] == 2 and excess == 1:
            cleaned[-1] = 1
            break
        cleaned.pop()

    while pattern_pane_count(cleaned) < n_tiles:
        need = n_tiles - pattern_pane_count(cleaned)
        cleaned.append(2 if need >= 2 else 1)

    # Final safety if a trailing split overshoots by one.
    while cleaned and pattern_pane_count(cleaned) > n_tiles:
        if cleaned[-1] == 2:
            cleaned[-1] = 1
        else:
            cleaned.pop()
    return cleaned or [1]


def row_pattern_rects(
    pattern: list[int],
    *,
    header: bool,
    header_h: int = 10,
    tile_count: int | None = None,
) -> list[tuple[int, int, int, int]]:
    """Build panes from a custom row pattern of 1s and 2s.

    Example: [1, 1, 1, 2] → three full-width bands, then a split row.
    Example: [2, 2, 1, 2] → two splits, one full, one split.

    When ``tile_count`` is set, the pattern is fitted so pane count matches
    visible tiles (no blank reserved rows).
    """
    cleaned = [n for n in pattern if n in (1, 2)]
    if tile_count is not None:
        cleaned = fit_row_pattern(cleaned, tile_count)
    elif not cleaned:
        cleaned = [1]
    top = header_h if header else 0
    usable = 64 - top
    rows = len(cleaned)
    band = max(8, usable // rows)
    rects: list[tuple[int, int, int, int]] = []
    y = top
    for i, cols in enumerate(cleaned):
        h = band if i < rows - 1 else 64 - y
        if h <= 0:
            break
        if cols == 1:
            rects.append((0, y, 64, h))
        else:
            rects.append((0, y, 32, h))
            rects.append((32, y, 32, h))
        y += h
    return rects
