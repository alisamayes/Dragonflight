"""Thin combatant view helpers for UI and previews (dragon, settlement, army)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .entity_stats import (
    StatKey,
    StatLine,
    StatModifier,
    StatModifierBag,
    base_statline_from_army,
    base_statline_from_dragon,
    base_statline_from_settlement,
    effective_statline,
    effective_statline_from_base,
    read_base,
    read_effective,
    read_effective_from_base,
)

if TYPE_CHECKING:
    from .army import Army
    from .dragon import Dragon
    from .map_state import GameMap
    from .settlement import Settlement


@dataclass(frozen=True, slots=True)
class CombatantView:
    """Base vs effective stat pairs for HUD panels."""

    base: StatLine
    effective: StatLine

    @property
    def base_max_hp(self) -> int:
        return self.base.max_hp

    @property
    def effective_max_hp(self) -> int:
        return self.effective.max_hp

    @property
    def max_hp_boosted(self) -> bool:
        return self.effective.max_hp > self.base.max_hp

    @property
    def base_atk(self) -> int:
        return self.base.atk

    @property
    def effective_atk(self) -> int:
        return self.effective.atk

    @property
    def base_dfn(self) -> int:
        return self.base.dfn

    @property
    def effective_dfn(self) -> int:
        return self.effective.dfn

    @property
    def atk_debuffed(self) -> bool:
        return self.effective.atk < self.base.atk

    @property
    def dfn_debuffed(self) -> bool:
        return self.effective.dfn < self.base.dfn


def dragon_combatant_view(
    dragon: Dragon,
    *,
    world: GameMap | None = None,
    extra_modifiers: tuple[StatModifier, ...] = (),
) -> CombatantView:
    """Build base/effective lines for the dragon, including ephemeral terrain buffs."""

    from .dragon_abilities import mountain_boon_extra_modifiers

    extras = mountain_boon_extra_modifiers(dragon, world=world)
    if extra_modifiers:
        extras = (*extras, *extra_modifiers)
    bag: StatModifierBag = dragon.stat_modifiers
    return CombatantView(
        base=base_statline_from_dragon(dragon),
        effective=effective_statline(dragon, bag, extra_modifiers=extras),
    )


def settlement_combatant_view(settlement: Settlement) -> CombatantView:
    """Build base/effective combat stats for a settlement."""

    base = base_statline_from_settlement(settlement)
    return CombatantView(
        base=base,
        effective=effective_statline_from_base(base, settlement.stat_modifiers),
    )


def army_combatant_view(army: Army) -> CombatantView:
    """Build base/effective combat stats for an army stack."""

    base = base_statline_from_army(army)
    return CombatantView(
        base=base,
        effective=effective_statline_from_base(base, army.stat_modifiers),
    )


def settlement_effective_atk(settlement: Settlement) -> int:
    return int(
        read_effective_from_base(
            base_statline_from_settlement(settlement),
            settlement.stat_modifiers,
            StatKey.ATK,
        )
    )


def settlement_effective_dfn(settlement: Settlement) -> int:
    return int(
        read_effective_from_base(
            base_statline_from_settlement(settlement),
            settlement.stat_modifiers,
            StatKey.DFN,
        )
    )


def settlement_effective_max_hp(settlement: Settlement) -> int:
    return int(
        read_effective_from_base(
            base_statline_from_settlement(settlement),
            settlement.stat_modifiers,
            StatKey.MAX_HP,
        )
    )


def army_effective_atk(army: Army) -> int:
    return int(
        read_effective_from_base(
            base_statline_from_army(army),
            army.stat_modifiers,
            StatKey.ATK,
        )
    )


def army_effective_dfn(army: Army) -> int:
    return int(
        read_effective_from_base(
            base_statline_from_army(army),
            army.stat_modifiers,
            StatKey.DFN,
        )
    )


def army_effective_max_hp(army: Army) -> int:
    return int(
        read_effective_from_base(
            base_statline_from_army(army),
            army.stat_modifiers,
            StatKey.MAX_HP,
        )
    )


def entity_combatant_view(entity: object) -> CombatantView:
    """Base vs effective combat lines for armies, settlements, or playtest stubs."""

    if isinstance(entity, Army):
        return army_combatant_view(entity)
    if isinstance(entity, Settlement):
        return settlement_combatant_view(entity)
    base = StatLine(
        max_hp=int(getattr(entity, "max_hp", 1)),
        atk=int(getattr(entity, "atk", 0)),
        dfn=int(getattr(entity, "dfn", 0)),
        flight_range=0,
        speed=0.0,
    )
    bag = getattr(entity, "stat_modifiers", None)
    if isinstance(bag, StatModifierBag):
        effective = effective_statline_from_base(base, bag)
    else:
        effective = base
    return CombatantView(base=base, effective=effective)


def entity_effective_atk(entity: object) -> int:
    """Combat ATK for any entity with a modifier bag (base ``atk`` field unchanged)."""

    if isinstance(entity, Army):
        return army_effective_atk(entity)
    if isinstance(entity, Settlement):
        return settlement_effective_atk(entity)
    bag = getattr(entity, "stat_modifiers", None)
    if isinstance(bag, StatModifierBag):
        return int(
            read_effective_from_base(
                StatLine(
                    max_hp=int(getattr(entity, "max_hp", 1)),
                    atk=int(getattr(entity, "atk", 0)),
                    dfn=int(getattr(entity, "dfn", 0)),
                    flight_range=0,
                    speed=0.0,
                ),
                bag,
                StatKey.ATK,
            )
        )
    return int(getattr(entity, "atk", 0))


def entity_effective_dfn(entity: object) -> int:
    """Combat DFN for any entity with a modifier bag."""

    if isinstance(entity, Army):
        return army_effective_dfn(entity)
    if isinstance(entity, Settlement):
        return settlement_effective_dfn(entity)
    bag = getattr(entity, "stat_modifiers", None)
    if isinstance(bag, StatModifierBag):
        return int(
            read_effective_from_base(
                StatLine(
                    max_hp=int(getattr(entity, "max_hp", 1)),
                    atk=int(getattr(entity, "atk", 0)),
                    dfn=int(getattr(entity, "dfn", 0)),
                    flight_range=0,
                    speed=0.0,
                ),
                bag,
                StatKey.DFN,
            )
        )
    return int(getattr(entity, "dfn", 0))


def dragon_base_stat(dragon: Dragon, key: StatKey) -> int | float:
    return read_base(dragon, key)


def dragon_effective_stat(
    dragon: Dragon,
    key: StatKey,
    *,
    world: GameMap | None = None,
) -> int | float:
    from .dragon_abilities import mountain_boon_extra_modifiers

    return read_effective(
        dragon,
        dragon.stat_modifiers,
        key,
        extra_modifiers=mountain_boon_extra_modifiers(dragon, world=world),
    )


__all__ = [
    "CombatantView",
    "army_combatant_view",
    "army_effective_atk",
    "army_effective_dfn",
    "army_effective_max_hp",
    "dragon_base_stat",
    "dragon_combatant_view",
    "dragon_effective_stat",
    "entity_combatant_view",
    "entity_effective_atk",
    "entity_effective_dfn",
    "settlement_combatant_view",
    "settlement_effective_atk",
    "settlement_effective_dfn",
    "settlement_effective_max_hp",
]
