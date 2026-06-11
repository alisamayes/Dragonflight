"""Isometric projection and drawing for the map preview module.

Tiles are addressed in offset space (same as the main game). Each tile centre
uses :func:`~dragonflight.hex_coord.offset_to_pixel` (odd-q flat-top); the
entire top-down tessellation is then squished into isometric screen space via
:func:`flat_delta_to_iso`. Hex fills reuse
:func:`~dragonflight.render.default_tile_fill_rgb`.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pygame

from dragonflight.hex_coord import (
    HEX_CORNERS,
    AxialCoord,
    OffsetCoord,
    axial_to_offset,
    hex_corner_offset,
    offset_to_axial,
    offset_to_pixel,
)
from dragonflight.map_state import GameMap, Tile
from dragonflight.render import (
    BACKGROUND_COLOR,
    HEX_OUTLINE_COLOR,
    HEX_OUTLINE_WIDTH,
    MARGIN_PX,
    default_tile_fill_rgb,
)

# Vertical scale for iso_y = (x_flat + y_flat) * ISO_Y_SCALE (2:1 dimetric).
_ISO_Y_SCALE: float = 0.5

_FIT_SAFETY_PX: float = 1.0


def flat_delta_to_iso(dx: float, dy: float) -> tuple[float, float]:
    """Map a top-down offset (dx, dy) into isometric screen space."""
    return (dx - dy, (dx + dy) * _ISO_Y_SCALE)


def offset_to_iso_pixel(offset: OffsetCoord, hex_size: float) -> tuple[float, float]:
    """Project an offset tile coordinate to isometric pixel-space centre."""
    return flat_delta_to_iso(*offset_to_pixel(offset, hex_size))


def axial_to_iso_pixel(axial: AxialCoord, hex_size: float) -> tuple[float, float]:
    """Project an axial coordinate to isometric pixel-space centre."""
    return offset_to_iso_pixel(axial_to_offset(axial), hex_size)


def iso_hex_polygon_points(
    center: tuple[float, float],
    hex_size: float,
) -> list[tuple[float, float]]:
    """Return isometric hex polygon vertices at ``center`` (6 corners, squished)."""
    cx, cy = center
    points: list[tuple[float, float]] = []
    for i in range(HEX_CORNERS):
        dx_iso, dy_iso = flat_delta_to_iso(*hex_corner_offset(hex_size, i))
        points.append((cx + dx_iso, cy + dy_iso))
    return points


def _offset_extent(game_map: GameMap) -> tuple[int, int, int, int]:
    if not game_map.tiles:
        return 0, 0, 0, 0
    cols = [coord.col for coord in game_map.tiles]
    rows = [coord.row for coord in game_map.tiles]
    return min(cols), max(cols), min(rows), max(rows)


def _iso_center_rel(
    offset: OffsetCoord,
    *,
    col_min: int,
    row_min: int,
    hex_size: float,
) -> tuple[float, float]:
    """Iso centre relative to the map anchor at ``(col_min, row_min)``."""
    px, py = offset_to_pixel(offset, hex_size)
    ax, ay = offset_to_pixel(OffsetCoord(col=col_min, row=row_min), hex_size)
    return flat_delta_to_iso(px - ax, py - ay)


def _iso_content_extent_rel(
    game_map: GameMap,
    hex_size: float,
) -> tuple[float, float, float, float]:
    """Return ``(min_x, max_x, min_y, max_y)`` of all iso hex corners (map-local)."""
    if not game_map.tiles:
        return 0.0, 0.0, 0.0, 0.0
    col_min, _, row_min, _ = _offset_extent(game_map)
    rel_min_x = float("inf")
    rel_max_x = float("-inf")
    rel_min_y = float("inf")
    rel_max_y = float("-inf")
    for tile in game_map:
        cx, cy = _iso_center_rel(tile.coord, col_min=col_min, row_min=row_min, hex_size=hex_size)
        for x, y in iso_hex_polygon_points((cx, cy), hex_size):
            rel_min_x = min(rel_min_x, x)
            rel_max_x = max(rel_max_x, x)
            rel_min_y = min(rel_min_y, y)
            rel_max_y = max(rel_max_y, y)
    return rel_min_x, rel_max_x, rel_min_y, rel_max_y


def _iso_pixel_bbox_size(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    rel_min_x, rel_max_x, rel_min_y, rel_max_y = _iso_content_extent_rel(game_map, hex_size)
    if not game_map.tiles:
        return 0.0, 0.0
    return rel_max_x - rel_min_x, rel_max_y - rel_min_y


def _iso_origin_for(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Pixel offset so iso content sits inside ``MARGIN_PX`` (map-local coords)."""
    rel_min_x, _, rel_min_y, _ = _iso_content_extent_rel(game_map, hex_size)
    origin_x = MARGIN_PX - rel_min_x
    origin_y = MARGIN_PX - rel_min_y
    return origin_x, origin_y


def compute_iso_render_hex_size_for_canvas(
    game_map: GameMap,
    canvas_width: int,
    canvas_height: int,
) -> float:
    """Hex size that fits the iso-projected map inside the canvas (never up-scales)."""
    authored = float(game_map.hex_size)
    if authored <= 0.0 or not game_map.tiles:
        return authored

    width_at_authored, height_at_authored = _iso_pixel_bbox_size(game_map, authored)
    avail_w = max(0.0, float(canvas_width) - 2 * MARGIN_PX - _FIT_SAFETY_PX)
    avail_h = max(0.0, float(canvas_height) - 2 * MARGIN_PX - _FIT_SAFETY_PX)

    scale_w = 1.0 if width_at_authored <= avail_w else avail_w / width_at_authored
    scale_h = 1.0 if height_at_authored <= avail_h else avail_h / height_at_authored
    return authored * min(1.0, scale_w, scale_h)


def compute_iso_window_size(game_map: GameMap, hex_size: float) -> tuple[int, int]:
    """Return ``(width, height)`` for the iso map footprint including margins."""
    pixel_w, pixel_h = _iso_pixel_bbox_size(game_map, hex_size)
    width = int(math.ceil(pixel_w)) + 2 * MARGIN_PX
    height = int(math.ceil(pixel_h)) + 2 * MARGIN_PX
    return width, height


def layout_iso_map_on_canvas(
    game_map: GameMap,
    canvas_width: int,
    canvas_height: int,
) -> tuple[float, tuple[float, float], tuple[int, int]]:
    """Fit the iso map in a viewport; returns ``(hex_size, origin, footprint)``."""
    hex_size = compute_iso_render_hex_size_for_canvas(game_map, canvas_width, canvas_height)
    map_w, map_h = compute_iso_window_size(game_map, hex_size)
    ox, oy = _iso_origin_for(game_map, hex_size)
    pad_x = max(0.0, (float(canvas_width) - float(map_w)) / 2.0)
    pad_y = max(0.0, (float(canvas_height) - float(map_h)) / 2.0)
    return hex_size, (ox + pad_x, oy + pad_y), (map_w, map_h)


def iso_content_x_extent_rel(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Min/max screen-x of iso hex corners relative to the map render origin."""
    rel_min_x, rel_max_x, _, _ = _iso_content_extent_rel(game_map, hex_size)
    return rel_min_x, rel_max_x


def iso_content_y_extent_rel(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Min/max screen-y of iso hex corners relative to the map render origin."""
    _, _, rel_min_y, rel_max_y = _iso_content_extent_rel(game_map, hex_size)
    return rel_min_y, rel_max_y


def _iso_painter_sort_key(tile: Tile) -> tuple[int, int]:
    """Back-to-front order: ascending ``(q + r, q)`` in axial space."""
    axial = offset_to_axial(tile.coord)
    return axial.q + axial.r, axial.q


def render_iso_map(
    surface: pygame.Surface,
    game_map: GameMap,
    hex_size: float,
    origin: tuple[float, float],
    *,
    tile_color: Callable[[Tile], tuple[int, int, int]] | None = None,
    clear_background: bool = True,
) -> None:
    """Draw every tile as an isometric hex polygon (back-to-front)."""
    if clear_background:
        surface.fill(BACKGROUND_COLOR)
    origin_x, origin_y = origin
    col_min, _, row_min, _ = _offset_extent(game_map)
    sorted_tiles = sorted(game_map, key=_iso_painter_sort_key)
    for tile in sorted_tiles:
        cx_rel, cy_rel = _iso_center_rel(
            tile.coord,
            col_min=col_min,
            row_min=row_min,
            hex_size=hex_size,
        )
        center = (origin_x + cx_rel, origin_y + cy_rel)
        polygon = iso_hex_polygon_points(center, hex_size)
        fill = default_tile_fill_rgb(tile) if tile_color is None else tile_color(tile)
        pygame.draw.polygon(surface, fill, polygon)
        pygame.draw.polygon(surface, HEX_OUTLINE_COLOR, polygon, width=HEX_OUTLINE_WIDTH)
