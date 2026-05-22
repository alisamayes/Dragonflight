"""Settlement and army stat modifier bags (Phase 2)."""

from __future__ import annotations

from dragonflight.army import Army, ArmyKind, merge_army_stacks
from dragonflight.combatant_stats import (
    army_combatant_view,
    army_effective_atk,
    settlement_combatant_view,
    settlement_effective_atk,
)
from dragonflight.dragon_abilities import (
    ANCIENTS_ROAR_DURATION_HOURS,
    ANCIENTS_ROAR_SOURCE,
    apply_time_spent,
    try_use_ability,
)
from dragonflight.dragon_playables import Blackgon, Purplegon
from dragonflight.entity_stats import (
    ModifierExpiry,
    ModifierKind,
    StatKey,
    StatModifier,
    add_modifier,
)
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.settlement import Fort, Village
from dragonflight.terrain import Terrain


def _world(*tiles: Tile) -> GameMap:
    return GameMap(
        width=10,
        height=10,
        hex_size=30.0,
        orientation="flat",
        tiles={tile.coord: tile for tile in tiles},
    )


def test_settlement_effective_atk_applies_roar_modifier() -> None:
    settlement = Village(OffsetCoord(0, 0))
    add_modifier(
        settlement.stat_modifiers,
        StatModifier(
            stat=StatKey.ATK,
            kind=ModifierKind.PERCENT_MULT,
            value=0.70,
            expiry=ModifierExpiry.HOURS,
            hours_remaining=12.0,
            source=ANCIENTS_ROAR_SOURCE,
        ),
    )
    assert settlement.atk == 50
    assert settlement_effective_atk(settlement) == 35


def test_ancients_roar_debuff_reverts_after_hours_tick() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Blackgon.new_at(OffsetCoord(1, 0))
    dragon.level = 10
    settlement = Fort(coord)
    world = _world(
        Tile(coord=coord, terrain=Terrain.SETTLEMENT),
        Tile(coord=OffsetCoord(1, 0), terrain=Terrain.GRASSLAND),
    )
    result = try_use_ability(
        dragon,
        "Ancient's Roar",
        world=world,
        citadel_coord=OffsetCoord(5, 0),
        settlements_by_coord={coord: settlement},
    )
    assert result.ok
    assert settlement.atk == 80
    assert settlement_effective_atk(settlement) == 56
    apply_time_spent(dragon, ANCIENTS_ROAR_DURATION_HOURS, settlements=[settlement])
    assert settlement_effective_atk(settlement) == 80


def test_growth_mutates_base_atk_not_modifier_bag() -> None:
    village = Village(OffsetCoord(0, 0))
    add_modifier(
        village.stat_modifiers,
        StatModifier(
            stat=StatKey.ATK,
            kind=ModifierKind.PERCENT_MULT,
            value=0.70,
            expiry=ModifierExpiry.HOURS,
            hours_remaining=5.0,
            source=ANCIENTS_ROAR_SOURCE,
        ),
    )
    village.on_settlement_phase_end()
    assert village.atk == 55
    view = settlement_combatant_view(village)
    assert view.effective_atk == 38


def test_merge_army_stacks_sums_base_stats_and_clears_modifiers() -> None:
    coord = OffsetCoord(2, 2)
    a = Army(hp=100, max_hp=100, atk=40, dfn=20, movement_speed=8, position=coord)
    b = Army(hp=80, max_hp=80, atk=30, dfn=10, movement_speed=10, position=coord)
    add_modifier(
        a.stat_modifiers,
        StatModifier(
            stat=StatKey.ATK,
            kind=ModifierKind.PERCENT_MULT,
            value=0.70,
            expiry=ModifierExpiry.HOURS,
            hours_remaining=12.0,
            source=ANCIENTS_ROAR_SOURCE,
        ),
    )
    merged = merge_army_stacks([a, b])
    assert len(merged) == 1
    stack = merged[0]
    assert stack.atk == 70
    assert stack.dfn == 30
    assert stack.stat_modifiers.modifiers == []
    assert army_effective_atk(stack) == 70


def test_army_combatant_view_reflects_effective_stats() -> None:
    army = Army(
        hp=50,
        max_hp=100,
        atk=100,
        dfn=40,
        movement_speed=8,
        position=OffsetCoord(0, 0),
        kind=ArmyKind.VILLAGE,
    )
    add_modifier(
        army.stat_modifiers,
        StatModifier(
            stat=StatKey.ATK,
            kind=ModifierKind.PERCENT_MULT,
            value=0.90,
            expiry=ModifierExpiry.HOURS,
            hours_remaining=1_000_000.0,
            source="Ice Talons",
        ),
    )
    view = army_combatant_view(army)
    assert view.base_atk == 100
    assert view.effective_atk == 90
    assert view.atk_debuffed


def test_ice_talons_stacks_via_modifiers_without_base_mutation() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Purplegon.new_at(coord)
    dragon.level = 5
    army = Army(hp=400, max_hp=400, atk=100, dfn=20, movement_speed=8, position=coord)
    world = _world(Tile(coord=coord, terrain=Terrain.GRASSLAND))
    from dragonflight.army import resolve_army_combat_round

    resolve_army_combat_round(dragon, army, world, citadel_coord=OffsetCoord(5, 0))
    resolve_army_combat_round(dragon, army, world, citadel_coord=OffsetCoord(5, 0))
    assert army.atk == 100
    assert army_effective_atk(army) == 81
