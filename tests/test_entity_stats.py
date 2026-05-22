"""Tests for stat modifier bags and fold order."""

from __future__ import annotations

from dragonflight.dragon_playables import Greengon, Redgon
from dragonflight.entity_stats import (
    ModifierExpiry,
    ModifierKind,
    StatKey,
    StatModifier,
    StatModifierBag,
    add_modifier,
    clear_day_end,
    effective_statline,
    read_base,
    read_effective,
    tick_hours,
)
from dragonflight.hex_coord import OffsetCoord


def test_fold_order_flat_add_then_percent_mult() -> None:
    dragon = Redgon.new_at(OffsetCoord(0, 0))
    dragon.atk = 100
    bag = StatModifierBag()
    add_modifier(
        bag,
        StatModifier(
            stat=StatKey.ATK,
            kind=ModifierKind.FLAT_ADD,
            value=20.0,
            expiry=ModifierExpiry.DAY_END,
            source="test",
        ),
    )
    add_modifier(
        bag,
        StatModifier(
            stat=StatKey.ATK,
            kind=ModifierKind.PERCENT_MULT,
            value=1.5,
            expiry=ModifierExpiry.DAY_END,
            source="test",
        ),
    )
    assert read_effective(dragon, bag, StatKey.ATK) == 180


def test_tick_hours_removes_expired_hour_modifiers() -> None:
    bag = StatModifierBag()
    add_modifier(
        bag,
        StatModifier(
            stat=StatKey.DFN,
            kind=ModifierKind.PERCENT_MULT,
            value=1.5,
            expiry=ModifierExpiry.HOURS,
            hours_remaining=3.0,
            source="buff",
        ),
    )
    tick_hours(bag, 2.0)
    assert len(bag.modifiers) == 1
    assert bag.modifiers[0].hours_remaining == 1.0
    tick_hours(bag, 1.0)
    assert bag.modifiers == []


def test_clear_day_end_drops_only_day_scoped_modifiers() -> None:
    bag = StatModifierBag()
    add_modifier(
        bag,
        StatModifier(
            stat=StatKey.MAX_HP,
            kind=ModifierKind.FLAT_ADD,
            value=50.0,
            expiry=ModifierExpiry.DAY_END,
            source="vivify",
        ),
    )
    add_modifier(
        bag,
        StatModifier(
            stat=StatKey.DFN,
            kind=ModifierKind.PERCENT_MULT,
            value=1.5,
            expiry=ModifierExpiry.HOURS,
            hours_remaining=2.0,
            source="defend",
        ),
    )
    clear_day_end(bag)
    assert len(bag.modifiers) == 1
    assert bag.modifiers[0].source == "defend"


def test_vivify_does_not_mutate_base_max_hp() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Greengon.new_at(coord)
    base = int(read_base(dragon, StatKey.MAX_HP))
    bag = dragon.stat_modifiers
    add_modifier(
        bag,
        StatModifier(
            stat=StatKey.MAX_HP,
            kind=ModifierKind.FLAT_ADD,
            value=float(base * 20 // 100),
            expiry=ModifierExpiry.DAY_END,
            source="Vivify max hp",
        ),
    )
    assert dragon.max_hp == base
    line = effective_statline(dragon, bag)
    assert line.max_hp == base + base * 20 // 100
