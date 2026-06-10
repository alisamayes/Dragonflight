"""Session-scoped map copies and Terrascape terrain mutation."""

from __future__ import annotations

from dragonflight.army_pathfinding import shortest_path
from dragonflight.dragon_abilities import try_use_ability
from dragonflight.dragon_playables import Browngon
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_loader import load_map
from dragonflight.map_state import GameMap, Tile, clone_game_map, replace_tile_terrain
from dragonflight.terrain import Terrain

_EXAMPLE_MAP = (
    __import__("pathlib").Path(__file__).resolve().parent.parent / "assets" / "example_hexmap.json"
)


def _line_map(*cells: tuple[int, int, Terrain]) -> GameMap:
    tiles = {
        OffsetCoord(col, row): Tile(coord=OffsetCoord(col, row), terrain=terrain)
        for col, row, terrain in cells
    }
    max_col = max(c[0] for c in cells)
    max_row = max(c[1] for c in cells)
    return GameMap(
        width=max_col + 1,
        height=max_row + 1,
        hex_size=30.0,
        orientation="flat",
        tiles=tiles,
    )


def test_clone_game_map_is_independent_of_loader_result() -> None:
    authored = load_map(_EXAMPLE_MAP)
    session = clone_game_map(authored)
    grass = next(t for t in session if t.terrain is Terrain.GRASSLAND)
    replace_tile_terrain(session, grass.coord, Terrain.MOUNTAIN)
    assert session.get(grass.coord) is not None
    assert session.get(grass.coord).terrain is Terrain.MOUNTAIN
    assert authored.get(grass.coord) is not None
    assert authored.get(grass.coord).terrain is Terrain.GRASSLAND


def test_terrascape_mutates_session_tile_to_mountain() -> None:
    citadel = OffsetCoord(0, 0)
    target = OffsetCoord(2, 0)
    world = _line_map(
        (0, 0, Terrain.CITADEL),
        (1, 0, Terrain.GRASSLAND),
        (2, 0, Terrain.GRASSLAND),
        (3, 0, Terrain.GRASSLAND),
    )
    dragon = Browngon.new_at(citadel)
    dragon.level = 15

    result = try_use_ability(
        dragon,
        "Terrascape",
        world=world,
        citadel_coord=citadel,
        settlements_by_coord={},
        target=target,
    )

    assert result.ok
    assert world.get(target) is not None
    assert world.get(target).terrain is Terrain.MOUNTAIN


def test_terrascape_mountain_blocks_army_path() -> None:
    start = OffsetCoord(0, 0)
    choke = OffsetCoord(1, 0)
    goal = OffsetCoord(2, 0)
    world = _line_map(
        (0, 0, Terrain.GRASSLAND),
        (1, 0, Terrain.GRASSLAND),
        (2, 0, Terrain.CITADEL),
    )
    assert shortest_path(start, goal, world) == (start, choke, goal)

    replace_tile_terrain(world, choke, Terrain.MOUNTAIN)
    assert shortest_path(start, goal, world) == ()
