"""World-state primitives — the simulation's single source of truth.

This module owns the in-memory representation of a Dragonflight map. The
loader (``map_loader``) constructs a ``GameMap`` from validated map data; the
renderer and rule systems consume it read-only. ``GameMap`` and ``Tile`` are
``frozen=True`` so callers cannot rebind their fields after construction —
this enforces the architectural rule that simulation state has one owner
(spec §13, §19; brief Acceptance Criteria).

Coordinate identity (round Wave-2-revision-1 amendment): tiles are keyed by
:class:`~dragonflight.hex_coord.OffsetCoord` (odd-q flat-top), not axial.
This matches the bundled map editor's JSON vocabulary and the visual layout
the renderer needs. Axial math (distance, neighbours, pathfinding) is a
derived view available via ``hex_coord.offset_to_axial``; nothing in the
simulation state stores axial directly.

For Slice 1 ("see the map") no mutation is required; a non-frozen
``MapState`` may layer on top in later slices.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .hex_coord import OffsetCoord
from .terrain import Terrain


@dataclass(frozen=True, slots=True)
class Tile:
    """A single hex tile: its coordinate plus the terrain occupying it."""

    coord: OffsetCoord
    terrain: Terrain


@dataclass(frozen=True, slots=True)
class GameMap:
    """Authoritative snapshot of the world layout.

    Fields:
        width: Map width in hex columns.
        height: Map height in hex rows.
        hex_size: Pixel hex radius hint from the map authoring tool.
            Informational at the simulation level; renderers consume it.
        orientation: Hex orientation. Slice 1 only supports ``"flat"``;
            ``map_loader`` rejects other values at the boundary.
        tiles: Surface-layer tiles keyed by odd-q flat-top offset
            coordinate. The loader guarantees no duplicate keys, that every
            ``(col, row)`` lies inside ``[0, width) × [0, height)``, and that
            ``len(tiles) == width * height`` for the surface layer (spec §4).
    """

    width: int
    height: int
    hex_size: float
    orientation: str
    tiles: dict[OffsetCoord, Tile]

    def get(self, coord: OffsetCoord) -> Tile | None:
        """Return the tile at ``coord`` or ``None`` if absent."""
        return self.tiles.get(coord)

    def __iter__(self) -> Iterator[Tile]:
        """Iterate tiles. Order matches ``dict`` insertion order from the loader."""
        return iter(self.tiles.values())
