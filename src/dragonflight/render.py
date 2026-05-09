"""Slice 1 hex-map renderer (Pygame).

Pure presentation layer for the "see the map" slice (spec §4 Perspective bullet:
"Initial development should just use coloured hexs"). The renderer reads a
:class:`~dragonflight.map_state.GameMap` and draws each tile as a flat-top
hex polygon filled with a per-terrain colour.

Coordinate convention (round Wave-2-revision-1 amendment): the renderer is
**offset-native**. Tiles in a ``GameMap`` are keyed by
:class:`~dragonflight.hex_coord.OffsetCoord` (odd-q flat-top column / row),
and pixel projection goes through
:func:`~dragonflight.hex_coord.offset_to_pixel`. The axial helpers are still
exposed by ``hex_coord`` for simulation math (distance, neighbours,
pathfinding) but rendering does not touch them — feeding offset values into
``axial_to_pixel`` is what made the rendered map look like a rhombus instead
of a square in earlier slices.

Architectural rules (locked by Architectural Lead):

* The colour table lives here, not in ``terrain``. ``terrain`` is the simulation's
  identity table; rendering palette is presentation policy.
* The renderer **never mutates** ``GameMap`` (single source of truth — spec §13/§19).
* No simulation rule logic in this module (no aggression, no movement, no combat).
* Hex math comes from ``hex_coord`` (``offset_to_pixel`` / ``hex_corner_offset``);
  this module never re-derives those formulas locally.
"""

from __future__ import annotations

import math

import pygame

from .hex_coord import HEX_CORNERS, hex_corner_offset, offset_to_pixel
from .map_state import GameMap
from .terrain import Terrain

# --- Public colour / sizing policy ------------------------------------------

#: Canonical colour table for Slice 1. Values chosen for clear distinction and to
#: roughly match the design-intent ``customColors`` recorded in
#: ``assets/example_hexmap.json`` (River #3a7bd5, Bridge #8B4513, Settlement
#: #fff705, Citadel #e31616). Built-in terrains (grassland, woodland, mountain)
#: pick readable defaults until art lands per spec §4 Perspective bullet.
TERRAIN_COLORS: dict[Terrain, tuple[int, int, int]] = {
    Terrain.GRASSLAND: (138, 191, 96),
    Terrain.WOODLAND: (49, 110, 50),
    Terrain.MOUNTAIN: (130, 130, 130),
    Terrain.RIVER: (58, 123, 213),
    Terrain.BRIDGE: (139, 69, 19),
    Terrain.SETTLEMENT: (255, 247, 5),
    Terrain.CITADEL: (227, 22, 22),
}

#: Window background fill — a near-black so any uncovered space (margin) reads
#: as inert chrome rather than a missing tile.
BACKGROUND_COLOR: tuple[int, int, int] = (20, 20, 28)

#: Outline drawn around every hex so adjacent same-colour tiles remain visually
#: distinguishable (e.g. a band of grasslands).
HEX_OUTLINE_COLOR: tuple[int, int, int] = (10, 10, 10)
HEX_OUTLINE_WIDTH: int = 1

#: Pixel margin between the rendered map's bounding box and the window edge.
MARGIN_PX: int = 24

#: Soft caps on the demo window so the map stays visible on typical 1920x1080
#: desktops (with chrome). ``compute_render_hex_size`` down-scales the
#: authored hex size to honour these caps; it never up-scales.
MAX_WINDOW_WIDTH: int = 1500
MAX_WINDOW_HEIGHT: int = 950

# --- Internal numeric constants ---------------------------------------------

#: Frames per second for the idle redraw loop. Slice 1 has no animation, so a
#: low rate is plenty and keeps the process from pegging a CPU core.
_FRAME_RATE: int = 30

#: One pixel of slack subtracted from each available axis when picking the
#: render hex size. Guards ``compute_window_size`` against a 1-ULP rounding
#: error pushing the ceiling-rounded window dimension just over
#: ``MAX_WINDOW_*``. Costs at most 1 px of map area; preserves the test
#: contract that ``compute_window_size(...) <= (MAX_WINDOW_WIDTH, MAX_WINDOW_HEIGHT)``.
_FIT_SAFETY_PX: float = 1.0

#: ``sqrt(3)`` — pre-computed because the flat-top vertical formulas use it
#: per-tile in tight loops.
_SQRT3: float = math.sqrt(3.0)


# --- Internal sizing helpers ------------------------------------------------


def _offset_extent(game_map: GameMap) -> tuple[int, int, int, int]:
    """Return ``(col_min, col_max, row_min, row_max)`` over all tile keys.

    Sampling the actual ``(col, row)`` extent — instead of assuming
    ``[0, width-1] × [0, height-1]`` — keeps the renderer correct for any
    future or synthesised map whose authored bounds differ from the
    example's 30×30. All four values are integers because
    :class:`~dragonflight.hex_coord.OffsetCoord` is integer-valued.
    """
    if not game_map.tiles:
        return 0, 0, 0, 0
    cols = [coord.col for coord in game_map.tiles]
    rows = [coord.row for coord in game_map.tiles]
    return min(cols), max(cols), min(rows), max(rows)


def _has_both_column_parities(game_map: GameMap) -> bool:
    """Return ``True`` if the map's columns include both even and odd indices.

    Odd-q flat-top offset projects odd columns half a hex below their even
    neighbours. The vertical bounding box only picks up that extra half-hex
    of zigzag when *both* parities are present in the rendered set; an
    all-even or all-odd subset has no zigzag and renders one hex shorter.
    """
    parities: set[int] = set()
    for coord in game_map.tiles:
        parities.add(coord.col & 1)
        if len(parities) == 2:
            return True
    return False


def _pixel_bbox_size(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Return ``(width, height)`` in pixels of the map's hex-polygon bounding box.

    Geometry is odd-q flat-top offset (see ``hex_coord.offset_to_pixel``):

    * Column spacing is ``1.5 * hex_size``; adding one full hex of
      horizontal slack (``+ 2.0`` in hex-size units) covers the leftmost
      tile's left corner and the rightmost tile's right corner.
    * Row spacing is ``sqrt(3) * hex_size``; the trailing ``+ 1.0`` in
      hex-size units covers top + bottom corner overhang together
      (flat-top hex height = ``sqrt(3) * hex_size``). When the rendered
      columns include both parities, an extra ``0.5`` accounts for the
      half-hex zigzag of odd columns.
    """
    col_min, col_max, row_min, row_max = _offset_extent(game_map)
    zigzag_extra = 0.5 if _has_both_column_parities(game_map) else 0.0
    pixel_w = hex_size * (1.5 * (col_max - col_min) + 2.0)
    pixel_h = hex_size * _SQRT3 * ((row_max - row_min) + zigzag_extra + 1.0)
    return pixel_w, pixel_h


def _origin_for(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Pixel offset for ``OffsetCoord(0, 0)`` so the bbox sits inside ``MARGIN_PX``.

    The renderer adds this to every ``offset_to_pixel`` result before
    drawing, so the leftmost column's centre lands at
    ``MARGIN_PX + hex_size`` and the topmost row's centre (accounting for
    whether ``col_min`` is odd or even) lands at
    ``MARGIN_PX + hex_size * sqrt(3) / 2``. Loader-validated maps always
    have ``col_min == 0`` (even) because every column from ``0`` to
    ``width-1`` must be populated; the parity branch is a safeguard for
    synthesised maps used in tests.
    """
    col_min, _, row_min, _ = _offset_extent(game_map)
    min_centre_x = hex_size * 1.5 * col_min
    parity_shift = 0.5 * (col_min & 1)
    min_centre_y = hex_size * _SQRT3 * (row_min + parity_shift)
    origin_x = MARGIN_PX + hex_size - min_centre_x
    origin_y = MARGIN_PX + hex_size * _SQRT3 / 2.0 - min_centre_y
    return origin_x, origin_y


# --- Public sizing / drawing API --------------------------------------------


def compute_render_hex_size(game_map: GameMap) -> float:
    """Pick a hex size (in pixels) that fits the map inside ``MAX_WINDOW_*``.

    Down-scales the authored ``game_map.hex_size`` so the entire map's
    bounding box (plus ``2 * MARGIN_PX``) fits within
    ``MAX_WINDOW_WIDTH × MAX_WINDOW_HEIGHT``. Never up-scales above the
    authored size — small maps stay at their authored hex size rather than
    ballooning to fill the window.
    """
    authored = float(game_map.hex_size)
    if authored <= 0.0 or not game_map.tiles:
        return authored

    width_at_authored, height_at_authored = _pixel_bbox_size(game_map, authored)
    avail_w = max(0.0, MAX_WINDOW_WIDTH - 2 * MARGIN_PX - _FIT_SAFETY_PX)
    avail_h = max(0.0, MAX_WINDOW_HEIGHT - 2 * MARGIN_PX - _FIT_SAFETY_PX)

    scale_w = 1.0 if width_at_authored <= avail_w else avail_w / width_at_authored
    scale_h = 1.0 if height_at_authored <= avail_h else avail_h / height_at_authored
    return authored * min(1.0, scale_w, scale_h)


def compute_window_size(game_map: GameMap, hex_size: float) -> tuple[int, int]:
    """Return the ``(width, height)`` in pixels needed to render the map.

    Includes ``MARGIN_PX`` on every side. Always rounds up so no hex corner
    is clipped by sub-pixel rounding. Monotonic in ``hex_size`` (bigger hex
    yields a bigger window) — this property is asserted by the tests.
    """
    pixel_w, pixel_h = _pixel_bbox_size(game_map, hex_size)
    width = int(math.ceil(pixel_w)) + 2 * MARGIN_PX
    height = int(math.ceil(pixel_h)) + 2 * MARGIN_PX
    return width, height


def render_map(
    surface: pygame.Surface,
    game_map: GameMap,
    hex_size: float,
    origin: tuple[float, float],
) -> None:
    """Draw the entire map onto ``surface``.

    Pure presentation: never mutates ``game_map``. ``origin`` is the pixel
    offset of ``OffsetCoord(0, 0)``'s centre on the surface; pair this with
    :func:`_origin_for` (or pass any matching offset) to place the map
    inside the rendered margin. Per-tile placement uses
    :func:`~dragonflight.hex_coord.offset_to_pixel` (odd-q flat-top), which
    is what makes a ``width × height`` map render as a square rather than a
    rhombus.
    """
    surface.fill(BACKGROUND_COLOR)
    origin_x, origin_y = origin
    for tile in game_map:
        cx_off, cy_off = offset_to_pixel(tile.coord, hex_size)
        cx = origin_x + cx_off
        cy = origin_y + cy_off
        polygon = [
            (cx + dx, cy + dy)
            for dx, dy in (hex_corner_offset(hex_size, i) for i in range(HEX_CORNERS))
        ]
        pygame.draw.polygon(surface, TERRAIN_COLORS[tile.terrain], polygon)
        pygame.draw.polygon(surface, HEX_OUTLINE_COLOR, polygon, width=HEX_OUTLINE_WIDTH)


def run_demo(game_map: GameMap, *, window_title: str = "Dragonflight — map preview") -> None:
    """Open a fixed-size Pygame window, draw ``game_map`` once, and idle.

    Quits on ``pygame.QUIT`` (window X button) and on ``KEYDOWN`` for
    ``K_ESCAPE``. Pygame is always shut down via ``finally`` so the process
    exits cleanly even if rendering raises.
    """
    hex_size = compute_render_hex_size(game_map)
    window_size = compute_window_size(game_map, hex_size)
    origin = _origin_for(game_map, hex_size)

    pygame.init()
    try:
        surface = pygame.display.set_mode(window_size)
        pygame.display.set_caption(window_title)
        clock = pygame.time.Clock()

        render_map(surface, game_map, hex_size, origin)
        pygame.display.flip()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                    break
            clock.tick(_FRAME_RATE)
    finally:
        pygame.quit()
