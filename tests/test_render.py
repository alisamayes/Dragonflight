"""Unit tests for ``dragonflight.render`` sizing helpers.

These tests deliberately stay off any Pygame display surface — opening a real
window is brittle in headless CI and the contracts that Slice 1 actually
needs (window-fit guarantee, never up-scale, monotonic window size) are pure
geometry. Anything requiring a live ``pygame.display`` is opt-in via the
``DRAGONFLIGHT_GUI_TESTS`` env var so QA can flip it on locally.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dragonflight.map_loader import load_map
from dragonflight.map_state import GameMap
from dragonflight.render import (
    HEX_OUTLINE_WIDTH,
    MARGIN_PX,
    MAX_WINDOW_HEIGHT,
    MAX_WINDOW_WIDTH,
    TERRAIN_COLORS,
    compute_render_hex_size,
    compute_window_size,
)
from dragonflight.terrain import Terrain

_EXAMPLE_MAP_PATH: Path = Path(__file__).resolve().parent.parent / "assets" / "example_hexmap.json"


@pytest.fixture(scope="module")
def example_map() -> GameMap:
    """Loaded example map shared across the render-sizing tests."""
    return load_map(_EXAMPLE_MAP_PATH)


class TestColourTable:
    """The renderer must have a colour for every simulation terrain.

    Catches the easiest way to break Slice 1: adding a new ``Terrain`` enum
    member without updating ``TERRAIN_COLORS``, which would crash inside
    ``render_map`` only when a tile of that terrain happened to be drawn.
    """

    def test_every_terrain_has_a_colour(self) -> None:
        missing = [terrain for terrain in Terrain if terrain not in TERRAIN_COLORS]
        assert not missing, f"TERRAIN_COLORS missing entries: {missing}"

    def test_outline_width_is_positive(self) -> None:
        assert HEX_OUTLINE_WIDTH >= 1


class TestComputeRenderHexSize:
    def test_never_upscales_above_authored(self, example_map: GameMap) -> None:
        size = compute_render_hex_size(example_map)
        assert size <= example_map.hex_size

    def test_returns_authored_size_when_map_already_fits(self) -> None:
        # Synthesise a tiny 3-tile map at hex_size 10. The bbox is well under
        # MAX_WINDOW_*, so the function must NOT change the authored size.
        from dragonflight.hex_coord import OffsetCoord
        from dragonflight.map_state import Tile

        tiny_tiles = {
            OffsetCoord(col, 0): Tile(coord=OffsetCoord(col, 0), terrain=Terrain.GRASSLAND)
            for col in range(3)
        }
        tiny_map = GameMap(
            width=3,
            height=1,
            hex_size=10.0,
            orientation="flat",
            tiles=tiny_tiles,
        )
        assert compute_render_hex_size(tiny_map) == pytest.approx(10.0)

    def test_returns_positive_for_example_map(self, example_map: GameMap) -> None:
        size = compute_render_hex_size(example_map)
        assert size > 0.0


class TestComputeWindowSize:
    def test_fits_within_max_window_for_example_map(self, example_map: GameMap) -> None:
        size = compute_render_hex_size(example_map)
        width, height = compute_window_size(example_map, size)
        assert width <= MAX_WINDOW_WIDTH, f"width={width} > MAX_WINDOW_WIDTH={MAX_WINDOW_WIDTH}"
        assert height <= MAX_WINDOW_HEIGHT, (
            f"height={height} > MAX_WINDOW_HEIGHT={MAX_WINDOW_HEIGHT}"
        )

    def test_includes_margin_on_both_axes(self, example_map: GameMap) -> None:
        # Even at a vanishingly small hex size, two margins worth of pixels
        # must still be present — confirms MARGIN_PX is applied on both sides.
        width, height = compute_window_size(example_map, 0.001)
        assert width >= 2 * MARGIN_PX
        assert height >= 2 * MARGIN_PX

    def test_is_monotonic_in_hex_size(self, example_map: GameMap) -> None:
        # Use values far enough apart that ceiling rounding can't tie them.
        small_w, small_h = compute_window_size(example_map, 2.0)
        large_w, large_h = compute_window_size(example_map, 8.0)
        assert large_w > small_w
        assert large_h > small_h

    def test_offset_layout_is_roughly_square_for_square_map(self, example_map: GameMap) -> None:
        # Regression guard for the round-1 rhombus bug. The example map is
        # 30 columns × 30 rows in odd-q flat-top offset coordinates, so its
        # rendered bounding box should be roughly square — a width-to-height
        # ratio reasonably close to 1.0. When the renderer was still feeding
        # offset values into ``axial_to_pixel``, the same map produced a
        # bbox whose height was ~1.6× its width (rhombus). The intrinsic
        # offset-projection ratio for a 30×30 map is
        # ``sqrt(3) * 30.5 / 45.5 ≈ 1.16`` (height / width), and adding the
        # fixed ``2 * MARGIN_PX`` slack on each axis pulls the ratio
        # slightly closer to 1. The bound ``[0.75, 1.5]`` (suggested in the
        # revision brief) is loose enough that minor sizing changes —
        # ``MAX_WINDOW_*`` tweaks, an extra margin pixel — won't trip it,
        # while still being tight enough to clearly fail for the previous
        # axial-mistake layout (~1.63).
        size = compute_render_hex_size(example_map)
        width, height = compute_window_size(example_map, size)
        ratio = height / width
        assert 0.75 <= ratio <= 1.5, (
            f"window ratio height/width = {ratio:.3f} "
            f"(width={width}, height={height}); "
            f"expected roughly square (rhombus regression?)"
        )


@pytest.mark.skipif(
    not os.environ.get("DRAGONFLIGHT_GUI_TESTS"),
    reason="opt-in Pygame integration test; set DRAGONFLIGHT_GUI_TESTS=1 to enable",
)
class TestRenderMapHeadlessSmoke:
    """Opt-in smoke test that exercises ``render_map`` against a real Surface.

    Uses ``SDL_VIDEODRIVER=dummy`` so it never tries to open a window. Kept
    behind an env-var so the default ``pytest -q`` run on CI/headless dev
    machines doesn't pull SDL into the loop.
    """

    def test_render_map_does_not_mutate_or_raise(self, example_map: GameMap) -> None:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame

        from dragonflight.render import render_map

        size = compute_render_hex_size(example_map)
        window = compute_window_size(example_map, size)
        before_tiles = dict(example_map.tiles)

        pygame.init()
        try:
            surface = pygame.display.set_mode(window)
            render_map(surface, example_map, size, origin=(MARGIN_PX, MARGIN_PX))
        finally:
            pygame.quit()

        assert example_map.tiles == before_tiles, "render_map must not mutate the GameMap"
