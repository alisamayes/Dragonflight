"""Hex-coordinate primitives for Dragonflight (axial + offset).

Two coordinate spaces coexist here, with a clear separation of concerns:

* **Offset (odd-q flat-top, ``col``/``row``)** — the **data identity** used by the
  bundled map editor's JSON, by ``map_state.Tile.coord``, and by the renderer's
  visual layout. Adjacent odd columns are shifted down by half a hex; this is
  what makes a ``width × height`` map render as a square instead of a rhombus.
* **Axial (``q``/``r``)** — the **math identity** used by spec num4 / num14 for
  distance, neighbour walks, and pathfinding. Slice 1 has no math consumers
  yet, but the primitives are kept stable so future systems pick them up
  unchanged.

Conversion goes through :func:`offset_to_axial` / :func:`axial_to_offset` at
the simulation boundary; nothing else should re-derive the formulas locally.

Flat-top orientation is the only orientation Slice 1 supports
(``settings.orientation = "flat"`` in map data).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Six axial neighbour deltas in a stable order.
# Order matches the Red Blob Games "axial directions" reference (E, NE, NW, W, SW, SE
# in flat-top terms). Tests rely only on the result being length 6, distinct, and
# all at distance 1, but the order is fixed so callers can rely on it.
_AXIAL_DIRECTIONS: tuple[tuple[int, int], ...] = (
    (+1, 0),
    (+1, -1),
    (0, -1),
    (-1, 0),
    (-1, +1),
    (0, +1),
)

# Number of corners of a hex (flat-top, indices 0..5).
HEX_CORNERS: int = 6

# Angular step between consecutive flat-top corners, in radians.
_FLAT_TOP_CORNER_STEP_RADIANS: float = math.pi / 3.0  # 60 degrees


@dataclass(frozen=True, slots=True)
class AxialCoord:
    """Immutable axial hex coordinate.

    ``q`` is the column axis, ``r`` is the row axis. The third cube axis is
    ``s = -q - r`` (kept implicit; do not store it).
    """

    q: int
    r: int


def neighbours(
    coord: AxialCoord,
) -> tuple[AxialCoord, AxialCoord, AxialCoord, AxialCoord, AxialCoord, AxialCoord]:
    """Return the six axial neighbours of ``coord`` in a stable order.

    The order is fixed (see ``_AXIAL_DIRECTIONS``). Each result is at axial
    distance 1 from ``coord``.
    """
    q, r = coord.q, coord.r
    return (
        AxialCoord(q + _AXIAL_DIRECTIONS[0][0], r + _AXIAL_DIRECTIONS[0][1]),
        AxialCoord(q + _AXIAL_DIRECTIONS[1][0], r + _AXIAL_DIRECTIONS[1][1]),
        AxialCoord(q + _AXIAL_DIRECTIONS[2][0], r + _AXIAL_DIRECTIONS[2][1]),
        AxialCoord(q + _AXIAL_DIRECTIONS[3][0], r + _AXIAL_DIRECTIONS[3][1]),
        AxialCoord(q + _AXIAL_DIRECTIONS[4][0], r + _AXIAL_DIRECTIONS[4][1]),
        AxialCoord(q + _AXIAL_DIRECTIONS[5][0], r + _AXIAL_DIRECTIONS[5][1]),
    )


def distance(a: AxialCoord, b: AxialCoord) -> int:
    """Axial / cube distance between ``a`` and ``b``.

    Equivalent to ``(|dq| + |dr| + |ds|) / 2`` where ``ds = -dq - dr``. Always a
    non-negative integer because ``a`` and ``b`` are integer coordinates.
    """
    dq = a.q - b.q
    dr = a.r - b.r
    ds = -dq - dr
    return (abs(dq) + abs(dr) + abs(ds)) // 2


def axial_to_pixel(coord: AxialCoord, hex_size: float) -> tuple[float, float]:
    """Project an axial coordinate to pixel-space center for a flat-top hex.

    Uses the standard flat-top axial→pixel formulas:

    * ``x = hex_size * 1.5 * q``
    * ``y = hex_size * sqrt(3) * (r + q / 2)``

    ``hex_size`` is the hex's "radius" (center-to-corner distance) in pixels.
    """
    x = hex_size * 1.5 * coord.q
    y = hex_size * math.sqrt(3.0) * (coord.r + coord.q / 2.0)
    return (x, y)


def hex_corner_offset(hex_size: float, corner: int) -> tuple[float, float]:
    """Return ``(dx, dy)`` of corner ``corner`` relative to a flat-top hex center.

    Corners are indexed ``0..5`` at angles ``0°, 60°, 120°, 180°, 240°, 300°``.
    Indices outside that range raise ``ValueError`` so renderer bugs surface
    early instead of silently wrapping.

    Corner geometry is identical for the offset and axial views (a single hex
    has the same shape regardless of how its centre is addressed), so this
    helper is shared by both paths.
    """
    if not 0 <= corner < HEX_CORNERS:
        raise ValueError(f"corner index {corner} out of range; must be in [0, {HEX_CORNERS - 1}]")
    angle = _FLAT_TOP_CORNER_STEP_RADIANS * corner
    return (hex_size * math.cos(angle), hex_size * math.sin(angle))


# --- Offset (odd-q flat-top) coordinate system ------------------------------
#
# Offset is the data identity: it matches the bundled map editor's JSON
# vocabulary (``q`` in JSON is the column, ``r`` in JSON is the row) and the
# visual layout the user expects (a ``width × height`` map renders as a
# square, with odd columns shifted down by half a hex). Round Wave-2-revision-1
# moved ``map_state.Tile.coord`` from ``AxialCoord`` to :class:`OffsetCoord`
# because rendering and authoring are both offset-native; axial is now a
# derived view exposed via :func:`offset_to_axial`.


@dataclass(frozen=True, slots=True)
class OffsetCoord:
    """Odd-q flat-top offset coordinate (column, row).

    Matches the bundled map editor's JSON vocabulary. The visual layout treats
    even columns as sitting at the row baseline and odd columns as shifted
    down by half a hex (see :func:`offset_to_pixel`). For axial math (distance,
    neighbour walks, pathfinding) convert via :func:`offset_to_axial`.
    """

    col: int
    row: int


def offset_to_axial(offset: OffsetCoord) -> AxialCoord:
    """Convert an odd-q flat-top offset coord to its axial equivalent.

    Formulas:

    * ``axial.q = offset.col``
    * ``axial.r = offset.row - (offset.col - (offset.col & 1)) // 2``

    The ``& 1`` term is what makes this *odd-q*: even columns subtract
    ``col // 2`` from ``row``; odd columns subtract ``(col - 1) // 2``. That
    bias is what bends the offset grid back onto an axial lattice.
    """
    col = offset.col
    row = offset.row
    return AxialCoord(q=col, r=row - (col - (col & 1)) // 2)


def axial_to_offset(axial: AxialCoord) -> OffsetCoord:
    """Inverse of :func:`offset_to_axial` for odd-q flat-top.

    Formulas:

    * ``offset.col = axial.q``
    * ``offset.row = axial.r + (axial.q - (axial.q & 1)) // 2``
    """
    q = axial.q
    r = axial.r
    return OffsetCoord(col=q, row=r + (q - (q & 1)) // 2)


def offset_to_pixel(offset: OffsetCoord, hex_size: float) -> tuple[float, float]:
    """Project an offset coord to flat-top pixel-space centre.

    Formulas (odd-q):

    * ``x = hex_size * 1.5 * col``
    * ``y = hex_size * sqrt(3) * (row + 0.5 * (col & 1))``

    Odd columns get an extra half-hex vertical shift (``0.5 * 1``); even
    columns sit at the row baseline (``0.5 * 0``). This is the visual zigzag
    that distinguishes odd-q offset from naive square-grid layout.

    ``hex_size`` is the hex's "radius" (centre-to-corner distance) in pixels.
    """
    col = offset.col
    row = offset.row
    x = hex_size * 1.5 * col
    y = hex_size * math.sqrt(3.0) * (row + 0.5 * (col & 1))
    return (x, y)
