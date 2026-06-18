"""Fog-of-war visibility for play sessions — no pygame."""

from __future__ import annotations

from dataclasses import dataclass, field

from .dragon import Dragon
from .dragon_abilities import effective_flight_range
from .hex_coord import OffsetCoord
from .map_state import GameMap

#: Uniform fill for hexes not yet revealed this session.
#: Slightly lighter gray so fog feels softer and reveals stand out more.
FOG_UNREVEALED_RGB: tuple[int, int, int] = (130, 130, 138)
FOG_FILL_RGB: tuple[int, int, int] = FOG_UNREVEALED_RGB


@dataclass
class FogOfWarState:
    """Tiles revealed during the current play session (persistent until reset)."""

    revealed: set[OffsetCoord] = field(default_factory=set)

    def clear(self) -> None:
        self.revealed.clear()

    def reveal(self, coord: OffsetCoord) -> None:
        self.revealed.add(coord)


def is_revealed(fog: FogOfWarState, coord: OffsetCoord) -> bool:
    """Return whether ``coord`` has been revealed this session."""
    return coord in fog.revealed


def reveal_coords_in_range(
    fog: FogOfWarState,
    dragon: Dragon,
    game_map: GameMap,
) -> None:
    """Reveal every map hex within :func:`~dragonflight.dragon_abilities.effective_flight_range`."""

    flight = effective_flight_range(dragon, world=game_map)
    for tile in game_map:
        if dragon.hex_distance_to(tile.coord) <= flight:
            fog.reveal(tile.coord)


def init_fog_from_dragon(fog: FogOfWarState, dragon: Dragon, game_map: GameMap) -> None:
    """Reset revealed tiles and reveal from the dragon's current position."""
    fog.clear()
    reveal_coords_in_range(fog, dragon, game_map)
