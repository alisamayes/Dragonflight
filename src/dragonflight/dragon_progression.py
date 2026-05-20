"""Dragon stat upgrades (spec num7) — pure pricing and draft application.

Citadel UI opens the upgrade overlay; progression logic is dragon-scoped, not citadel-named.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from .dragon import Dragon
from .dragon_defaults import (
    DRAGON_STAT_UPGRADE_ATK_DELTA,
    DRAGON_STAT_UPGRADE_COST_BASE,
    DRAGON_STAT_UPGRADE_COST_COUNT_COEFF,
    DRAGON_STAT_UPGRADE_COST_LEVEL_COEFF,
    DRAGON_STAT_UPGRADE_DFN_DELTA,
    DRAGON_STAT_UPGRADE_FLIGHT_RANGE_HEXES_DELTA,
    DRAGON_STAT_UPGRADE_HP_DELTA,
    DRAGON_STAT_UPGRADE_SPEED_HEXES_PER_HOUR_DELTA,
)


class DragonUpgradeStat(Enum):
    """Column order for upgrade UI: HP, ATK, DFN, flight range, speed."""

    HP = "hp"
    ATK = "atk"
    DFN = "dfn"
    FLIGHT_RANGE = "flight_range"
    SPEED = "speed"


DRAGON_UPGRADE_STAT_COLUMN_ORDER: tuple[DragonUpgradeStat, ...] = (
    DragonUpgradeStat.HP,
    DragonUpgradeStat.ATK,
    DragonUpgradeStat.DFN,
    DragonUpgradeStat.FLIGHT_RANGE,
    DragonUpgradeStat.SPEED,
)


@dataclass(frozen=True, slots=True)
class DragonUpgradeBaseline:
    """Snapshot of dragon economy/stats at the moment a draft session begins."""

    level: int
    gold: int
    hp: int
    max_hp: int
    atk: int
    dfn: int
    flight_range_hexes: int
    speed_hexes_per_hour: float
    hp_upgrades: int
    atk_upgrades: int
    dfn_upgrades: int
    flight_range_upgrades: int
    speed_upgrades: int


def dragon_upgrade_baseline_from_dragon(dragon: Dragon) -> DragonUpgradeBaseline:
    return DragonUpgradeBaseline(
        level=int(dragon.level),
        gold=int(dragon.gold),
        hp=int(dragon.hp),
        max_hp=int(dragon.max_hp),
        atk=int(dragon.atk),
        dfn=int(dragon.dfn),
        flight_range_hexes=int(dragon.flight_range_hexes),
        speed_hexes_per_hour=float(dragon.speed_hexes_per_hour),
        hp_upgrades=int(dragon.hp_upgrades),
        atk_upgrades=int(dragon.atk_upgrades),
        dfn_upgrades=int(dragon.dfn_upgrades),
        flight_range_upgrades=int(dragon.flight_range_upgrades),
        speed_upgrades=int(dragon.speed_upgrades),
    )


def dragon_stat_upgrade_gold_cost(level_at_purchase: int, n_stat_inclusive: int) -> int:
    """Gold for one purchase: ``200 + level*20 + n*20`` (spec num7)."""
    return (
        DRAGON_STAT_UPGRADE_COST_BASE
        + int(level_at_purchase) * DRAGON_STAT_UPGRADE_COST_LEVEL_COEFF
        + int(n_stat_inclusive) * DRAGON_STAT_UPGRADE_COST_COUNT_COEFF
    )


def dragon_stat_upgrade_lifetime_count(
    baseline: DragonUpgradeBaseline,
    stat: DragonUpgradeStat,
) -> int:
    if stat is DragonUpgradeStat.HP:
        return baseline.hp_upgrades
    if stat is DragonUpgradeStat.ATK:
        return baseline.atk_upgrades
    if stat is DragonUpgradeStat.DFN:
        return baseline.dfn_upgrades
    if stat is DragonUpgradeStat.FLIGHT_RANGE:
        return baseline.flight_range_upgrades
    return baseline.speed_upgrades


def marginal_dragon_stat_upgrade_cost(
    baseline: DragonUpgradeBaseline,
    draft: Sequence[DragonUpgradeStat],
    stat: DragonUpgradeStat,
) -> int:
    """Gold for appending ``stat`` to ``draft`` (sequential levels, per-stat *n*)."""
    draft_list = list(draft)
    purchase_index = len(draft_list)
    level_at = baseline.level + purchase_index
    in_draft = sum(1 for s in draft_list if s is stat)
    n = dragon_stat_upgrade_lifetime_count(baseline, stat) + in_draft + 1
    return dragon_stat_upgrade_gold_cost(level_at, n)


def total_dragon_upgrade_draft_cost(
    baseline: DragonUpgradeBaseline,
    draft: Sequence[DragonUpgradeStat],
) -> int:
    total = 0
    partial: list[DragonUpgradeStat] = []
    for stat in draft:
        total += marginal_dragon_stat_upgrade_cost(baseline, partial, stat)
        partial.append(stat)
    return total


def _apply_stat_delta_to_totals(
    hp: int,
    max_hp: int,
    atk: int,
    dfn: int,
    flight_range_hexes: int,
    speed_hexes_per_hour: float,
    stat: DragonUpgradeStat,
) -> tuple[int, int, int, int, int, float]:
    if stat is DragonUpgradeStat.HP:
        max_hp2 = max_hp + DRAGON_STAT_UPGRADE_HP_DELTA
        hp2 = min(max_hp2, hp + DRAGON_STAT_UPGRADE_HP_DELTA)
        return hp2, max_hp2, atk, dfn, flight_range_hexes, speed_hexes_per_hour
    if stat is DragonUpgradeStat.ATK:
        next_atk = atk + DRAGON_STAT_UPGRADE_ATK_DELTA
        return hp, max_hp, next_atk, dfn, flight_range_hexes, speed_hexes_per_hour
    if stat is DragonUpgradeStat.DFN:
        next_dfn = dfn + DRAGON_STAT_UPGRADE_DFN_DELTA
        return hp, max_hp, atk, next_dfn, flight_range_hexes, speed_hexes_per_hour
    if stat is DragonUpgradeStat.FLIGHT_RANGE:
        return (
            hp,
            max_hp,
            atk,
            dfn,
            flight_range_hexes + DRAGON_STAT_UPGRADE_FLIGHT_RANGE_HEXES_DELTA,
            speed_hexes_per_hour,
        )
    return (
        hp,
        max_hp,
        atk,
        dfn,
        flight_range_hexes,
        speed_hexes_per_hour + DRAGON_STAT_UPGRADE_SPEED_HEXES_PER_HOUR_DELTA,
    )


def preview_dragon_stats_after_draft(
    baseline: DragonUpgradeBaseline,
    draft: Sequence[DragonUpgradeStat],
) -> tuple[int, int, int, int, int, float]:
    hp, max_hp = baseline.hp, baseline.max_hp
    atk, dfn = baseline.atk, baseline.dfn
    fr = baseline.flight_range_hexes
    spd = baseline.speed_hexes_per_hour
    for stat in draft:
        hp, max_hp, atk, dfn, fr, spd = _apply_stat_delta_to_totals(
            hp, max_hp, atk, dfn, fr, spd, stat
        )
    return hp, max_hp, atk, dfn, fr, spd


def dragon_stat_pill_strings_from_totals(
    hp: int,
    max_hp: int,
    atk: int,
    dfn: int,
    flight_range_hexes: int,
    speed_hexes_per_hour: float,
) -> tuple[str, str, str, str, str]:
    return (
        f"{hp}/{max_hp}",
        str(atk),
        str(dfn),
        str(flight_range_hexes),
        f"{speed_hexes_per_hour:.1f}",
    )


def apply_one_dragon_stat_upgrade(dragon: Dragon, stat: DragonUpgradeStat) -> None:
    """Apply one stat tier and bump that stat's lifetime counter (no gold or level)."""
    if stat is DragonUpgradeStat.HP:
        dragon.max_hp += DRAGON_STAT_UPGRADE_HP_DELTA
        dragon.hp = min(dragon.max_hp, dragon.hp + DRAGON_STAT_UPGRADE_HP_DELTA)
        dragon.hp_upgrades += 1
    elif stat is DragonUpgradeStat.ATK:
        dragon.atk += DRAGON_STAT_UPGRADE_ATK_DELTA
        dragon.atk_upgrades += 1
    elif stat is DragonUpgradeStat.DFN:
        dragon.dfn += DRAGON_STAT_UPGRADE_DFN_DELTA
        dragon.dfn_upgrades += 1
    elif stat is DragonUpgradeStat.FLIGHT_RANGE:
        dragon.flight_range_hexes += DRAGON_STAT_UPGRADE_FLIGHT_RANGE_HEXES_DELTA
        dragon.flight_range_upgrades += 1
    else:
        dragon.speed_hexes_per_hour += DRAGON_STAT_UPGRADE_SPEED_HEXES_PER_HOUR_DELTA
        dragon.speed_upgrades += 1


def apply_dragon_upgrade_draft(dragon: Dragon, purchases: Sequence[DragonUpgradeStat]) -> None:
    """Spend gold for ``purchases``, apply stat deltas, then set ``level += len(purchases)``.

    Costs use :attr:`Dragon.level` and per-stat counts before applying (draft baseline).
    """
    baseline = dragon_upgrade_baseline_from_dragon(dragon)
    total = total_dragon_upgrade_draft_cost(baseline, purchases)
    if total > baseline.gold:
        msg = "insufficient gold for dragon upgrade draft"
        raise ValueError(msg)
    dragon.gold = baseline.gold - total
    for stat in purchases:
        apply_one_dragon_stat_upgrade(dragon, stat)
    dragon.level = baseline.level + len(purchases)


def parse_dragon_upgrade_stat_name(stat_name: str) -> DragonUpgradeStat | None:
    key = stat_name.strip().lower()
    for member in DragonUpgradeStat:
        if member.value == key:
            return member
    return None
