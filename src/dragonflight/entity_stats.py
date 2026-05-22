"""Entity stat lines and modifier bags (fold order: FLAT_ADD, PERCENT_MULT, clamps).

Base values live on entities (e.g. :class:`~dragonflight.dragon.Dragon` fields).
Temporary and day-scoped changes are :class:`StatModifier` entries in a
:class:`StatModifierBag`, not in-place mutations of base stats.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .army import Army
    from .dragon import Dragon
    from .settlement import Settlement


class StatKey(Enum):
    """Combat and mobility stats for dragons, settlements, and armies."""

    MAX_HP = "max_hp"
    ATK = "atk"
    DFN = "dfn"
    FLIGHT_RANGE = "flight_range"
    SPEED = "speed"


class ModifierKind(Enum):
    """How a modifier combines with the running total for one stat."""

    FLAT_ADD = "flat_add"
    PERCENT_MULT = "percent_mult"


class ModifierScope(Enum):
    """Which stats a modifier may target (Phase 1 uses single-stat entries)."""

    SINGLE = "single"


class ModifierExpiry(Enum):
    """When a modifier is removed from the bag."""

    HOURS = "hours"
    DAY_END = "day_end"


@dataclass(frozen=True, slots=True)
class StatModifier:
    """One applied change to a single stat key."""

    stat: StatKey
    kind: ModifierKind
    value: float
    expiry: ModifierExpiry
    scope: ModifierScope = ModifierScope.SINGLE
    hours_remaining: float = 0.0
    source: str = ""


@dataclass
class StatLine:
    """Resolved values for all dragon stats (base or effective)."""

    max_hp: int
    atk: int
    dfn: int
    flight_range: int
    speed: float


@dataclass
class StatModifierBag:
    """Mutable collection of stat modifiers for one entity."""

    modifiers: list[StatModifier] = field(default_factory=list)


def base_statline_from_dragon(dragon: Dragon) -> StatLine:
    """Read persistent base stats from the dragon entity fields."""

    return StatLine(
        max_hp=int(dragon.max_hp),
        atk=int(dragon.atk),
        dfn=int(dragon.dfn),
        flight_range=int(dragon.flight_range_hexes),
        speed=float(dragon.speed_hexes_per_hour),
    )


def base_statline_from_settlement(settlement: Settlement) -> StatLine:
    """Read persistent base combat stats from settlement fields."""

    return StatLine(
        max_hp=int(settlement.max_hp),
        atk=int(settlement.atk),
        dfn=int(settlement.dfn),
        flight_range=0,
        speed=0.0,
    )


def base_statline_from_army(army: Army) -> StatLine:
    """Read persistent base combat stats from army fields."""

    return StatLine(
        max_hp=int(army.max_hp),
        atk=int(army.atk),
        dfn=int(army.dfn),
        flight_range=0,
        speed=0.0,
    )


def _read_from_line(line: StatLine, key: StatKey) -> float:
    if key is StatKey.MAX_HP:
        return float(line.max_hp)
    if key is StatKey.ATK:
        return float(line.atk)
    if key is StatKey.DFN:
        return float(line.dfn)
    if key is StatKey.FLIGHT_RANGE:
        return float(line.flight_range)
    return line.speed


def _apply_clamp(key: StatKey, value: float) -> float:
    if key is StatKey.MAX_HP:
        return float(max(1, int(round(value))))
    if key is StatKey.ATK:
        return float(max(1, int(round(value))))
    if key is StatKey.DFN:
        return float(max(0, int(round(value))))
    if key is StatKey.FLIGHT_RANGE:
        return float(max(0, int(math.floor(value))))
    return max(0.001, value)


def _fold_stat(base: float, modifiers: list[StatModifier], key: StatKey) -> float:
    """Apply FLAT_ADD sums, then PERCENT_MULT products, then key clamps."""

    relevant = [m for m in modifiers if m.stat is key]
    total = base
    for mod in relevant:
        if mod.kind is ModifierKind.FLAT_ADD:
            total += mod.value
    for mod in relevant:
        if mod.kind is ModifierKind.PERCENT_MULT:
            total *= mod.value
    return _apply_clamp(key, total)


def effective_statline_from_base(
    base: StatLine,
    bag: StatModifierBag,
    *,
    extra_modifiers: tuple[StatModifier, ...] = (),
) -> StatLine:
    """Fold a base stat line with bag modifiers and optional ephemeral extras."""

    combined = [*bag.modifiers, *extra_modifiers]
    return StatLine(
        max_hp=int(_fold_stat(float(base.max_hp), combined, StatKey.MAX_HP)),
        atk=int(_fold_stat(float(base.atk), combined, StatKey.ATK)),
        dfn=int(_fold_stat(float(base.dfn), combined, StatKey.DFN)),
        flight_range=int(_fold_stat(float(base.flight_range), combined, StatKey.FLIGHT_RANGE)),
        speed=_fold_stat(base.speed, combined, StatKey.SPEED),
    )


def effective_statline(
    dragon: Dragon,
    bag: StatModifierBag,
    *,
    extra_modifiers: tuple[StatModifier, ...] = (),
) -> StatLine:
    """Fold dragon base stats with bag modifiers and optional ephemeral extras."""

    return effective_statline_from_base(
        base_statline_from_dragon(dragon),
        bag,
        extra_modifiers=extra_modifiers,
    )


def read_base_from_line(base: StatLine, key: StatKey) -> int | float:
    return _read_from_line(base, key)


def read_base(dragon: Dragon, key: StatKey) -> int | float:
    """Single base stat from dragon entity fields."""

    return read_base_from_line(base_statline_from_dragon(dragon), key)


def read_effective_from_base(
    base: StatLine,
    bag: StatModifierBag,
    key: StatKey,
    *,
    extra_modifiers: tuple[StatModifier, ...] = (),
) -> int | float:
    """Single effective stat after modifier fold for any combatant base line."""

    return _read_from_line(
        effective_statline_from_base(base, bag, extra_modifiers=extra_modifiers),
        key,
    )


def read_effective(
    dragon: Dragon,
    bag: StatModifierBag,
    key: StatKey,
    *,
    extra_modifiers: tuple[StatModifier, ...] = (),
) -> int | float:
    """Single effective stat after modifier fold."""

    return read_effective_from_base(
        base_statline_from_dragon(dragon),
        bag,
        key,
        extra_modifiers=extra_modifiers,
    )


def tick_modifier_bags(bags: Iterable[StatModifierBag], hours: float) -> None:
    """Decrement hour-scoped modifiers on every bag in ``bags``."""

    for bag in bags:
        tick_hours(bag, hours)


def add_modifier(bag: StatModifierBag, modifier: StatModifier) -> None:
    """Append a modifier (callers replace same-source buffs if needed)."""

    bag.modifiers.append(modifier)


def remove_modifiers_by_source(bag: StatModifierBag, source: str) -> None:
    """Drop all modifiers tagged with ``source`` (before re-applying a refreshed buff)."""

    bag.modifiers = [m for m in bag.modifiers if m.source != source]


def tick_hours(bag: StatModifierBag, hours: float) -> None:
    """Decrement hour-scoped modifiers; remove entries that expire."""

    spent = max(0.0, float(hours))
    if spent <= 0.0:
        return
    kept: list[StatModifier] = []
    for mod in bag.modifiers:
        if mod.expiry is not ModifierExpiry.HOURS:
            kept.append(mod)
            continue
        remaining = mod.hours_remaining - spent
        if remaining > 1e-9:
            kept.append(
                StatModifier(
                    stat=mod.stat,
                    kind=mod.kind,
                    value=mod.value,
                    expiry=mod.expiry,
                    scope=mod.scope,
                    hours_remaining=remaining,
                    source=mod.source,
                )
            )
    bag.modifiers = kept


def clear_day_end(bag: StatModifierBag) -> None:
    """Remove modifiers that last until the citadel day boundary."""

    bag.modifiers = [m for m in bag.modifiers if m.expiry is not ModifierExpiry.DAY_END]


def hours_remaining_for_source(bag: StatModifierBag, source: str) -> float:
    """Max remaining hours among hour-expiry modifiers with matching ``source``."""

    hours = [
        m.hours_remaining
        for m in bag.modifiers
        if m.expiry is ModifierExpiry.HOURS and m.source == source
    ]
    return max(hours, default=0.0)


def flat_add_total_for_source(bag: StatModifierBag, source: str, key: StatKey) -> int:
    """Sum FLAT_ADD contributions from one source (e.g. Vivify max HP bonus)."""

    total = 0.0
    for mod in bag.modifiers:
        if (
            mod.source == source
            and mod.stat is key
            and mod.kind is ModifierKind.FLAT_ADD
            and mod.expiry is ModifierExpiry.DAY_END
        ):
            total += mod.value
    return int(total)


__all__ = [
    "ModifierExpiry",
    "ModifierKind",
    "ModifierScope",
    "StatKey",
    "StatLine",
    "StatModifier",
    "StatModifierBag",
    "add_modifier",
    "base_statline_from_army",
    "base_statline_from_dragon",
    "base_statline_from_settlement",
    "clear_day_end",
    "effective_statline",
    "effective_statline_from_base",
    "flat_add_total_for_source",
    "hours_remaining_for_source",
    "read_base",
    "read_base_from_line",
    "read_effective",
    "read_effective_from_base",
    "remove_modifiers_by_source",
    "tick_hours",
    "tick_modifier_bags",
]
