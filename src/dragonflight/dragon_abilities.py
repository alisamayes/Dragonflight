"""Runtime draconic ability state and simulation hooks.

Cooldowns are measured in player-day boundaries: using a ``1 turn CD`` ability
sets a one-turn counter, and :meth:`Dragon.begin_new_day_at_citadel` decrements
that counter before the next day starts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .combat_math import damage_dragon_attacks
from .dragon_defaults import HOURS_PER_DRAGON_DAY
from .hex_coord import OffsetCoord, distance, offset_to_axial
from .terrain import Terrain

if TYPE_CHECKING:
    from .dragon import Dragon
    from .dragon_playables import DragonAbilitySpec
    from .map_state import GameMap
    from .settlement import Settlement

FLAME_BUFFER_STACK_PERCENT: int = 3
FLAME_BUFFER_MAX_STACKS: int = 10
SPIKED_SCALES_DEFENCE_PERCENT: int = 10
HEALING_CRYSTAL_PERCENT_PER_HOUR: float = 2.0
FORESIGHT_DAMAGE_UNDO_PERCENT: int = 10
ICE_TALONS_ATTACK_REDUCTION_PERCENT: int = 10
MOUNTAINS_BOON_RANGE_HEXES: int = 3
MOUNTAINS_BOON_ATTACK_MULTIPLIER: float = 1.10
MOUNTAINS_BOON_SPEED_BONUS: float = 2.0
FIERY_MALICE_MULTIPLIER: float = 1.50
DEFEND_THE_CITADEL_TRAVEL_DIVISOR: float = 3.0
VIVIFY_HP_BONUS_PERCENT: int = 20
VIVIFY_ATTACK_SACRIFICE_PERCENT: int = 20
VIVIFY_SACRIFICE_DURATION_HOURS: float = 5.0
VIVIFY_SACRIFICE_EFFECT_NAME: str = "Vivify sacrifice"
TREMORS_DEFENCE_MULTIPLIER: float = 0.85


@dataclass(frozen=True, slots=True)
class AbilityUseResult:
    """Structured response from the ability-use boundary."""

    ok: bool
    reason: str
    ability_name: str
    target_required: bool = False


def _ability_specs(dragon: Dragon) -> tuple[DragonAbilitySpec, ...]:
    return tuple(getattr(type(dragon), "ABILITIES", ()))


def ability_spec_by_name(dragon: Dragon, ability_name: str) -> DragonAbilitySpec | None:
    for spec in _ability_specs(dragon):
        if spec.name == ability_name:
            return spec
    return None


def synchronize_unlocked_abilities(dragon: Dragon) -> None:
    """Persist all specs unlocked by the dragon's current level on the dragon state."""

    unlocked = list(dragon.unlocked_ability_names)
    for spec in _ability_specs(dragon):
        if dragon.level >= spec.unlock_level and spec.name not in unlocked:
            unlocked.append(spec.name)
    dragon.unlocked_ability_names = tuple(unlocked)


def unlocked_ability_specs(dragon: Dragon) -> tuple[DragonAbilitySpec, ...]:
    synchronize_unlocked_abilities(dragon)
    unlocked = set(dragon.unlocked_ability_names)
    return tuple(spec for spec in _ability_specs(dragon) if spec.name in unlocked)


def passive_active(dragon: Dragon, name: str) -> bool:
    synchronize_unlocked_abilities(dragon)
    return name in dragon.unlocked_ability_names


def cooldown_turns_from_text(text: str) -> int:
    match = re.search(r"(\d+)\s*turn", text, flags=re.IGNORECASE)
    if match is None:
        return 0
    return max(0, int(match.group(1)))


def cooldown_remaining(dragon: Dragon, ability_name: str) -> int:
    return max(0, int(dragon.ability_cooldowns.get(ability_name, 0)))


def extra_charges_remaining(dragon: Dragon, ability_name: str) -> int:
    return max(0, int(dragon.ability_extra_charges_today.get(ability_name, 0)))


def active_effect_hours_remaining(dragon: Dragon, effect_name: str) -> float:
    return max(0.0, float(dragon.active_ability_hours.get(effect_name, 0.0)))


def begin_new_turn(dragon: Dragon) -> None:
    """Advance cooldowns/effects at a citadel day boundary."""

    synchronize_unlocked_abilities(dragon)
    for name, remaining in list(dragon.ability_cooldowns.items()):
        if remaining <= 1:
            dragon.ability_cooldowns.pop(name, None)
        else:
            dragon.ability_cooldowns[name] = remaining - 1
    dragon.ability_extra_charges_today.clear()
    dragon.active_ability_hours.clear()
    dragon.passive_stacks["Flame buffer"] = 0
    vivify_bonus = int(dragon.passive_stacks.pop("Vivify max hp bonus", 0))
    if vivify_bonus > 0:
        old_max = dragon.max_hp
        dragon.max_hp = max(1, dragon.max_hp - vivify_bonus)
        dragon.hp = min(dragon.hp, dragon.max_hp)
        if old_max <= vivify_bonus:
            dragon.hp = max(0, dragon.hp)


def _cooldown_block(dragon: Dragon, spec: DragonAbilitySpec) -> AbilityUseResult | None:
    if cooldown_remaining(dragon, spec.name) <= 0:
        return None
    if spec.name == "Plasma Lance" and extra_charges_remaining(dragon, spec.name) > 0:
        return None
    return AbilityUseResult(
        False,
        f"{spec.name} cooldown: {cooldown_remaining(dragon, spec.name)} turn(s)",
        spec.name,
    )


def _start_cooldown(dragon: Dragon, spec: DragonAbilitySpec) -> None:
    turns = cooldown_turns_from_text(spec.cooldown)
    if turns > 0:
        dragon.ability_cooldowns[spec.name] = max(dragon.ability_cooldowns.get(spec.name, 0), turns)


def ability_requires_target(ability_name: str) -> bool:
    return ability_name in {
        "Plasma Lance",
        "Tempest Strike",
        "Absolute Zero Breath",
        "Tremors",
        "Terrascape",
    }


def try_use_ability(
    dragon: Dragon,
    ability_name: str,
    *,
    world: GameMap,
    citadel_coord: OffsetCoord,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
    target: OffsetCoord | None = None,
) -> AbilityUseResult:
    """Validate and apply an active ability, mutating state only on success."""

    synchronize_unlocked_abilities(dragon)
    spec = ability_spec_by_name(dragon, ability_name)
    if spec is None:
        return AbilityUseResult(False, f"unknown ability: {ability_name}", ability_name)
    if spec.category != "ability":
        return AbilityUseResult(False, f"{ability_name} is passive", ability_name)
    if spec.name not in dragon.unlocked_ability_names:
        return AbilityUseResult(False, f"{ability_name} is not unlocked", ability_name)
    if ability_requires_target(spec.name) and target is None:
        return AbilityUseResult(True, f"Choose a target tile for {ability_name}.", spec.name, True)

    cooldown_block = _cooldown_block(dragon, spec)
    if cooldown_block is not None:
        return cooldown_block

    if spec.name == "Plasma Lance":
        assert target is not None
        result = _plasma_lance(dragon, world, settlements_by_coord, target)
    elif spec.name == "Fiery Malice":
        dragon.active_ability_hours[spec.name] = 3.0
        dragon.ability_extra_charges_today["Plasma Lance"] = (
            dragon.ability_extra_charges_today.get("Plasma Lance", 0) + 1
        )
        result = AbilityUseResult(
            True, "Fiery Malice active for 3 hours; +1 Plasma Lance today.", spec.name
        )
    elif spec.name == "Ancient's Roar":
        affected = _ancients_roar(dragon, settlements_by_coord)
        dragon.active_ability_hours[spec.name] = 12.0
        result = AbilityUseResult(
            True, f"Ancient's Roar weakened {affected} settlement(s).", spec.name
        )
    elif spec.name == "Defend the Citadel":
        result = _defend_the_citadel(dragon, citadel_coord)
    elif spec.name == "Draconic Resurgence":
        if dragon.hp >= dragon.max_hp // 2:
            return AbilityUseResult(False, "Draconic Resurgence requires HP below 50%.", spec.name)
        healed = max(1, dragon.max_hp * 25 // 100)
        dragon.hp = min(dragon.max_hp, dragon.hp + healed)
        dragon.active_ability_hours[spec.name] = 5.0
        result = AbilityUseResult(
            True, f"Restored {healed} HP; passive healing doubled for 5 hours.", spec.name
        )
    elif spec.name == "Vivify":
        bonus = max(1, dragon.max_hp * VIVIFY_HP_BONUS_PERCENT // 100)
        dragon.max_hp += bonus
        dragon.hp += bonus
        dragon.passive_stacks["Vivify max hp bonus"] = (
            dragon.passive_stacks.get("Vivify max hp bonus", 0) + bonus
        )
        dragon.active_ability_hours[VIVIFY_SACRIFICE_EFFECT_NAME] = VIVIFY_SACRIFICE_DURATION_HOURS
        result = AbilityUseResult(
            True,
            (
                f"Vivify raised max HP by {bonus} until next day; "
                f"sacrifice active for {VIVIFY_SACRIFICE_DURATION_HOURS:g}h."
            ),
            spec.name,
        )
    elif spec.name == "Timestop":
        dragon.active_ability_hours[spec.name] = 1.0
        result = AbilityUseResult(True, "Timestop active for the next hour.", spec.name)
    elif spec.name == "Chrono-conic pulse":
        dragon.active_ability_hours[spec.name] = HOURS_PER_DRAGON_DAY
        result = AbilityUseResult(
            True, "Chrono-conic pulse primed for this turn (army/growth hooks TODO).", spec.name
        )
    elif spec.name == "Tempest Strike":
        assert target is not None
        result = _tempest_strike(dragon, world, settlements_by_coord, target)
    elif spec.name == "Absolute Zero Breath":
        assert target is not None
        result = _absolute_zero_breath(dragon, world, settlements_by_coord, target)
    elif spec.name == "Tremors":
        assert target is not None
        result = _tremors(dragon, world, target)
    elif spec.name == "Terrascape":
        assert target is not None
        result = _terrascape(dragon, world, citadel_coord, settlements_by_coord, target)
    else:
        return AbilityUseResult(False, f"{spec.name} has no implementation yet.", spec.name)

    if result.ok:
        if (
            cooldown_remaining(dragon, spec.name) > 0
            and extra_charges_remaining(dragon, spec.name) > 0
        ):
            dragon.ability_extra_charges_today[spec.name] -= 1
        else:
            _start_cooldown(dragon, spec)
    return result


def _target_in_range(
    dragon: Dragon, target: OffsetCoord, world: GameMap
) -> AbilityUseResult | None:
    tile = world.get(target)
    if tile is None:
        return AbilityUseResult(False, "target tile is not on the map", "")
    if dragon.hex_distance_to(target) > effective_flight_range(dragon):
        return AbilityUseResult(False, "target tile is outside dragon range", "")
    return None


def _plasma_lance(
    dragon: Dragon,
    world: GameMap,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
    target: OffsetCoord,
) -> AbilityUseResult:
    invalid = _target_in_range(dragon, target, world)
    if invalid is not None:
        return AbilityUseResult(False, invalid.reason, "Plasma Lance")
    settlement = settlements_by_coord.get(target)
    if settlement is None:
        return AbilityUseResult(True, "Plasma Lance scorched the empty tile.", "Plasma Lance")
    damage = max(1, effective_attack(dragon, world=world))
    settlement.hp = max(0, settlement.hp - damage)
    return AbilityUseResult(
        True, f"Plasma Lance dealt {damage} defence-ignoring damage.", "Plasma Lance"
    )


def _ancients_roar(
    dragon: Dragon,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
) -> int:
    affected = 0
    for settlement in settlements_by_coord.values():
        if dragon.hex_distance_to(settlement.position) <= effective_flight_range(dragon):
            settlement.atk = max(0, int(math.floor(settlement.atk * 0.70)))
            affected += 1
    return affected


def _defend_the_citadel(dragon: Dragon, citadel_coord: OffsetCoord) -> AbilityUseResult:
    dist = dragon.hex_distance_to(citadel_coord)
    travel_hours = (
        dist
        / max(0.001, effective_speed_hexes_per_hour(dragon))
        / DEFEND_THE_CITADEL_TRAVEL_DIVISOR
    )
    if travel_hours > dragon.hours_remaining + 1e-9:
        return AbilityUseResult(
            False, "not enough hours to return to the citadel", "Defend the Citadel"
        )
    dragon.position = citadel_coord
    dragon.hours_remaining -= travel_hours
    apply_time_spent(dragon, travel_hours)
    dragon.active_ability_hours["Defend the Citadel"] = 3.0
    return AbilityUseResult(
        True,
        f"Returned to citadel in {travel_hours:.1f}h; defence boosted for 3h.",
        "Defend the Citadel",
    )


def _tempest_strike(
    dragon: Dragon,
    world: GameMap,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
    target: OffsetCoord,
) -> AbilityUseResult:
    invalid = _target_in_range(dragon, target, world)
    if invalid is not None:
        return AbilityUseResult(False, invalid.reason, "Tempest Strike")
    current = settlements_by_coord.get(target)
    if current is None:
        return AbilityUseResult(True, "Tempest Strike hit an empty tile.", "Tempest Strike")
    hit: set[OffsetCoord] = set()
    damage = max(1, effective_attack(dragon, world=world))
    total = 0
    while current is not None and damage > 0 and current.position not in hit:
        current.hp = max(0, current.hp - damage_dragon_attacks(damage, current.dfn))
        total += 1
        hit.add(current.position)
        damage //= 2
        current = _nearest_unhit_settlement(current.position, settlements_by_coord, hit)
    return AbilityUseResult(
        True, f"Tempest Strike chained through {total} settlement(s).", "Tempest Strike"
    )


def _nearest_unhit_settlement(
    origin: OffsetCoord,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
    hit: set[OffsetCoord],
) -> Settlement | None:
    candidates = [s for s in settlements_by_coord.values() if s.position not in hit]
    if not candidates:
        return None
    nearest = min(
        candidates,
        key=lambda s: distance(offset_to_axial(origin), offset_to_axial(s.position)),
    )
    if distance(offset_to_axial(origin), offset_to_axial(nearest.position)) > 1:
        return None
    return nearest


def _absolute_zero_breath(
    dragon: Dragon,
    world: GameMap,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
    target: OffsetCoord,
) -> AbilityUseResult:
    invalid = _target_in_range(dragon, target, world)
    if invalid is not None:
        return AbilityUseResult(False, invalid.reason, "Absolute Zero Breath")
    settlement = settlements_by_coord.get(target)
    if settlement is None:
        return AbilityUseResult(
            True, "Absolute Zero Breath froze an empty line.", "Absolute Zero Breath"
        )
    damage = max(1, int(round(effective_attack(dragon, world=world) * 1.5)))
    settlement.hp = max(0, settlement.hp - damage_dragon_attacks(damage, settlement.dfn))
    _append_unique_coord(dragon.marked_ability_tiles, "Absolute Zero no heal", target)
    return AbilityUseResult(
        True, f"Absolute Zero Breath hit for {damage} attack power.", "Absolute Zero Breath"
    )


def _tremors(dragon: Dragon, world: GameMap, target: OffsetCoord) -> AbilityUseResult:
    invalid = _target_in_range(dragon, target, world)
    if invalid is not None:
        return AbilityUseResult(False, invalid.reason, "Tremors")
    _append_unique_coord(dragon.marked_ability_tiles, "Tremors", target)
    return AbilityUseResult(True, "Tremors marked the tile as loose ground.", "Tremors")


def _terrascape(
    dragon: Dragon,
    world: GameMap,
    citadel_coord: OffsetCoord,
    settlements_by_coord: Mapping[OffsetCoord, Settlement],
    target: OffsetCoord,
) -> AbilityUseResult:
    invalid = _target_in_range(dragon, target, world)
    if invalid is not None:
        return AbilityUseResult(False, invalid.reason, "Terrascape")
    tile = world.get(target)
    if tile is None or tile.terrain in {Terrain.CITADEL, Terrain.SETTLEMENT, Terrain.MOUNTAIN}:
        return AbilityUseResult(
            False,
            "Terrascape needs a non-settlement, non-citadel, non-mountain tile.",
            "Terrascape",
        )
    if distance(offset_to_axial(target), offset_to_axial(citadel_coord)) <= 1:
        return AbilityUseResult(
            False, "Terrascape must leave space around the citadel.", "Terrascape"
        )
    for settlement in settlements_by_coord.values():
        if distance(offset_to_axial(target), offset_to_axial(settlement.position)) <= 1:
            return AbilityUseResult(
                False, "Terrascape must leave space around settlements.", "Terrascape"
            )
    _append_unique_coord(dragon.marked_ability_tiles, "Terrascape mountains", target)
    return AbilityUseResult(
        True, "Terrascape raised a simulated mountain marker (map mutation TODO).", "Terrascape"
    )


def _append_unique_coord(
    store: dict[str, tuple[OffsetCoord, ...]], key: str, coord: OffsetCoord
) -> None:
    coords = store.get(key, ())
    if coord not in coords:
        store[key] = (*coords, coord)


def apply_time_spent(dragon: Dragon, hours: float) -> None:
    """Apply passive healing and tick active effect durations for spent time."""

    spent = max(0.0, float(hours))
    if spent <= 0.0:
        return
    timestop = active_effect_hours_remaining(dragon, "Timestop")
    if timestop > 0.0:
        refund = min(spent, timestop)
        dragon.hours_remaining = min(HOURS_PER_DRAGON_DAY, dragon.hours_remaining + refund)
        spent -= refund
        _set_or_clear_effect(dragon, "Timestop", timestop - refund)
    for name, remaining in list(dragon.active_ability_hours.items()):
        if name == "Timestop":
            continue
        _set_or_clear_effect(dragon, name, remaining - spent)
    if passive_active(dragon, "Healing Crystal"):
        multiplier = (
            2.0 if active_effect_hours_remaining(dragon, "Draconic Resurgence") > 0 else 1.0
        )
        healing = int(
            round(dragon.max_hp * HEALING_CRYSTAL_PERCENT_PER_HOUR / 100.0 * spent * multiplier)
        )
        if healing > 0:
            dragon.hp = min(dragon.max_hp, dragon.hp + healing)


def _set_or_clear_effect(dragon: Dragon, name: str, hours: float) -> None:
    if hours <= 1e-9:
        dragon.active_ability_hours.pop(name, None)
    else:
        dragon.active_ability_hours[name] = hours


def on_settlement_combat_started(dragon: Dragon) -> None:
    if passive_active(dragon, "Flame buffer"):
        dragon.passive_stacks.setdefault("Flame buffer", 0)


def on_combat_ended(dragon: Dragon) -> None:
    del dragon


def effective_attack(dragon: Dragon, *, world: GameMap | None = None) -> int:
    attack = float(dragon.atk)
    if active_effect_hours_remaining(dragon, "Fiery Malice") > 0:
        attack *= FIERY_MALICE_MULTIPLIER
    if (
        world is not None
        and passive_active(dragon, "Mountain's Boon")
        and _mountain_nearby(dragon, world)
    ):
        attack *= MOUNTAINS_BOON_ATTACK_MULTIPLIER
    return max(1, int(round(attack)))


def effective_defence(dragon: Dragon) -> int:
    defence = float(dragon.dfn)
    if active_effect_hours_remaining(dragon, "Defend the Citadel") > 0:
        defence *= FIERY_MALICE_MULTIPLIER
    return max(0, int(round(defence)))


def effective_flight_range(dragon: Dragon) -> int:
    value = float(dragon.flight_range_hexes)
    if active_effect_hours_remaining(dragon, "Fiery Malice") > 0:
        value *= FIERY_MALICE_MULTIPLIER
    return max(0, int(math.floor(value)))


def effective_speed_hexes_per_hour(dragon: Dragon, *, world: GameMap | None = None) -> float:
    speed = float(dragon.speed_hexes_per_hour)
    if active_effect_hours_remaining(dragon, "Fiery Malice") > 0:
        speed *= FIERY_MALICE_MULTIPLIER
    if (
        world is not None
        and passive_active(dragon, "Mountain's Boon")
        and _mountain_nearby(dragon, world)
    ):
        speed += MOUNTAINS_BOON_SPEED_BONUS
    return max(0.001, speed)


def _mountain_nearby(dragon: Dragon, world: GameMap) -> bool:
    mountain_markers = dragon.marked_ability_tiles.get("Terrascape mountains", ())
    for tile in world:
        if tile.terrain is Terrain.MOUNTAIN or tile.coord in mountain_markers:
            if (
                distance(offset_to_axial(dragon.position), offset_to_axial(tile.coord))
                <= MOUNTAINS_BOON_RANGE_HEXES
            ):
                return True
    return False


def outgoing_settlement_damage_multiplier(dragon: Dragon) -> float:
    if not passive_active(dragon, "Flame buffer"):
        return 1.0
    stacks = min(FLAME_BUFFER_MAX_STACKS, dragon.passive_stacks.get("Flame buffer", 0) + 1)
    dragon.passive_stacks["Flame buffer"] = stacks
    return 1.0 + (stacks * FLAME_BUFFER_STACK_PERCENT / 100.0)


def thorns_damage(dragon: Dragon, incoming_damage: int) -> int:
    if incoming_damage <= 0 or not passive_active(dragon, "Spiked Scales"):
        return 0
    return max(1, dragon.dfn * SPIKED_SCALES_DEFENCE_PERCENT // 100)


def mitigated_damage_taken(dragon: Dragon, incoming_damage: int) -> int:
    if incoming_damage <= 0 or not passive_active(dragon, "Foresight"):
        return incoming_damage
    undo = int(round(incoming_damage * FORESIGHT_DAMAGE_UNDO_PERCENT / 100.0))
    return max(0, incoming_damage - undo)


def enemy_can_retaliate(dragon: Dragon) -> bool:
    return active_effect_hours_remaining(dragon, "Timestop") <= 0


def vivify_attack_bonus(dragon: Dragon) -> int:
    if active_effect_hours_remaining(dragon, VIVIFY_SACRIFICE_EFFECT_NAME) <= 0:
        return 0
    sacrifice = dragon.hp * VIVIFY_ATTACK_SACRIFICE_PERCENT // 100
    if sacrifice <= 0:
        return 0
    dragon.hp = max(1, dragon.hp - sacrifice)
    return sacrifice


def apply_ice_talons_to_settlement(dragon: Dragon, settlement: Settlement) -> None:
    if passive_active(dragon, "Ice Talons"):
        settlement.atk = max(
            0, int(math.floor(settlement.atk * (1.0 - ICE_TALONS_ATTACK_REDUCTION_PERCENT / 100.0)))
        )


def settlement_defence_for_round(dragon: Dragon, settlement: Settlement) -> int:
    if settlement.position in dragon.marked_ability_tiles.get("Tremors", ()):
        return max(0, int(math.floor(settlement.dfn * TREMORS_DEFENCE_MULTIPLIER)))
    return settlement.dfn


def ability_status_label(dragon: Dragon, ability_name: str) -> str:
    cooldown = cooldown_remaining(dragon, ability_name)
    charges = extra_charges_remaining(dragon, ability_name)
    effect_name = VIVIFY_SACRIFICE_EFFECT_NAME if ability_name == "Vivify" else ability_name
    hours = active_effect_hours_remaining(dragon, effect_name)
    parts: list[str] = []
    if cooldown > 0:
        parts.append(f"CD {cooldown} turn(s)")
    if charges > 0:
        parts.append(f"+{charges} charge(s)")
    if hours > 0:
        label = "sacrifice" if ability_name == "Vivify" else "active"
        parts.append(f"{hours:.1f}h {label}")
    return " | ".join(parts) if parts else "Ready"


def ability_button_enabled(dragon: Dragon, ability_name: str) -> bool:
    return cooldown_remaining(dragon, ability_name) <= 0 or (
        ability_name == "Plasma Lance" and extra_charges_remaining(dragon, ability_name) > 0
    )


def ability_ui_detail_lines(
    dragon: Dragon,
    spec: DragonAbilitySpec,
    *,
    world: GameMap | None,
) -> list[str]:
    """Short read-only factual lines for the ability panel."""

    if spec.name == "Flame buffer":
        stacks = min(FLAME_BUFFER_MAX_STACKS, dragon.passive_stacks.get("Flame buffer", 0))
        percent = stacks * FLAME_BUFFER_STACK_PERCENT
        return [
            f"Stacks today: {stacks}/{FLAME_BUFFER_MAX_STACKS}",
            f"Current damage bonus: +{percent}%",
            f"Adds +{FLAME_BUFFER_STACK_PERCENT}% per settlement combat round.",
        ]
    if spec.name == "Spiked Scales":
        damage = max(1, dragon.dfn * SPIKED_SCALES_DEFENCE_PERCENT // 100)
        return [f"Thorns per damaging hit: {damage}", f"{SPIKED_SCALES_DEFENCE_PERCENT}% of DFN."]
    if spec.name == "Healing Crystal":
        multiplier = (
            2.0 if active_effect_hours_remaining(dragon, "Draconic Resurgence") > 0 else 1.0
        )
        healing = int(round(dragon.max_hp * HEALING_CRYSTAL_PERCENT_PER_HOUR / 100.0 * multiplier))
        return [
            f"Heals {healing} HP per hour spent.",
            f"Base rate: {HEALING_CRYSTAL_PERCENT_PER_HOUR:g}% max HP/hour.",
        ]
    if spec.name == "Foresight":
        return [f"Mitigates {FORESIGHT_DAMAGE_UNDO_PERCENT}% damage after each combat round."]
    if spec.name == "Ice Talons":
        return [f"Settlement attack reduced {ICE_TALONS_ATTACK_REDUCTION_PERCENT}% per hit."]
    if spec.name == "Mountain's Boon":
        active = world is not None and _mountain_nearby(dragon, world)
        attack_bonus = int(round((MOUNTAINS_BOON_ATTACK_MULTIPLIER - 1.0) * 100))
        return [
            f"Mountain within {MOUNTAINS_BOON_RANGE_HEXES} hexes: {'yes' if active else 'no'}.",
            f"If active: +{attack_bonus}% ATK, +{MOUNTAINS_BOON_SPEED_BONUS:g} speed.",
        ]
    if spec.name == "Plasma Lance":
        return [
            f"Preview damage: {effective_attack(dragon, world=world)}",
            "Ignores target defence.",
        ]
    if spec.name == "Fiery Malice":
        percent = int(round((FIERY_MALICE_MULTIPLIER - 1.0) * 100))
        hours = active_effect_hours_remaining(dragon, spec.name)
        return [
            f"+{percent}% ATK, range, speed for 3h.",
            f"Active remaining: {hours:.1f}h.",
            f"Plasma Lance charges today: {extra_charges_remaining(dragon, 'Plasma Lance')}.",
        ]
    if spec.name == "Ancient's Roar":
        return [
            f"Range: {effective_flight_range(dragon)} hexes.",
            "Settlements in range: -30% attack.",
            "Army move slow hook TODO.",
        ]
    if spec.name == "Defend the Citadel":
        percent = int(round((FIERY_MALICE_MULTIPLIER - 1.0) * 100))
        return [
            f"Return time is 1/{int(DEFEND_THE_CITADEL_TRAVEL_DIVISOR)} normal.",
            f"+{percent}% DFN for 3h.",
        ]
    if spec.name == "Draconic Resurgence":
        heal = max(1, dragon.max_hp * 25 // 100)
        return [f"Usable below 50% HP; heals {heal} HP.", "Doubles Healing Crystal for 5h."]
    if spec.name == "Vivify":
        active_bonus = int(dragon.passive_stacks.get("Vivify max hp bonus", 0))
        base_max_hp = max(1, dragon.max_hp - active_bonus)
        next_bonus = max(1, base_max_hp * VIVIFY_HP_BONUS_PERCENT // 100)
        sacrifice = dragon.hp * VIVIFY_ATTACK_SACRIFICE_PERCENT // 100
        sacrifice_hours = active_effect_hours_remaining(dragon, VIVIFY_SACRIFICE_EFFECT_NAME)
        return [
            f"+{active_bonus or next_bonus} max HP until next day.",
            f"Sacrifice window: {sacrifice_hours:.1f}h / {VIVIFY_SACRIFICE_DURATION_HOURS:g}h.",
            f"Attack sacrifice preview: {sacrifice} HP.",
        ]
    if spec.name == "Timestop":
        return ["Next 1h of actions costs no time.", "Enemies cannot retaliate while active."]
    if spec.name == "Chrono-conic pulse":
        return ["Map-wide slow for this turn.", "Army/growth/eco hooks TODO."]
    if spec.name == "Tempest Strike":
        return [
            f"First hit attack power: {effective_attack(dragon, world=world)}.",
            "Chains at 50% power.",
        ]
    if spec.name == "Absolute Zero Breath":
        damage = max(1, int(round(effective_attack(dragon, world=world) * 1.5)))
        return [f"Attack power: {damage}.", "No-heal marker hook TODO."]
    if spec.name == "Tremors":
        penalty = int(round((1.0 - TREMORS_DEFENCE_MULTIPLIER) * 100))
        return [f"Marks one tile: -{penalty}% settlement DFN in combat."]
    if spec.name == "Terrascape":
        return ["Raises simulated mountain marker.", "Permanent map mutation TODO."]
    return [spec.description]


__all__ = [
    "AbilityUseResult",
    "ability_button_enabled",
    "ability_requires_target",
    "ability_status_label",
    "ability_ui_detail_lines",
    "ability_spec_by_name",
    "apply_ice_talons_to_settlement",
    "apply_time_spent",
    "begin_new_turn",
    "cooldown_remaining",
    "cooldown_turns_from_text",
    "effective_attack",
    "effective_defence",
    "effective_flight_range",
    "effective_speed_hexes_per_hour",
    "enemy_can_retaliate",
    "mitigated_damage_taken",
    "on_combat_ended",
    "on_settlement_combat_started",
    "outgoing_settlement_damage_multiplier",
    "passive_active",
    "settlement_defence_for_round",
    "synchronize_unlocked_abilities",
    "thorns_damage",
    "try_use_ability",
    "unlocked_ability_specs",
    "VIVIFY_SACRIFICE_EFFECT_NAME",
    "VIVIFY_SACRIFICE_DURATION_HOURS",
    "vivify_attack_bonus",
]
