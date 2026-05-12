"""Tests for spawning simulation settlements from map tiles."""

from __future__ import annotations

from pathlib import Path

from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_loader import load_map
from dragonflight.settlement import City, Fort, SettlementType, Village
from dragonflight.terrain import Terrain
from dragonflight.world_settlements import settlements_by_coord_from_map

_EXAMPLE_MAP_PATH: Path = Path(__file__).resolve().parent.parent / "assets" / "example_hexmap.json"


def test_example_map_spawns_one_entity_per_settlement_tile() -> None:
    gm = load_map(_EXAMPLE_MAP_PATH)
    by_coord = settlements_by_coord_from_map(gm)
    settlement_tiles = sum(1 for t in gm if t.terrain is Terrain.SETTLEMENT)
    assert len(by_coord) == settlement_tiles == 9
    assert all(isinstance(v, Village) for v in by_coord.values())


def test_city_tile_spawns_city_instance(tmp_path: Path) -> None:
    import json
    from typing import Any

    raw: dict[str, Any] = json.loads(_EXAMPLE_MAP_PATH.read_text(encoding="utf-8"))
    raw["hexes"]["2,2,surface"]["settlementType"] = "city"
    p = tmp_path / "one_city.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    gm = load_map(p)
    ent = settlements_by_coord_from_map(gm)[OffsetCoord(2, 2)]
    assert isinstance(ent, City)
    assert ent.settlement_type is SettlementType.CITY


def test_fort_tile_spawns_fort_instance(tmp_path: Path) -> None:
    import json
    from typing import Any

    raw: dict[str, Any] = json.loads(_EXAMPLE_MAP_PATH.read_text(encoding="utf-8"))
    raw["hexes"]["2,2,surface"]["settlementType"] = "fort"
    p = tmp_path / "one_fort.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    gm = load_map(p)
    ent = settlements_by_coord_from_map(gm)[OffsetCoord(2, 2)]
    assert isinstance(ent, Fort)
    assert ent.settlement_type is SettlementType.FORT
