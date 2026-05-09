"""Integration tests for ``dragonflight.map_loader`` against the bundled map."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_loader import MapLoadError, load_map
from dragonflight.map_state import GameMap
from dragonflight.terrain import Terrain

# --- Test fixtures ----------------------------------------------------------

# The example map authored by the Game Map Designer (Wave 1 output). It is
# the canonical Slice 1 map and the single source of truth for these expected
# counts. If a future map edit changes terrain counts these tests must be
# updated *together* with the JSON; they are intentionally tightly coupled
# so that the loader's resolution rules cannot silently drift.
_EXAMPLE_MAP_PATH: Path = Path(__file__).resolve().parent.parent / "assets" / "example_hexmap.json"

#: Per-terrain tile counts in the example map post-Wave-1 schemaVersion 3.
_EXPECTED_COUNTS: dict[Terrain, int] = {
    Terrain.GRASSLAND: 539,
    Terrain.WOODLAND: 180,
    Terrain.MOUNTAIN: 61,
    Terrain.RIVER: 106,
    Terrain.BRIDGE: 4,
    Terrain.SETTLEMENT: 9,
    Terrain.CITADEL: 1,
}


@pytest.fixture(scope="module")
def example_map() -> GameMap:
    """Loaded ``GameMap`` for the bundled example map.

    Module-scoped because parsing 900 tiles + Pydantic validation per test is
    wasteful when every assertion is read-only.
    """
    return load_map(_EXAMPLE_MAP_PATH)


def _example_map_raw() -> dict[str, Any]:
    """Load the bundled example map as a plain dict, ready to mutate.

    Tests that need a *bad* fixture should call this, mutate one field, dump
    to ``tmp_path``, then call :func:`load_map`. We never mutate the bundled
    JSON on disk (Game Map Designer owns it).
    """
    return json.loads(_EXAMPLE_MAP_PATH.read_text(encoding="utf-8"))


def _write_mutated_map(tmp_path: Path, mutator: Any, name: str = "bad.json") -> Path:
    """Apply ``mutator`` to a fresh copy of the example map and write it out."""
    raw = _example_map_raw()
    mutator(raw)
    out = tmp_path / name
    out.write_text(json.dumps(raw), encoding="utf-8")
    return out


# --- Happy-path tests -------------------------------------------------------


class TestExampleMapShape:
    def test_dimensions_and_orientation(self, example_map: GameMap) -> None:
        assert example_map.width == 30
        assert example_map.height == 30
        assert example_map.hex_size == pytest.approx(30.0)
        assert example_map.orientation == "flat"

    def test_tile_count(self, example_map: GameMap) -> None:
        assert len(example_map.tiles) == 900
        # __iter__ should expose the same number of tiles
        assert sum(1 for _ in example_map) == 900

    def test_terrain_counts(self, example_map: GameMap) -> None:
        counts = Counter(tile.terrain for tile in example_map)
        for terrain, expected in _EXPECTED_COUNTS.items():
            assert counts[terrain] == expected, (
                f"{terrain.name} count drifted: got {counts[terrain]}, expected {expected}"
            )
        # Total must equal the surface tile count, i.e. no terrain is unaccounted for.
        assert sum(counts.values()) == 900

    def test_citadel_at_expected_coord(self, example_map: GameMap) -> None:
        # Round Wave-2-revision-1: the loader is offset-native, so the citadel
        # is keyed by the JSON's literal (q, r) = (16, 16) interpreted as an
        # odd-q ``OffsetCoord``. Axial math (e.g. distance to settlements)
        # still works via ``hex_coord.offset_to_axial``.
        citadel_coord = OffsetCoord(16, 16)
        tile = example_map.get(citadel_coord)
        assert tile is not None, "no tile at the expected citadel coordinate"
        assert tile.terrain is Terrain.CITADEL


# --- Failure-path tests -----------------------------------------------------


class TestUnknownHexType:
    def test_ocean_tile_raises_with_coordinate_in_message(self, tmp_path: Path) -> None:
        def mutate(raw: dict[str, Any]) -> None:
            bad_key = "3,18,surface"
            assert bad_key in raw["hexes"], (
                f"fixture assumption broken: expected {bad_key} in example map"
            )
            raw["hexes"][bad_key]["hexType"] = "ocean"

        bad_path = _write_mutated_map(tmp_path, mutate, name="bad_ocean_hexmap.json")
        with pytest.raises(MapLoadError) as exc_info:
            load_map(bad_path)
        message = str(exc_info.value)
        # Coordinate must appear so authors can find the tile fast.
        assert "(3, 18)" in message
        # The hexType that broke must be quoted in the error.
        assert "'ocean'" in message or '"ocean"' in message


class TestPydanticBounds:
    """Numeric fields on the Pydantic boundary must reject out-of-range input.

    These cases pin the Security L1 fix (round Wave-2-revision-1): every
    documented bound either traps the bad value at validation time or via a
    follow-on consistency check. Errors must come back as ``MapLoadError``,
    not raw ``ValidationError``, so callers don't have to depend on Pydantic
    types.
    """

    def test_width_zero_is_rejected(self, tmp_path: Path) -> None:
        def mutate(raw: dict[str, Any]) -> None:
            raw["settings"]["width"] = 0

        bad_path = _write_mutated_map(tmp_path, mutate, name="bad_width_zero.json")
        with pytest.raises(MapLoadError) as exc_info:
            load_map(bad_path)
        message = str(exc_info.value)
        assert "width" in message

    def test_width_above_cap_is_rejected(self, tmp_path: Path) -> None:
        def mutate(raw: dict[str, Any]) -> None:
            raw["settings"]["width"] = 10000

        bad_path = _write_mutated_map(tmp_path, mutate, name="bad_width_huge.json")
        with pytest.raises(MapLoadError) as exc_info:
            load_map(bad_path)
        message = str(exc_info.value)
        assert "width" in message

    def test_hex_size_zero_is_rejected(self, tmp_path: Path) -> None:
        def mutate(raw: dict[str, Any]) -> None:
            raw["settings"]["hexSize"] = 0

        bad_path = _write_mutated_map(tmp_path, mutate, name="bad_hex_size_zero.json")
        with pytest.raises(MapLoadError) as exc_info:
            load_map(bad_path)
        message = str(exc_info.value)
        assert "hexSize" in message

    def test_schema_version_above_cap_is_rejected(self, tmp_path: Path) -> None:
        def mutate(raw: dict[str, Any]) -> None:
            raw["schemaVersion"] = 200

        bad_path = _write_mutated_map(tmp_path, mutate, name="bad_schema_v.json")
        with pytest.raises(MapLoadError) as exc_info:
            load_map(bad_path)
        message = str(exc_info.value)
        assert "schemaVersion" in message

    def test_huge_tile_q_is_rejected(self, tmp_path: Path) -> None:
        def mutate(raw: dict[str, Any]) -> None:
            # Mutate a known-good tile so other fields stay valid.
            target = "3,18,surface"
            assert target in raw["hexes"]
            raw["hexes"][target]["q"] = 999999

        bad_path = _write_mutated_map(tmp_path, mutate, name="bad_tile_q.json")
        with pytest.raises(MapLoadError) as exc_info:
            load_map(bad_path)
        message = str(exc_info.value)
        # The Pydantic bound or the runtime range check must complain about
        # ``q`` (the field name) — either path is acceptable; we just don't
        # want a vague "validation failed" with no field hint.
        assert "q" in message
