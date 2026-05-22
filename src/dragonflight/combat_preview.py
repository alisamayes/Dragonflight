"""Non-mutating previews of the next combat damage round for GUI panels."""

from __future__ import annotations

from dataclasses import dataclass

from .army import Army
from .combat_math import damage_dragon_attacks, damage_settlement_or_army_attacks
from .combatant_stats import army_effective_atk, settlement_effective_atk
from .dragon import Dragon
from .dragon_abilities import (
    army_defence_for_round,
    effective_attack,
    effective_defence,
    enemy_can_retaliate,
    mitigated_damage_taken,
    preview_flame_buffer_damage_multiplier,
    preview_vivify_attack_power_bonus,
    settlement_defence_for_round,
    thorns_damage,
)
from .map_state import GameMap
from .settlement import Settlement


@dataclass(frozen=True, slots=True)
class CombatDamagePreview:
    damage_to_dragon: int
    damage_to_enemy: int  # settlement or army


def preview_settlement_round(
    dragon: Dragon, settlement: Settlement, world: GameMap
) -> CombatDamagePreview:
    """Mirror :func:`~dragonflight.settlement.resolve_settlement_combat_round` damage numbers."""

    base_attack = effective_attack(dragon, world=world) + preview_vivify_attack_power_bonus(dragon)
    boosted_attack = max(
        1, int(round(base_attack * preview_flame_buffer_damage_multiplier(dragon)))
    )
    dfn = settlement_defence_for_round(dragon, settlement)
    dragon_to_target = damage_dragon_attacks(boosted_attack, dfn)
    raw_to_dragon = (
        damage_settlement_or_army_attacks(
            settlement_effective_atk(settlement), effective_defence(dragon)
        )
        if enemy_can_retaliate(dragon)
        else 0
    )
    target_to_dragon = mitigated_damage_taken(dragon, raw_to_dragon)
    thorns = thorns_damage(dragon, raw_to_dragon)
    return CombatDamagePreview(
        damage_to_dragon=target_to_dragon,
        damage_to_enemy=dragon_to_target + thorns,
    )


def preview_army_round(dragon: Dragon, army: Army, world: GameMap) -> CombatDamagePreview:
    """Mirror :func:`~dragonflight.army.resolve_army_combat_round` damage numbers."""

    base_attack = effective_attack(dragon, world=world) + preview_vivify_attack_power_bonus(dragon)
    boosted_attack = max(
        1, int(round(base_attack * preview_flame_buffer_damage_multiplier(dragon)))
    )
    dfn = army_defence_for_round(dragon, army)
    dragon_to_target = damage_dragon_attacks(boosted_attack, dfn)
    raw_to_dragon = (
        damage_settlement_or_army_attacks(army_effective_atk(army), effective_defence(dragon))
        if enemy_can_retaliate(dragon)
        else 0
    )
    target_to_dragon = mitigated_damage_taken(dragon, raw_to_dragon)
    thorns = thorns_damage(dragon, raw_to_dragon)
    return CombatDamagePreview(
        damage_to_dragon=target_to_dragon,
        damage_to_enemy=dragon_to_target + thorns,
    )


__all__ = ["CombatDamagePreview", "preview_army_round", "preview_settlement_round"]
