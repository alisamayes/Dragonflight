"""Build live settlement entities from a loaded :class:`~dragonflight.map_state.GameMap`.

Each ``SETTLEMENT`` terrain tile with an authored subtype becomes a mutable
:class:`~dragonflight.settlement.Settlement` subclass instance at that coordinate.
The playtest / future turn loop owns the returned dict and runs phase hooks
(``on_settlement_phase_end``, combat, raids) against these objects — not against
``Tile`` alone.
"""

from __future__ import annotations

from .hex_coord import OffsetCoord
from .map_state import GameMap
from .settlement import City, Fort, Settlement, SettlementType, Village
from .terrain import Terrain


def settlements_by_coord_from_map(game_map: GameMap) -> dict[OffsetCoord, Settlement]:
    """Return one simulation settlement per settlement tile on ``game_map``."""

    out: dict[OffsetCoord, Settlement] = {}
    for tile in game_map:
        if tile.terrain is not Terrain.SETTLEMENT:
            continue
        kind = tile.settlement_kind or SettlementType.VILLAGE
        coord = tile.coord
        if kind is SettlementType.VILLAGE:
            out[coord] = Village(coord)
        elif kind is SettlementType.CITY:
            out[coord] = City(coord)
        else:
            out[coord] = Fort(coord)
    return out
