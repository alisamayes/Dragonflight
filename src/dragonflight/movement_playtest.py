"""Interactive map session — Pygame (pygame required).

Launched by default from ``python -m dragonflight`` (see ``__main__``). Click
reachable hexes to move the dragon from the bundled citadel. Invalid tiles
(due to flight range or mandatory return to citadel on the daily clock) are
drawn muted. A 24-segment hour bar at the top tracks remaining daylight.

This module couples presentation with :class:`~dragonflight.dragon.Dragon` for
the runnable prototype. A static map-only window is :func:`render.run_demo`.
"""

from __future__ import annotations

import pygame

from .dragon import Dragon
from .dragon_defaults import HOURS_PER_DRAGON_DAY
from .hex_coord import HEX_CORNERS, OffsetCoord, offset_to_pixel
from .hour_bar_layout import hour_bar_segment_layout
from .map_state import GameMap, Tile
from .render import (
    BACKGROUND_COLOR,
    TERRAIN_COLORS,
    _origin_for,
    compute_render_hex_size,
    compute_window_size,
    hex_corner_offset,
    render_map,
)
from .terrain import Terrain

# --- Layout -------------------------------------------------------------------

#: Total height of the top chrome (caption + discrete hour bar).
TIME_BAR_HEIGHT: int = 52

#: Vertical position of the hour segments within the top chrome.
_BAR_TOP_Y: int = 30

#: Pixel height of each hour segment strip.
_BAR_SEGMENT_HEIGHT: int = 14

#: Gap between adjacent hour segments (pixels).
_SEGMENT_GAP: int = 1

#: Mute factor applied to unreachable terrain RGB components.
_MUTE_FACTOR: float = 0.42

#: Dragon marker colour (flat filled circle).
_DRAGON_DOT_RGB: tuple[int, int, int] = (0, 0, 0)

_FRAME_RATE: int = 60


def _find_citadel_coord(game_map: GameMap) -> OffsetCoord:
    """Return the offset coordinate of the single citadel tile."""
    found: list = []
    for tile in game_map:
        if tile.terrain is Terrain.CITADEL:
            found.append(tile.coord)
    if len(found) != 1:
        msg = f"movement playtest expects exactly one citadel tile; found {len(found)}"
        raise RuntimeError(msg)
    return found[0]


def _mute_rgb(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    r, g, b = rgb
    return (
        int(r * factor),
        int(g * factor),
        int(b * factor),
    )


def _make_tile_color_fn(dragon: Dragon, citadel: OffsetCoord, game_map: GameMap):
    """Return a per-tile fill that mutes destinations failing :meth:`Dragon.validate_move`."""

    def tile_color(tile: Tile) -> tuple[int, int, int]:
        base = TERRAIN_COLORS[tile.terrain]
        if tile.coord == dragon.position:
            return base
        if dragon.validate_move(tile.coord, game_map, citadel).ok:
            return base
        return _mute_rgb(base, _MUTE_FACTOR)

    return tile_color


def _hex_polygon_screen(
    coord: OffsetCoord,
    hex_size: float,
    origin: tuple[float, float],
) -> list[tuple[float, float]]:
    ox, oy = origin
    cx_off, cy_off = offset_to_pixel(coord, hex_size)
    cx = ox + cx_off
    cy = oy + cy_off
    return [
        (cx + dx, cy + dy)
        for dx, dy in (hex_corner_offset(hex_size, i) for i in range(HEX_CORNERS))
    ]


def _point_in_polygon(px: float, py: float, verts: list[tuple[float, float]]) -> bool:
    """Point-in-polygon (even-odd) for flat-top hex hit-testing."""
    n = len(verts)
    inside = False
    for i in range(n):
        j = (i + 1) % n
        xi, yi = verts[i]
        xj, yj = verts[j]
        if abs(yj - yi) < 1e-12:
            continue
        if (yi > py) != (yj > py):
            xinters = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < xinters:
                inside = not inside
    return inside


def _pick_tile_at_pixel(
    px: float,
    py: float,
    game_map: GameMap,
    hex_size: float,
    origin: tuple[float, float],
) -> OffsetCoord | None:
    """Return the topmost tile whose screen hex contains ``(px, py)``, else ``None``."""
    for tile in game_map:
        poly = _hex_polygon_screen(tile.coord, hex_size, origin)
        if _point_in_polygon(px, py, poly):
            return tile.coord
    return None


def _dragon_screen_center(
    position: OffsetCoord,
    hex_size: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    ox, oy = origin
    cx_off, cy_off = offset_to_pixel(position, hex_size)
    return ox + cx_off, oy + cy_off


def _draw_hour_bar(surface: pygame.Surface, hours_remaining: float, bar_width: int) -> None:
    """Draw 24 equal hour segments; left-to-right shows **spent** (dark) then **left** (green)."""
    margin = 8
    inner_w = max(1, bar_width - 2 * margin)
    segment_widths, gap = hour_bar_segment_layout(inner_w, _SEGMENT_GAP)

    hr = max(0.0, min(HOURS_PER_DRAGON_DAY, hours_remaining))
    spent = HOURS_PER_DRAGON_DAY - hr

    spent_rgb = (45, 48, 58)
    remain_rgb = (72, 160, 96)

    x_pos = margin
    y = _BAR_TOP_Y
    for i in range(24):
        w = segment_widths[i]
        consumed_here = spent - float(i)
        rect = pygame.Rect(x_pos, y, w, _BAR_SEGMENT_HEIGHT)
        if consumed_here >= 1.0:
            pygame.draw.rect(surface, spent_rgb, rect)
        elif consumed_here <= 0.0:
            pygame.draw.rect(surface, remain_rgb, rect)
        else:
            pygame.draw.rect(surface, remain_rgb, rect)
            w_spent = min(w, int(round(consumed_here * w)))
            if w_spent > 0:
                pygame.draw.rect(
                    surface,
                    spent_rgb,
                    pygame.Rect(x_pos, y, w_spent, _BAR_SEGMENT_HEIGHT),
                )
        x_pos += w
        if i < 23:
            x_pos += gap


def run_movement_playtest(
    game_map: GameMap,
    *,
    window_title: str = "Dragonflight",
) -> None:
    """Open a window with the map, a dragon dot, reachability tinting, and hour bar."""
    citadel_coord = _find_citadel_coord(game_map)
    dragon = Dragon.new_red_fire_at(citadel_coord)

    hex_size = compute_render_hex_size(game_map)
    base_w, base_h = compute_window_size(game_map, hex_size)
    win_w = base_w
    win_h = base_h + TIME_BAR_HEIGHT

    ox, oy = _origin_for(game_map, hex_size)
    origin: tuple[float, float] = (ox, oy + float(TIME_BAR_HEIGHT))

    pygame.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((win_w, win_h))
        pygame.display.set_caption(window_title)
        font = pygame.font.SysFont(None, 20)
        clock = pygame.time.Clock()

        day_index = 1

        def redraw() -> None:
            surface.fill(BACKGROUND_COLOR)
            caption = font.render(
                (
                    f"Day {day_index}  |  Green bar = hours left  |  Muted = unreachable  |  "
                    "Citadel = new day"
                ),
                True,
                (210, 210, 220),
            )
            surface.blit(caption, (8, 6))
            _draw_hour_bar(surface, dragon.hours_remaining, win_w)

            tile_color = _make_tile_color_fn(dragon, citadel_coord, game_map)
            render_map(
                surface,
                game_map,
                hex_size,
                origin,
                tile_color=tile_color,
                clear_background=False,
            )

            cx, cy = _dragon_screen_center(dragon.position, hex_size, origin)
            radius = max(3, int(hex_size * 0.18))
            pygame.draw.circle(surface, _DRAGON_DOT_RGB, (int(round(cx)), int(round(cy))), radius)
            pygame.display.flip()

        redraw()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                    break
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    if my < TIME_BAR_HEIGHT:
                        continue
                    picked = _pick_tile_at_pixel(float(mx), float(my), game_map, hex_size, origin)
                    if picked is None:
                        continue

                    outcome = dragon.move(picked, game_map, citadel_coord)
                    if outcome.ok and dragon.position == citadel_coord:
                        dragon.begin_new_day_at_citadel(citadel_coord)
                        day_index += 1
                    redraw()

            clock.tick(_FRAME_RATE)
    finally:
        pygame.quit()
