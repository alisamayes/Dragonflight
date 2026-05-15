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
from collections.abc import Callable

import pygame

from .hex_coord import HEX_CORNERS, OffsetCoord, hex_corner_offset, offset_to_pixel
from .map_state import GameMap, Tile
from .settlement import SettlementType
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

#: Distinct fills for authored settlement subtypes (map ``settlementType``).
SETTLEMENT_KIND_FILL: dict[SettlementType, tuple[int, int, int]] = {
    SettlementType.VILLAGE: (255, 247, 5),
    SettlementType.CITY: (255, 196, 72),
    SettlementType.FORT: (196, 168, 58),
}


def default_tile_fill_rgb(tile: Tile) -> tuple[int, int, int]:
    """Default hex fill: terrain colour, with settlement subtype tint when set."""
    if tile.terrain is Terrain.SETTLEMENT and tile.settlement_kind is not None:
        return SETTLEMENT_KIND_FILL[tile.settlement_kind]
    return TERRAIN_COLORS[tile.terrain]


#: Window background fill — a near-black so any uncovered space (margin) reads
#: as inert chrome rather than a missing tile.
BACKGROUND_COLOR: tuple[int, int, int] = (20, 20, 28)

#: Outline drawn around every hex so adjacent same-colour tiles remain visually
#: distinguishable (e.g. a band of grasslands).
HEX_OUTLINE_COLOR: tuple[int, int, int] = (10, 10, 10)
HEX_OUTLINE_WIDTH: int = 1

#: Pixel margin between the rendered map's bounding box and the window edge.
MARGIN_PX: int = 24

#: Soft caps on the default / design-time window so the map stays comfortable
#: on large monitors. ``compute_render_hex_size`` down-scales the authored hex
#: size to honour these caps; it never up-scales. Resizable sessions use
#: :func:`compute_render_hex_size_for_canvas` with the live map viewport instead.
MAX_WINDOW_WIDTH: int = 1500
MAX_WINDOW_HEIGHT: int = 950

#: Smallest window the interactive client allows (total Pygame surface, including
#: any chrome such as the movement playtest time bar). Prevents unusably tiny
#: hit targets while still fitting small laptops.
MIN_CLIENT_WIDTH: int = 800
MIN_CLIENT_HEIGHT: int = 600

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


def _hex_polygon_points(
    coord: tuple[float, float],
    hex_size: float,
) -> list[tuple[float, float]]:
    """Return polygon points for a flat-top hex at centre ``coord``."""
    cx, cy = coord
    return [
        (cx + dx, cy + dy)
        for dx, dy in (hex_corner_offset(hex_size, i) for i in range(HEX_CORNERS))
    ]


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


def compute_render_hex_size_for_canvas(
    game_map: GameMap,
    canvas_width: int,
    canvas_height: int,
) -> float:
    """Pick a hex size (in pixels) so the map fits inside a ``canvas_width × canvas_height`` area.

    The canvas is the full pixel rectangle reserved for the map layer (the
    usual ``2 * MARGIN_PX`` inset still applies). Down-scales the authored
    ``game_map.hex_size`` when the bounding box would overflow; never up-scales
    above the authored size.
    """
    authored = float(game_map.hex_size)
    if authored <= 0.0 or not game_map.tiles:
        return authored

    width_at_authored, height_at_authored = _pixel_bbox_size(game_map, authored)
    avail_w = max(0.0, float(canvas_width) - 2 * MARGIN_PX - _FIT_SAFETY_PX)
    avail_h = max(0.0, float(canvas_height) - 2 * MARGIN_PX - _FIT_SAFETY_PX)

    scale_w = 1.0 if width_at_authored <= avail_w else avail_w / width_at_authored
    scale_h = 1.0 if height_at_authored <= avail_h else avail_h / height_at_authored
    return authored * min(1.0, scale_w, scale_h)


def compute_render_hex_size(game_map: GameMap) -> float:
    """Pick a hex size (in pixels) that fits the map inside ``MAX_WINDOW_*``.

    Convenience wrapper for fixed design-time caps; resizable clients should
    call :func:`compute_render_hex_size_for_canvas` with the live viewport.
    """
    return compute_render_hex_size_for_canvas(
        game_map,
        MAX_WINDOW_WIDTH,
        MAX_WINDOW_HEIGHT,
    )


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


def clamp_client_window_size(
    width: int,
    height: int,
    desktop_wh: tuple[int, int],
) -> tuple[int, int]:
    """Clamp client dimensions to ``[MIN_CLIENT_*, desktop]`` (inclusive)."""
    d_w, d_h = desktop_wh
    d_w_eff = max(d_w, MIN_CLIENT_WIDTH)
    d_h_eff = max(d_h, MIN_CLIENT_HEIGHT)
    return (
        max(MIN_CLIENT_WIDTH, min(width, d_w_eff)),
        max(MIN_CLIENT_HEIGHT, min(height, d_h_eff)),
    )


def client_size_from_resize_event(event: pygame.event.Event) -> tuple[int, int] | None:
    """Return ``(width, height)`` for a pygame window resize event, else ``None``."""
    window_resized = getattr(pygame, "WINDOWRESIZED", None)
    if window_resized is not None and event.type == window_resized:
        return int(event.x), int(event.y)
    if event.type == pygame.VIDEORESIZE:
        size = getattr(event, "size", None)
        if size is not None:
            w, h = size
            return int(w), int(h)
        return int(event.w), int(event.h)
    return None


def layout_map_on_canvas(
    game_map: GameMap,
    canvas_width: int,
    canvas_height: int,
) -> tuple[float, tuple[float, float], tuple[int, int]]:
    """Fit the map inside a viewport and return draw parameters.

    Returns ``(hex_size, (origin_x, origin_y), (map_w, map_h))`` for passing
    to :func:`render_map`. When the viewport is larger than the tight map
    bounds, the map is centred with equal padding. ``map_w``/``map_h`` are
    the pixel footprint from :func:`compute_window_size` at ``hex_size``.
    """
    hex_size = compute_render_hex_size_for_canvas(game_map, canvas_width, canvas_height)
    map_w, map_h = compute_window_size(game_map, hex_size)
    ox, oy = _origin_for(game_map, hex_size)
    pad_x = max(0.0, (float(canvas_width) - float(map_w)) / 2.0)
    pad_y = max(0.0, (float(canvas_height) - float(map_h)) / 2.0)
    return hex_size, (ox + pad_x, oy + pad_y), (map_w, map_h)


def render_map(
    surface: pygame.Surface,
    game_map: GameMap,
    hex_size: float,
    origin: tuple[float, float],
    *,
    tile_color: Callable[[Tile], tuple[int, int, int]] | None = None,
    clear_background: bool = True,
) -> None:
    """Draw the entire map onto ``surface``.

    Pure presentation: never mutates ``game_map``. ``origin`` is the pixel
    offset of ``OffsetCoord(0, 0)``'s centre on the surface; pair this with
    :func:`_origin_for` (or pass any matching offset) to place the map
    inside the rendered margin. Per-tile placement uses
    :func:`~dragonflight.hex_coord.offset_to_pixel` (odd-q flat-top), which
    is what makes a ``width × height`` map render as a square rather than a
    rhombus.

    When ``tile_color`` is provided, each tile's fill RGB comes from that
    callback (dev overlays, reachability tinting). When ``clear_background``
    is ``False``, existing pixels outside the hex layer are preserved — useful
    when a HUD strip already occupies the top of the surface.
    """
    if clear_background:
        surface.fill(BACKGROUND_COLOR)
    origin_x, origin_y = origin
    for tile in game_map:
        cx_off, cy_off = offset_to_pixel(tile.coord, hex_size)
        cx = origin_x + cx_off
        cy = origin_y + cy_off
        polygon = _hex_polygon_points((cx, cy), hex_size)
        fill = default_tile_fill_rgb(tile) if tile_color is None else tile_color(tile)
        pygame.draw.polygon(surface, fill, polygon)
        pygame.draw.polygon(surface, HEX_OUTLINE_COLOR, polygon, width=HEX_OUTLINE_WIDTH)


def draw_hex_outline(
    surface: pygame.Surface,
    *,
    coord: OffsetCoord,
    hex_size: float,
    origin: tuple[float, float],
    rgb: tuple[int, int, int],
    width: int = 2,
) -> None:
    """Draw a polygon outline around one offset hex coordinate."""
    origin_x, origin_y = origin
    cx_off, cy_off = offset_to_pixel(coord, hex_size)
    polygon = _hex_polygon_points((origin_x + cx_off, origin_y + cy_off), hex_size)
    pygame.draw.polygon(surface, rgb, polygon, width=width)


def run_demo(game_map: GameMap, *, window_title: str = "Dragonflight — map preview") -> None:
    """Open a resizable Pygame window, draw ``game_map``, and idle.

    The map scales down when the window is smaller than the design-time cap
    and is letterboxed when larger (no up-scaling past the authored hex size).

    Quits on ``pygame.QUIT`` (window X button) and on ``KEYDOWN`` for
    ``K_ESCAPE``. Pygame is always shut down via ``finally`` so the process
    exits cleanly even if rendering raises.
    """
    pygame.init()
    pygame.display.init()
    try:
        desktop = pygame.display.get_desktop_sizes()[0]
    except (IndexError, pygame.error):
        desktop = (
            pygame.display.Info().current_w,
            pygame.display.Info().current_h,
        )

    reserve_px = 80
    cap_w = max(MIN_CLIENT_WIDTH, desktop[0] - reserve_px)
    cap_h = max(MIN_CLIENT_HEIGHT, desktop[1] - reserve_px)

    design_hex = compute_render_hex_size(game_map)
    design_w, design_h = compute_window_size(game_map, design_hex)
    initial_w = min(max(MIN_CLIENT_WIDTH, design_w), cap_w)
    initial_h = min(max(MIN_CLIENT_HEIGHT, design_h), cap_h)

    def redraw(client_w: int, client_h: int) -> pygame.Surface:
        hex_size_, origin_, _ = layout_map_on_canvas(game_map, client_w, client_h)
        surf = pygame.display.set_mode(
            (client_w, client_h),
            pygame.RESIZABLE,
        )
        pygame.display.set_caption(window_title)
        render_map(surf, game_map, hex_size_, origin_)
        pygame.display.flip()
        return surf

    try:
        redraw(initial_w, initial_h)
        clock = pygame.time.Clock()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                    break
                resized = client_size_from_resize_event(event)
                if resized is not None:
                    nw, nh = clamp_client_window_size(*resized, desktop)
                    redraw(nw, nh)
            clock.tick(_FRAME_RATE)
    finally:
        pygame.quit()
