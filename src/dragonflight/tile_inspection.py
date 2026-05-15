"""Read-only tile inspection views for UI — no pygame (simulation-adjacent helpers)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .hex_coord import OffsetCoord
from .map_state import GameMap
from .settlement import Settlement, SettlementType
from .terrain import Terrain


@dataclass(frozen=True, slots=True)
class ArmyInspectInfo:
    """Live army stats for inspector panels."""

    hp: int
    max_hp: int
    atk: int
    dfn: int


@dataclass(frozen=True, slots=True)
class SettlementInspectInfo:
    """Live settlement stats for inspector panels."""

    settlement_type: SettlementType
    hp: int
    max_hp: int
    eco: int
    atk: int
    dfn: int
    aggression: int
    aggression_threshold: int


@dataclass(frozen=True, slots=True)
class TileInspectInfo:
    """Terrain identity plus optional live settlement stats."""

    coord: OffsetCoord
    terrain: Terrain
    settlement: SettlementInspectInfo | None
    army: ArmyInspectInfo | None = None


@dataclass(frozen=True, slots=True)
class TileInspectorLine:
    """One inspector row — :attr:`kind` drives UI styling and tests."""

    text: str
    kind: Literal["terrain", "settlement", "army", "notice"]


def tile_inspector_lines(info: TileInspectInfo) -> list[TileInspectorLine]:
    """Structured copy for the tile inspector.

    Terrain is always listed; settlement detail rows appear only when a live
    settlement is present on the tile.
    """

    lines: list[TileInspectorLine] = [
        TileInspectorLine(
            text=f"Terrain: {terrain_display_name(info.terrain)}",
            kind="terrain",
        ),
    ]
    if info.settlement is not None:
        s = info.settlement
        lines.extend(
            [
                TileInspectorLine(
                    text=f"Settlement type: {s.settlement_type.value}",
                    kind="settlement",
                ),
                TileInspectorLine(
                    text=f"HP: {s.hp} / {s.max_hp}",
                    kind="settlement",
                ),
                TileInspectorLine(text=f"Eco: {s.eco}", kind="settlement"),
                TileInspectorLine(
                    text=f"Atk / Def: {s.atk} / {s.dfn}",
                    kind="settlement",
                ),
                TileInspectorLine(
                    text=f"Aggression: {s.aggression} / {s.aggression_threshold}",
                    kind="settlement",
                ),
            ]
        )
    elif info.terrain is Terrain.SETTLEMENT:
        lines.append(
            TileInspectorLine(
                text="Settlement hex — no live settlement data for this tile.",
                kind="notice",
            ),
        )
    if info.army is not None:
        a = info.army
        lines.extend(
            [
                TileInspectorLine(text="Army", kind="army"),
                TileInspectorLine(
                    text=f"HP: {a.hp} / {a.max_hp}",
                    kind="army",
                ),
                TileInspectorLine(
                    text=f"Atk / Def: {a.atk} / {a.dfn}",
                    kind="army",
                ),
            ]
        )
    return lines


def army_inspect_info_from_entity(army: Any) -> ArmyInspectInfo | None:
    """Build inspector stats from a live army entity (simulation module or playtest stub)."""

    hp = int(getattr(army, "hp", 0))
    if hp <= 0:
        return None
    max_hp = int(getattr(army, "max_hp", hp))
    return ArmyInspectInfo(
        hp=hp,
        max_hp=max_hp,
        atk=int(getattr(army, "atk", 0)),
        dfn=int(getattr(army, "dfn", 0)),
    )


def tile_inspect_info(
    game_map: GameMap,
    coord: OffsetCoord,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
    armies_by_coord: Mapping[OffsetCoord, Any] | None = None,
) -> TileInspectInfo | None:
    """Return structured tile info for ``coord``, or ``None`` when off-map."""

    tile = game_map.get(coord)
    if tile is None:
        return None

    settlement_view: SettlementInspectInfo | None = None
    if tile.terrain is Terrain.SETTLEMENT:
        live = settlements_by_coord.get(coord)
        if live is not None:
            settlement_view = SettlementInspectInfo(
                settlement_type=live.settlement_type,
                hp=live.hp,
                max_hp=live.max_hp,
                eco=live.eco,
                atk=live.atk,
                dfn=live.dfn,
                aggression=live.aggression,
                aggression_threshold=live.aggression_threshold,
            )

    army_view: ArmyInspectInfo | None = None
    if armies_by_coord is not None:
        live_army = armies_by_coord.get(coord)
        if live_army is not None:
            army_view = army_inspect_info_from_entity(live_army)

    return TileInspectInfo(
        coord=coord,
        terrain=tile.terrain,
        settlement=settlement_view,
        army=army_view,
    )


def terrain_display_name(terrain: Terrain) -> str:
    """Human-readable terrain label for HUD/panels."""

    return terrain.value.replace("_", " ").title()
