"""Tests for fog-of-war visibility helpers."""

from __future__ import annotations

from dragonflight.dragon_abilities import effective_flight_range
from dragonflight.dragon_playables import Redgon
from dragonflight.fog_of_war import (
    FOG_UNREVEALED_RGB,
    FogOfWarState,
    init_fog_from_dragon,
    is_revealed,
    reveal_coords_in_range,
)
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.play_session import _make_tile_color_fn
from dragonflight.terrain import Terrain


def _grid_map(width: int, height: int, *, terrain: Terrain = Terrain.GRASSLAND) -> GameMap:
    tiles = {
        OffsetCoord(c, r): Tile(coord=OffsetCoord(c, r), terrain=terrain)
        for c in range(width)
        for r in range(height)
    }
    return GameMap(
        width=width,
        height=height,
        hex_size=30.0,
        orientation="flat",
        tiles=tiles,
    )


def test_init_reveals_only_flight_range_from_dragon() -> None:
    origin = OffsetCoord(2, 2)
    dragon = Redgon.new_at(origin)
    dragon.flight_range_hexes = 1
    game_map = _grid_map(5, 5)
    fog = FogOfWarState()

    init_fog_from_dragon(fog, dragon, game_map)

    assert is_revealed(fog, origin)
    assert is_revealed(fog, OffsetCoord(3, 2))
    assert not is_revealed(fog, OffsetCoord(0, 0))


def test_reveal_persists_after_dragon_moves() -> None:
    start = OffsetCoord(1, 1)
    far = OffsetCoord(4, 4)
    dragon = Redgon.new_at(start)
    dragon.flight_range_hexes = 2
    game_map = _grid_map(6, 6)
    fog = FogOfWarState()

    reveal_coords_in_range(fog, dragon, game_map)
    assert is_revealed(fog, OffsetCoord(2, 1))

    dragon.position = far
    reveal_coords_in_range(fog, dragon, game_map)

    assert is_revealed(fog, OffsetCoord(2, 1))
    assert is_revealed(fog, far)


def test_reveal_uses_effective_flight_range() -> None:
    origin = OffsetCoord(0, 0)
    dragon = Redgon.new_at(origin)
    dragon.flight_range_hexes = 2
    from dragonflight.dragon_abilities import _apply_fiery_malice_modifiers

    _apply_fiery_malice_modifiers(dragon)
    game_map = _grid_map(8, 8)
    fog = FogOfWarState()
    flight = effective_flight_range(dragon)
    assert flight == 3

    reveal_coords_in_range(fog, dragon, game_map)

    assert is_revealed(fog, OffsetCoord(3, 0))
    assert not is_revealed(fog, OffsetCoord(4, 0))


def test_tile_color_fn_fog_vs_muted() -> None:
    citadel = OffsetCoord(0, 0)
    dragon = Redgon.new_at(OffsetCoord(1, 0))
    dragon.flight_range_hexes = 0
    game_map = _grid_map(3, 3)
    fog = FogOfWarState()
    fog.reveal(OffsetCoord(1, 0))
    fog.reveal(OffsetCoord(2, 0))

    tile_color = _make_tile_color_fn(dragon, citadel, game_map, fog)
    hidden = game_map.get(OffsetCoord(0, 2))
    assert hidden is not None
    assert tile_color(hidden) == FOG_UNREVEALED_RGB

    reachable = game_map.get(OffsetCoord(2, 0))
    assert reachable is not None
    base = tile_color(reachable)
    assert base != FOG_UNREVEALED_RGB


def test_init_clears_previous_session_reveals() -> None:
    origin = OffsetCoord(0, 0)
    dragon = Redgon.new_at(origin)
    dragon.flight_range_hexes = 1
    game_map = _grid_map(10, 10)
    fog = FogOfWarState()
    far = OffsetCoord(9, 9)
    fog.reveal(far)

    init_fog_from_dragon(fog, dragon, game_map)

    assert not is_revealed(fog, far)
    assert is_revealed(fog, origin)


def test_fog_fill_alias_matches_unrevealed_rgb() -> None:
    from dragonflight.fog_of_war import FOG_FILL_RGB

    assert FOG_FILL_RGB == FOG_UNREVEALED_RGB
