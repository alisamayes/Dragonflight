"""Unit tests for ``dragonflight.hex_coord``."""

from __future__ import annotations

import math

import pytest

from dragonflight.hex_coord import (
    AxialCoord,
    OffsetCoord,
    axial_to_offset,
    axial_to_pixel,
    distance,
    hex_corner_offset,
    neighbours,
    offset_to_axial,
    offset_to_pixel,
)

# Float tolerance used for pixel-space comparisons. The flat-top axial→pixel
# math involves sqrt(3), so exact equality is not safe; 1e-9 is comfortably
# below any rounding floor we care about for rendering.
_PIXEL_TOLERANCE: float = 1e-9


class TestDistance:
    def test_distance_is_zero_on_identity(self) -> None:
        coords = [
            AxialCoord(0, 0),
            AxialCoord(3, -2),
            AxialCoord(-7, 4),
            AxialCoord(16, 16),
        ]
        for c in coords:
            assert distance(c, c) == 0

    def test_distance_is_symmetric(self) -> None:
        pairs = [
            (AxialCoord(0, 0), AxialCoord(3, -2)),
            (AxialCoord(-1, 1), AxialCoord(4, 5)),
            (AxialCoord(10, -3), AxialCoord(-2, 8)),
        ]
        for a, b in pairs:
            assert distance(a, b) == distance(b, a)

    def test_distance_known_values(self) -> None:
        origin = AxialCoord(0, 0)
        # +q axis
        assert distance(origin, AxialCoord(3, 0)) == 3
        # +r axis
        assert distance(origin, AxialCoord(0, 3)) == 3
        # Cube-diagonal corner case where naive |dq|+|dr| would be 6 but the
        # axial distance is 3 because dq and dr have opposite signs along the
        # third (s) axis.
        assert distance(origin, AxialCoord(3, -3)) == 3


class TestNeighbours:
    def test_returns_six_distinct_coords_at_distance_one(self) -> None:
        for centre in [AxialCoord(0, 0), AxialCoord(5, -2), AxialCoord(-3, 7)]:
            ns = neighbours(centre)
            assert len(ns) == 6
            assert len(set(ns)) == 6, "neighbours must be distinct"
            for n in ns:
                assert distance(centre, n) == 1

    def test_neighbours_excludes_self(self) -> None:
        centre = AxialCoord(2, 2)
        assert centre not in neighbours(centre)


class TestAxialToPixel:
    def test_origin_maps_to_origin(self) -> None:
        x, y = axial_to_pixel(AxialCoord(0, 0), 30.0)
        assert x == pytest.approx(0.0, abs=_PIXEL_TOLERANCE)
        assert y == pytest.approx(0.0, abs=_PIXEL_TOLERANCE)

    def test_flat_top_formulas(self) -> None:
        size = 30.0
        x, y = axial_to_pixel(AxialCoord(2, 1), size)
        assert x == pytest.approx(size * 1.5 * 2, abs=_PIXEL_TOLERANCE)
        assert y == pytest.approx(size * math.sqrt(3.0) * (1 + 2 / 2.0), abs=_PIXEL_TOLERANCE)


class TestHexCornerOffset:
    def test_corner_zero_is_on_positive_x_axis_for_flat_top(self) -> None:
        dx, dy = hex_corner_offset(30.0, 0)
        assert dx == pytest.approx(30.0, abs=_PIXEL_TOLERANCE)
        assert dy == pytest.approx(0.0, abs=_PIXEL_TOLERANCE)

    def test_six_corners_lie_on_the_circle_of_radius_size(self) -> None:
        size = 30.0
        for corner in range(6):
            dx, dy = hex_corner_offset(size, corner)
            assert math.hypot(dx, dy) == pytest.approx(size, abs=_PIXEL_TOLERANCE)

    def test_out_of_range_corner_index_raises(self) -> None:
        with pytest.raises(ValueError):
            hex_corner_offset(30.0, 6)
        with pytest.raises(ValueError):
            hex_corner_offset(30.0, -1)


class TestOffsetAxialRoundTrip:
    """Conversion between offset and axial must be exact and collision-free.

    These cases pin the odd-q flat-top formulas (column-major, odd columns
    shifted down by half a hex) so a future refactor cannot silently flip
    parity, swap to even-q, or break the example map's citadel coordinate.
    """

    @pytest.mark.parametrize(
        "offset",
        [
            OffsetCoord(0, 0),
            OffsetCoord(1, 0),
            OffsetCoord(2, 0),
            OffsetCoord(15, 16),
            OffsetCoord(29, 29),
        ],
    )
    def test_offset_axial_round_trip_is_identity(self, offset: OffsetCoord) -> None:
        assert axial_to_offset(offset_to_axial(offset)) == offset

    def test_known_axial_for_citadel_offset_coord(self) -> None:
        # The bundled map's citadel sits at offset (16, 16). The odd-q
        # formula gives axial r = 16 - (16 - 0) // 2 = 16 - 8 = 8.
        assert offset_to_axial(OffsetCoord(16, 16)) == AxialCoord(16, 8)

    def test_offsets_in_a_full_grid_map_to_unique_axials(self) -> None:
        # Equivalent to the example map's 30×30 surface footprint. If parity
        # ever flipped, two different offset coords would collide on the
        # same axial value and this assertion would catch it.
        seen: set[AxialCoord] = set()
        for col in range(30):
            for row in range(30):
                axial = offset_to_axial(OffsetCoord(col, row))
                assert axial not in seen, f"axial collision at offset ({col}, {row})"
                seen.add(axial)
        assert len(seen) == 30 * 30

    def test_odd_column_row_increment_yields_distinct_axials(self) -> None:
        # Specifically pin the parity rule: stepping ``row`` by 1 inside a
        # single odd column produces distinct axial coords (no duplication
        # caused by the odd-q vertical shift).
        odd_col = 5
        axials = [offset_to_axial(OffsetCoord(odd_col, r)) for r in range(10)]
        assert len(set(axials)) == 10


class TestOffsetToPixel:
    """Pixel projection for odd-q flat-top: even columns sit at the row
    baseline, odd columns shift down by half a hex height."""

    def test_origin_maps_to_origin(self) -> None:
        x, y = offset_to_pixel(OffsetCoord(0, 0), 30.0)
        assert x == pytest.approx(0.0, abs=_PIXEL_TOLERANCE)
        assert y == pytest.approx(0.0, abs=_PIXEL_TOLERANCE)

    def test_odd_column_shifts_down_by_half_hex_height(self) -> None:
        x, y = offset_to_pixel(OffsetCoord(1, 0), 30.0)
        assert x == pytest.approx(45.0, abs=_PIXEL_TOLERANCE)
        # 30 * sqrt(3) / 2 — the half-hex vertical shift on odd columns.
        assert y == pytest.approx(30.0 * math.sqrt(3.0) / 2.0, abs=_PIXEL_TOLERANCE)

    def test_even_column_returns_to_baseline(self) -> None:
        x, y = offset_to_pixel(OffsetCoord(2, 0), 30.0)
        assert x == pytest.approx(90.0, abs=_PIXEL_TOLERANCE)
        # col=2 is even, so y returns to the baseline — confirms the zigzag.
        assert y == pytest.approx(0.0, abs=_PIXEL_TOLERANCE)
