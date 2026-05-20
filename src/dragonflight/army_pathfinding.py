"""A* pathfinding for armies on axial hex grids (spec numnum5, 14)."""

from __future__ import annotations

import heapq

from .hex_coord import (
    OffsetCoord,
    axial_to_offset,
    distance,
    neighbours,
    offset_to_axial,
)
from .map_state import GameMap
from .terrain import Terrain

#: Terrains armies may enter (spec num5).
ARMY_PASSABLE_TERRAINS: frozenset[Terrain] = frozenset(
    {
        Terrain.GRASSLAND,
        Terrain.WOODLAND,
        Terrain.BRIDGE,
        Terrain.SETTLEMENT,
        Terrain.CITADEL,
    }
)

GRASSLAND_MOVE_COST: int = 1
WOODLAND_MOVE_COST: int = 2


def army_terrain_move_cost(terrain: Terrain) -> int | None:
    """Return movement cost to enter ``terrain``, or ``None`` if impassable."""

    if terrain not in ARMY_PASSABLE_TERRAINS:
        return None
    if terrain is Terrain.WOODLAND:
        return WOODLAND_MOVE_COST
    return GRASSLAND_MOVE_COST


def _offset_neighbours(offset: OffsetCoord) -> tuple[OffsetCoord, ...]:
    axial = offset_to_axial(offset)
    return tuple(axial_to_offset(n) for n in neighbours(axial))


def shortest_path(
    start: OffsetCoord,
    goal: OffsetCoord,
    game_map: GameMap,
) -> tuple[OffsetCoord, ...]:
    """Return lowest-cost path from ``start`` to ``goal`` (inclusive), or ``()`` if unreachable."""

    if start == goal:
        return (start,)

    start_tile = game_map.get(start)
    goal_tile = game_map.get(goal)
    if start_tile is None or goal_tile is None:
        return ()
    if army_terrain_move_cost(start_tile.terrain) is None:
        return ()
    if army_terrain_move_cost(goal_tile.terrain) is None:
        return ()

    def heuristic(coord: OffsetCoord) -> int:
        return distance(offset_to_axial(coord), offset_to_axial(goal))

    open_heap: list[tuple[int, int, OffsetCoord]] = []
    counter = 0
    heapq.heappush(open_heap, (heuristic(start), counter, start))
    came_from: dict[OffsetCoord, OffsetCoord] = {}
    g_score: dict[OffsetCoord, int] = {start: 0}

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == goal:
            path: list[OffsetCoord] = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return tuple(path)

        for neighbour in _offset_neighbours(current):
            tile = game_map.get(neighbour)
            if tile is None:
                continue
            step_cost = army_terrain_move_cost(tile.terrain)
            if step_cost is None:
                continue
            tentative = g_score[current] + step_cost
            if tentative < g_score.get(neighbour, 109):
                came_from[neighbour] = current
                g_score[neighbour] = tentative
                counter += 1
                f_score = tentative + heuristic(neighbour)
                heapq.heappush(open_heap, (f_score, counter, neighbour))

    return ()


def path_cost_to_goal(
    start: OffsetCoord,
    goal: OffsetCoord,
    game_map: GameMap,
) -> int | None:
    """Return total movement cost along the shortest path, or ``None`` if unreachable."""

    path = shortest_path(start, goal, game_map)
    if not path:
        return None
    total = 0
    for coord in path[1:]:
        tile = game_map.get(coord)
        if tile is None:
            return None
        step = army_terrain_move_cost(tile.terrain)
        if step is None:
            return None
        total += step
    return total


def advance_along_path(
    start: OffsetCoord,
    goal: OffsetCoord,
    movement_budget: int,
    game_map: GameMap,
) -> OffsetCoord:
    """Move from ``start`` toward ``goal`` spending at most ``movement_budget`` movement points."""

    path = shortest_path(start, goal, game_map)
    if not path:
        return start

    budget = movement_budget
    position = start
    for next_coord in path[1:]:
        tile = game_map.get(next_coord)
        if tile is None:
            break
        step_cost = army_terrain_move_cost(tile.terrain)
        if step_cost is None or step_cost > budget:
            break
        budget -= step_cost
        position = next_coord
        if position == goal:
            break
    return position


def army_sort_key(
    army_position: OffsetCoord,
    citadel_coord: OffsetCoord,
    game_map: GameMap,
) -> tuple[int, int, int]:
    """Sort armies closest-to-citadel first; tie-break by ``(col, row)`` for stability."""

    cost = path_cost_to_goal(army_position, citadel_coord, game_map)
    unreachable_penalty = 109 if cost is None else cost
    return (unreachable_penalty, army_position.col, army_position.row)


__all__ = [
    "ARMY_PASSABLE_TERRAINS",
    "GRASSLAND_MOVE_COST",
    "WOODLAND_MOVE_COST",
    "advance_along_path",
    "army_sort_key",
    "army_terrain_move_cost",
    "path_cost_to_goal",
    "shortest_path",
]
