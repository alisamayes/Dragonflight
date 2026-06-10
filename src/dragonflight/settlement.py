"""Settlement rules for growth, dragon combat, and raid defeat (spec numnum6, 8)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal

from .dragon import DamageRoundExchange, Dragon, MoveAttempt
from .entity_stats import StatModifierBag
from .hex_coord import OffsetCoord, distance, offset_to_axial
from .terrain import Terrain

if TYPE_CHECKING:
    from .army import Army
    from .game_tuning import GameTuning
    from .map_state import GameMap


def _resolved_tuning(tuning: GameTuning | None) -> GameTuning:
    from .game_tuning import resolve_tuning

    return resolve_tuning(tuning)


#: When settlement ``hp == 0``, heal this percent of :attr:`Settlement.max_hp` per
#: settlement phase tick.
SETTLEMENT_HEAL_PERCENT_OF_MAX_AT_ZERO: int = 80
#: When ``0 < hp < max_hp``, heal this percent of :attr:`Settlement.max_hp` per tick.
SETTLEMENT_HEAL_PERCENT_OF_MAX_WHEN_DAMAGED: int = 40
SETTLEMENT_GROWTH_ECO_PERCENT: int = 15
SETTLEMENT_GROWTH_STAT_BONUS: int = 3
#: Maximum eco gained per undamaged settlement-phase tick (one in-game day).
SETTLEMENT_GROWTH_ECO_CAP_PER_DAY: int = 200

RAID_ECO_LOSS_DIVISOR: float = 2.0
RAID_STAT_LOSS: int = 6
#: Percent of the defeated settlement's current ``eco`` granted as dragon gold when a raid clears.
RAID_VICTORY_GOLD_PERCENT_OF_ECO: int = 50
RAID_DIRECT_AGGRESSION: int = 300


class SettlementType(Enum):
    """Supported MVP settlement archetypes."""

    VILLAGE = "village"
    CITY = "city"
    FORT = "fort"


@dataclass(frozen=True, slots=True)
class MockArmySpawnEvent:
    """Deprecated playtest type; aggression spawns return :class:`~dragonflight.army.Army` now."""

    position: OffsetCoord
    settlement_type: SettlementType
    eco: int
    atk: int
    dfn: int


@dataclass(frozen=True, slots=True)
class SettlementPhaseOutcome:
    """Structured result from an end-of-settlement-phase tick."""

    action: Literal["healed", "grew", "none"]
    hp_delta: int = 0
    max_hp_delta: int = 0
    eco_delta: int = 0
    atk_delta: int = 0
    dfn_delta: int = 0


@dataclass(frozen=True, slots=True)
class SettlementCombatLoopResult:
    """Outcome from resolving settlement combat until defeat, dragon loss, or retreat."""

    rounds_resolved: int
    retreated: bool
    exchanges: tuple[DamageRoundExchange, ...]
    spawn_events: tuple[Army, ...] = ()
    last_failure: MoveAttempt | None = None


@dataclass(frozen=True, slots=True)
class SettlementRaidResolution:
    """Structured result from auto-resolving a settlement raid (combat + raid-defeat bundle)."""

    combat: SettlementCombatLoopResult
    gold_gained: int


def settlement_hex_distance(a: OffsetCoord, b: OffsetCoord) -> int:
    """Hex distance between two offset settlement coordinates."""

    return distance(offset_to_axial(a), offset_to_axial(b))


def raid_spill_aggression_amount(
    distance: int,
    *,
    dropoff: int,
    base: int = RAID_DIRECT_AGGRESSION,
) -> int:
    """Spill aggression at ``distance`` hexes from a defeated settlement."""

    return max(0, base - distance * dropoff)


def max_spill_distance(
    dropoff: int,
    *,
    base: int = RAID_DIRECT_AGGRESSION,
) -> int:
    """Largest hex distance that still receives spill aggression (amount > 0)."""

    if dropoff < 1:
        raise ValueError(f"dropoff must be >= 1, got {dropoff}")
    return (base - 1) // dropoff


def compute_settlement_eco_growth(
    eco: int,
    starting_eco: int,
    growth_eco_percent: int,
    *,
    cap_per_day: int = SETTLEMENT_GROWTH_ECO_CAP_PER_DAY,
) -> int:
    """Eco gained for one growth tick: formula, rounded up, capped per day."""

    raw = (eco * growth_eco_percent / 100) + (starting_eco * 0.1)
    return min(cap_per_day, max(0, math.ceil(raw)))


@dataclass(slots=True)
class Settlement:
    """Mutable settlement state owned by a higher-level game loop registry.

    ``hp`` is current hit points; ``max_hp`` is the ceiling (HP changes from combat,
    healing, and external rules; undamaged end-of-phase growth does not raise HP).
    """

    hp: int
    max_hp: int
    eco: int
    starting_eco: int
    atk: int
    dfn: int
    aggression: int
    aggression_threshold: int
    position: OffsetCoord
    settlement_type: SettlementType
    stat_modifiers: StatModifierBag = field(default_factory=StatModifierBag)

    @classmethod
    def village(cls, position: OffsetCoord) -> Village:
        """Factory for a village with MVP starting stats."""

        return Village(position)

    @classmethod
    def city(cls, position: OffsetCoord) -> City:
        """Factory for a city with MVP starting stats."""

        return City(position)

    @classmethod
    def fort(cls, position: OffsetCoord) -> Fort:
        """Factory for a fort with MVP starting stats."""

        return Fort(position)

    @property
    def defence(self) -> int:
        """Alias for ``dfn`` to match the design vocabulary."""

        return self.dfn

    @defence.setter
    def defence(self, value: int) -> None:
        self.dfn = value

    def on_settlement_phase_end(
        self,
        tuning: GameTuning | None = None,
        *,
        growth_delayed: bool = False,
        double_growth: bool = False,
        double_healing: bool = False,
        eco_growth_mult: float = 1.0,
    ) -> SettlementPhaseOutcome:
        """Apply one end-of-settlement-phase tick.

        Damaged settlements (``hp < max_hp``) heal only—no eco/stat growth that tick.
        Undamaged settlements (``hp == max_hp``) grow ``eco`` and raise ``atk``/``dfn``;
        ``hp`` and ``max_hp`` are unchanged on growth ticks.
        """

        t = _resolved_tuning(tuning)

        if growth_delayed:
            return SettlementPhaseOutcome(action="none")

        if self.hp < self.max_hp:
            if self.hp == 0:
                healing = self.max_hp * t.settlement_heal_percent_of_max_at_zero // 100
            else:
                healing = self.max_hp * t.settlement_heal_percent_of_max_when_damaged // 100
            if double_healing:
                healing *= 2
            hp_before = self.hp
            self.hp = min(self.max_hp, self.hp + healing)
            return SettlementPhaseOutcome(action="healed", hp_delta=self.hp - hp_before)

        if self.hp == self.max_hp:
            eco_growth = compute_settlement_eco_growth(
                int(self.eco),
                self.starting_eco,
                t.settlement_growth_eco_percent,
            )
            if eco_growth_mult != 1.0:
                eco_growth = max(0, int(math.ceil(eco_growth * eco_growth_mult)))
            stat_bonus = t.settlement_growth_stat_bonus
            if double_growth:
                eco_growth *= 2
                stat_bonus *= 2
            self.eco = int(self.eco) + eco_growth
            self.atk = int(self.atk) + stat_bonus
            self.dfn = int(self.dfn) + stat_bonus
            return SettlementPhaseOutcome(
                action="grew",
                hp_delta=0,
                max_hp_delta=0,
                eco_delta=eco_growth,
                atk_delta=stat_bonus,
                dfn_delta=stat_bonus,
            )

        return SettlementPhaseOutcome(action="none")

    def run_combat_round(
        self,
        dragon: Dragon,
        world: GameMap,
        *,
        citadel_coord: OffsetCoord,
    ) -> DamageRoundExchange | MoveAttempt:
        """Resolve one dragon-vs-settlement damage round and write settlement HP."""

        return resolve_settlement_combat_round(dragon, self, world, citadel_coord=citadel_coord)

    def add_aggression(
        self,
        amount: int,
        tuning: GameTuning | None = None,
    ) -> Army | None:
        """Add local aggression, spawning an army if the threshold is reached."""

        self.aggression += max(0, amount)
        return self.check_aggression_threshold(tuning=tuning)

    def check_aggression_threshold(
        self,
        tuning: GameTuning | None = None,
    ) -> Army | None:
        """Spawn an army and reset aggression when the threshold is met (spec num9)."""

        if self.aggression < self.aggression_threshold:
            return None

        self.aggression = 0
        from .army import Army

        return Army.spawn_from_settlement(self, tuning=tuning)

    def spill_aggression_to_nearby(
        self,
        settlements: Iterable[Settlement],
        *,
        tuning: GameTuning | None = None,
    ) -> list[Army]:
        """Apply distance-dropoff aggression spillover and return any spawned armies."""

        t = _resolved_tuning(tuning)
        dropoff = t.raid_aggression_dropoff_per_tile
        candidates = [s for s in settlements if s is not self]
        candidates.sort(
            key=lambda s: settlement_hex_distance(self.position, s.position),
        )
        events: list[Army] = []
        for settlement in candidates:
            dist = settlement_hex_distance(self.position, settlement.position)
            amount = raid_spill_aggression_amount(dist, dropoff=dropoff)
            if amount == 0:
                break
            event = settlement.add_aggression(amount, tuning=tuning)
            if event is not None:
                events.append(event)
        return events

    def on_raid_defeat(
        self,
        settlements: Iterable[Settlement],
        *,
        tuning: GameTuning | None = None,
    ) -> list[Army]:
        """Apply the raid-defeat bundle after this settlement reaches 0 HP."""

        t = _resolved_tuning(tuning)
        self.eco = max(0, int(int(self.eco) / t.raid_eco_loss_divisor))
        self.atk = max(0, int(self.atk) - t.raid_stat_loss)
        self.dfn = max(0, int(self.dfn) - t.raid_stat_loss)

        events: list[Army] = []
        direct_event = self.add_aggression(RAID_DIRECT_AGGRESSION, tuning=tuning)
        if direct_event is not None:
            events.append(direct_event)
        events.extend(self.spill_aggression_to_nearby(settlements, tuning=tuning))
        return events


class Village(Settlement):
    """Village settlement with low economy and combat strength."""

    __slots__ = ()

    def __init__(self, position: OffsetCoord, *, aggression: int = 0) -> None:
        super().__init__(
            hp=500,
            max_hp=500,
            eco=400,
            starting_eco=400,
            atk=50,
            dfn=30,
            aggression=aggression,
            aggression_threshold=500,
            position=position,
            settlement_type=SettlementType.VILLAGE,
        )


class City(Settlement):
    """City settlement with high economy and balanced combat strength."""

    __slots__ = ()

    def __init__(self, position: OffsetCoord, *, aggression: int = 0) -> None:
        super().__init__(
            hp=800,
            max_hp=800,
            eco=800,
            starting_eco=800,
            atk=70,
            dfn=80,
            aggression=aggression,
            aggression_threshold=600,
            position=position,
            settlement_type=SettlementType.CITY,
        )


class Fort(Settlement):
    """Fort settlement with defensive stats and low aggression threshold."""

    __slots__ = ()

    def __init__(self, position: OffsetCoord, *, aggression: int = 0) -> None:
        super().__init__(
            hp=800,
            max_hp=800,
            eco=150,
            starting_eco=150,
            atk=80,
            dfn=80,
            aggression=aggression,
            aggression_threshold=300,
            position=position,
            settlement_type=SettlementType.FORT,
        )


def raid_victory_gold_from_eco(eco: int) -> int:
    """Gold granted on raid victory; must match :func:`apply_raid_victory_loot`."""

    return eco * RAID_VICTORY_GOLD_PERCENT_OF_ECO // 100


def apply_raid_victory_loot(dragon: Dragon, settlement: Settlement) -> None:
    """Grant raid spoils from ``eco`` before :meth:`Settlement.on_raid_defeat` halves it."""

    dragon.gold += raid_victory_gold_from_eco(settlement.eco)


def apply_settlement_raid_victory_bundle(
    dragon: Dragon,
    settlement: Settlement,
    settlements: Iterable[Settlement],
    *,
    tuning: GameTuning | None = None,
) -> tuple[int, list[Army]]:
    """After combat reduces settlement HP to 0: grant gold, then apply raid-defeat effects.

    Returns ``(gold_granted_this_step, spawn_events)`` for UI messaging.
    """

    gold_before = dragon.gold
    apply_raid_victory_loot(dragon, settlement)
    gold_added = dragon.gold - gold_before
    events = list(
        settlement.on_raid_defeat(settlements, tuning=tuning),
    )
    return gold_added, events


def validate_settlement_raid(
    dragon: Dragon, settlement: Settlement, world: GameMap
) -> tuple[bool, str]:
    """Return whether the dragon may initiate settlement combat at the simulation boundary."""

    tile = world.get(settlement.position)
    if tile is None:
        return False, "settlement tile not on loaded map"
    if tile.terrain is not Terrain.SETTLEMENT:
        return False, "target hex is not a settlement"
    if dragon.position != settlement.position:
        return False, "dragon must occupy the settlement hex to raid"
    return True, ""


def resolve_settlement_combat_round(
    dragon: Dragon,
    settlement: Settlement,
    world: GameMap,
    *,
    citadel_coord: OffsetCoord,
) -> DamageRoundExchange | MoveAttempt:
    """Run one 30-minute settlement combat round using the existing Dragon API."""

    from .dragon_abilities import apply_ice_talons_to_settlement, on_combat_round_started

    budget = dragon.validate_damage_round_preserves_return_to_citadel(citadel_coord)
    if not budget.ok:
        return budget

    from .combatant_stats import settlement_effective_atk
    from .dragon_abilities import settlement_defence_for_round

    on_combat_round_started(dragon)
    exchange = dragon.attack_settlement(
        settlement_hp=settlement.hp,
        settlement_defence_atk_proxy=settlement_effective_atk(settlement),
        settlement_dfn=settlement_defence_for_round(dragon, settlement),
        world=world,
    )
    if isinstance(exchange, DamageRoundExchange):
        settlement.hp = exchange.target_hp_after
        apply_ice_talons_to_settlement(dragon, settlement)
    return exchange


def run_settlement_combat_loop(
    dragon: Dragon,
    settlement: Settlement,
    world: GameMap,
    should_continue: Callable[[], bool],
    *,
    citadel_coord: OffsetCoord,
    settlements: Iterable[Settlement] | None = None,
    tuning: GameTuning | None = None,
    on_settlement_defeated: Callable[[Dragon, Settlement], None] | None = None,
) -> SettlementCombatLoopResult:
    """Resolve combat rounds until defeat, dragon loss, or callback-requested retreat.

    The first round always resolves immediately per spec num8. After each non-final
    round, ``should_continue`` decides whether to run another round. Real UI code
    will replace that callback; library code must not read from stdin.

    Retreating (``should_continue`` false) ends combat without applying the
    raid-defeat bundle—only HP already lost in resolved rounds remains changed.

    If ``settlements`` is supplied, settlement defeat triggers the raid-defeat
    bundle immediately when settlement HP reaches 0.
    """

    rounds = 0
    exchanges: list[DamageRoundExchange] = []
    spawn_events: list[Army] = []

    while True:
        exchange = resolve_settlement_combat_round(
            dragon, settlement, world, citadel_coord=citadel_coord
        )
        if isinstance(exchange, MoveAttempt):
            from .dragon_abilities import on_combat_ended

            on_combat_ended(dragon)
            return SettlementCombatLoopResult(
                rounds_resolved=rounds,
                retreated=False,
                exchanges=tuple(exchanges),
                spawn_events=tuple(spawn_events),
                last_failure=exchange,
            )

        rounds += 1
        exchanges.append(exchange)

        if settlement.hp == 0:
            from .dragon_abilities import on_combat_ended

            on_combat_ended(dragon)
            if on_settlement_defeated is not None:
                on_settlement_defeated(dragon, settlement)
            if settlements is not None:
                spawn_events.extend(
                    settlement.on_raid_defeat(settlements, tuning=tuning),
                )
            return SettlementCombatLoopResult(
                rounds_resolved=rounds,
                retreated=False,
                exchanges=tuple(exchanges),
                spawn_events=tuple(spawn_events),
            )

        if dragon.hp == 0:
            from .dragon_abilities import on_combat_ended

            on_combat_ended(dragon)
            return SettlementCombatLoopResult(
                rounds_resolved=rounds,
                retreated=False,
                exchanges=tuple(exchanges),
                spawn_events=tuple(spawn_events),
            )

        if not should_continue():
            from .dragon_abilities import on_combat_ended

            on_combat_ended(dragon)
            return SettlementCombatLoopResult(
                rounds_resolved=rounds,
                retreated=True,
                exchanges=tuple(exchanges),
                spawn_events=tuple(spawn_events),
            )


def resolve_settlement_raid(
    dragon: Dragon,
    settlement: Settlement,
    world: GameMap,
    settlements: Iterable[Settlement],
    *,
    citadel_coord: OffsetCoord,
    tuning: GameTuning | None = None,
) -> SettlementRaidResolution:
    """Auto-resolve combat; grant raid gold before the raid-defeat eco penalty."""

    ok, reason = validate_settlement_raid(dragon, settlement, world)
    if not ok:
        raise ValueError(reason)
    gold_before = dragon.gold
    combat = run_settlement_combat_loop(
        dragon,
        settlement,
        world,
        lambda: True,
        citadel_coord=citadel_coord,
        settlements=settlements,
        tuning=tuning,
        on_settlement_defeated=apply_raid_victory_loot,
    )
    return SettlementRaidResolution(combat=combat, gold_gained=dragon.gold - gold_before)


__all__ = [
    "City",
    "Fort",
    "MockArmySpawnEvent",
    "RAID_DIRECT_AGGRESSION",
    "RAID_ECO_LOSS_DIVISOR",
    "RAID_STAT_LOSS",
    "RAID_VICTORY_GOLD_PERCENT_OF_ECO",
    "SETTLEMENT_GROWTH_ECO_PERCENT",
    "SETTLEMENT_GROWTH_STAT_BONUS",
    "SETTLEMENT_HEAL_PERCENT_OF_MAX_AT_ZERO",
    "SETTLEMENT_HEAL_PERCENT_OF_MAX_WHEN_DAMAGED",
    "Settlement",
    "SettlementCombatLoopResult",
    "SettlementPhaseOutcome",
    "SettlementRaidResolution",
    "SettlementType",
    "Village",
    "apply_raid_victory_loot",
    "apply_settlement_raid_victory_bundle",
    "max_spill_distance",
    "raid_spill_aggression_amount",
    "raid_victory_gold_from_eco",
    "resolve_settlement_combat_round",
    "resolve_settlement_raid",
    "run_settlement_combat_loop",
    "settlement_hex_distance",
    "validate_settlement_raid",
]
