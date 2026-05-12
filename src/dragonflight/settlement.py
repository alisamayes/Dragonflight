"""Settlement rules for growth, dragon combat, and raid defeat (spec §§6, 8)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal

from .dragon import DamageRoundExchange, Dragon, MoveAttempt
from .hex_coord import OffsetCoord, distance, offset_to_axial
from .terrain import Terrain

if TYPE_CHECKING:
    from .map_state import GameMap


#: When settlement ``hp == 0``, heal this percent of :attr:`Settlement.max_hp` per
#: settlement phase tick.
SETTLEMENT_HEAL_PERCENT_OF_MAX_AT_ZERO: int = 80
#: When ``0 < hp < max_hp``, heal this percent of :attr:`Settlement.max_hp` per tick.
SETTLEMENT_HEAL_PERCENT_OF_MAX_WHEN_DAMAGED: int = 40
SETTLEMENT_GROWTH_ECO_PERCENT: int = 10
SETTLEMENT_GROWTH_STAT_BONUS: int = 5

RAID_ECO_LOSS_DIVISOR: int = 2
RAID_STAT_LOSS: int = 10
#: Percent of the defeated settlement's current ``eco`` granted as dragon gold when a raid clears.
RAID_VICTORY_GOLD_PERCENT_OF_ECO: int = 50
RAID_DIRECT_AGGRESSION: int = 300
RAID_NEARBY_AGGRESSION: int = 150
DEFAULT_NEARBY_RADIUS_MAP_WIDTH_PERCENT: int = 15


class SettlementType(Enum):
    """Supported MVP settlement archetypes."""

    VILLAGE = "village"
    CITY = "city"
    FORT = "fort"


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
class MockArmySpawnEvent:
    """MVP stand-in for army creation when aggression crosses its threshold."""

    position: OffsetCoord
    settlement_type: SettlementType
    eco: int
    atk: int
    dfn: int


@dataclass(frozen=True, slots=True)
class SettlementCombatLoopResult:
    """Outcome from resolving settlement combat until defeat, dragon loss, or retreat."""

    rounds_resolved: int
    retreated: bool
    exchanges: tuple[DamageRoundExchange, ...]
    spawn_events: tuple[MockArmySpawnEvent, ...] = ()
    last_failure: MoveAttempt | None = None


@dataclass(frozen=True, slots=True)
class SettlementRaidResolution:
    """Structured result from auto-resolving a settlement raid (combat + raid-defeat bundle)."""

    combat: SettlementCombatLoopResult
    gold_gained: int


def nearby_aggression_radius(map_width: int) -> int:
    """Return the default nearby-spill radius: rounded 15% of map width."""

    return round(map_width * DEFAULT_NEARBY_RADIUS_MAP_WIDTH_PERCENT / 100)


def settlement_hex_distance(a: OffsetCoord, b: OffsetCoord) -> int:
    """Hex distance between two offset settlement coordinates."""

    return distance(offset_to_axial(a), offset_to_axial(b))


def is_within_nearby_radius(origin: OffsetCoord, candidate: OffsetCoord, radius: int) -> bool:
    """Return whether ``candidate`` receives aggression spillover from ``origin``."""

    return settlement_hex_distance(origin, candidate) <= radius


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

    def on_settlement_phase_end(self) -> SettlementPhaseOutcome:
        """Apply one end-of-settlement-phase tick.

        Damaged settlements (``hp < max_hp``) heal only—no eco/stat growth that tick.
        Undamaged settlements (``hp == max_hp``) grow ``eco`` and raise ``atk``/``dfn``;
        ``hp`` and ``max_hp`` are unchanged on growth ticks.
        """

        if self.hp < self.max_hp:
            if self.hp == 0:
                healing = self.max_hp * SETTLEMENT_HEAL_PERCENT_OF_MAX_AT_ZERO // 100
            else:
                healing = self.max_hp * SETTLEMENT_HEAL_PERCENT_OF_MAX_WHEN_DAMAGED // 100
            hp_before = self.hp
            self.hp = min(self.max_hp, self.hp + healing)
            return SettlementPhaseOutcome(action="healed", hp_delta=self.hp - hp_before)

        if self.hp == self.max_hp:
            eco_growth = self.starting_eco * SETTLEMENT_GROWTH_ECO_PERCENT // 100
            self.eco += eco_growth
            self.atk += SETTLEMENT_GROWTH_STAT_BONUS
            self.dfn += SETTLEMENT_GROWTH_STAT_BONUS
            return SettlementPhaseOutcome(
                action="grew",
                hp_delta=0,
                max_hp_delta=0,
                eco_delta=eco_growth,
                atk_delta=SETTLEMENT_GROWTH_STAT_BONUS,
                dfn_delta=SETTLEMENT_GROWTH_STAT_BONUS,
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

    def add_aggression(self, amount: int) -> MockArmySpawnEvent | None:
        """Add local aggression, spawning a mock army if the threshold is reached."""

        self.aggression += max(0, amount)
        return self.check_aggression_threshold()

    def check_aggression_threshold(self) -> MockArmySpawnEvent | None:
        """Spawn a mock army and reset aggression when the threshold is met."""

        if self.aggression < self.aggression_threshold:
            return None

        self.aggression = 0
        return MockArmySpawnEvent(
            position=self.position,
            settlement_type=self.settlement_type,
            eco=self.eco,
            atk=self.atk,
            dfn=self.dfn,
        )

    def spill_aggression_to_nearby(
        self,
        settlements: Iterable[Settlement],
        *,
        map_width: int,
        radius: int | None = None,
    ) -> list[MockArmySpawnEvent]:
        """Apply nearby aggression spillover and return any mock spawn events."""

        spill_radius = nearby_aggression_radius(map_width) if radius is None else radius
        events: list[MockArmySpawnEvent] = []
        for settlement in settlements:
            if settlement is self:
                continue
            if is_within_nearby_radius(self.position, settlement.position, spill_radius):
                event = settlement.add_aggression(RAID_NEARBY_AGGRESSION)
                if event is not None:
                    events.append(event)
        return events

    def on_raid_defeat(
        self,
        settlements: Iterable[Settlement],
        *,
        map_width: int,
        radius: int | None = None,
    ) -> list[MockArmySpawnEvent]:
        """Apply the raid-defeat bundle after this settlement reaches 0 HP."""

        self.eco //= RAID_ECO_LOSS_DIVISOR
        self.atk = max(0, self.atk - RAID_STAT_LOSS)
        self.dfn = max(0, self.dfn - RAID_STAT_LOSS)

        events: list[MockArmySpawnEvent] = []
        direct_event = self.add_aggression(RAID_DIRECT_AGGRESSION)
        if direct_event is not None:
            events.append(direct_event)
        events.extend(
            self.spill_aggression_to_nearby(settlements, map_width=map_width, radius=radius)
        )
        return events


class Village(Settlement):
    """Village settlement with low economy and combat strength."""

    __slots__ = ()

    def __init__(self, position: OffsetCoord, *, aggression: int = 0) -> None:
        super().__init__(
            hp=400,
            max_hp=500,
            eco=500,
            starting_eco=500,
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
            max_hp=1000,
            eco=1000,
            starting_eco=1000,
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
            hp=600,
            max_hp=800,
            eco=100,
            starting_eco=100,
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
    map_width: int,
) -> tuple[int, list[MockArmySpawnEvent]]:
    """After combat reduces settlement HP to 0: grant gold, then apply raid-defeat effects.

    Returns ``(gold_granted_this_step, spawn_events)`` for UI messaging.
    """

    gold_before = dragon.gold
    apply_raid_victory_loot(dragon, settlement)
    gold_added = dragon.gold - gold_before
    events = list(settlement.on_raid_defeat(settlements, map_width=map_width))
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

    budget = dragon.validate_damage_round_preserves_return_to_citadel(citadel_coord)
    if not budget.ok:
        return budget

    exchange = dragon.attack_settlement(
        settlement_hp=settlement.hp,
        settlement_defence_atk_proxy=settlement.atk,
        settlement_dfn=settlement.dfn,
        world=world,
    )
    if isinstance(exchange, DamageRoundExchange):
        settlement.hp = exchange.target_hp_after
    return exchange


def run_settlement_combat_loop(
    dragon: Dragon,
    settlement: Settlement,
    world: GameMap,
    should_continue: Callable[[], bool],
    *,
    citadel_coord: OffsetCoord,
    settlements: Iterable[Settlement] | None = None,
    map_width: int | None = None,
    on_settlement_defeated: Callable[[Dragon, Settlement], None] | None = None,
) -> SettlementCombatLoopResult:
    """Resolve combat rounds until defeat, dragon loss, or callback-requested retreat.

    The first round always resolves immediately per spec §8. After each non-final
    round, ``should_continue`` decides whether to run another round. Real UI code
    will replace that callback; library code must not read from stdin.

    Retreating (``should_continue`` false) ends combat without applying the
    raid-defeat bundle—only HP already lost in resolved rounds remains changed.

    If ``settlements`` and ``map_width`` are supplied, settlement defeat triggers
    the raid-defeat bundle immediately when settlement HP reaches 0.
    """

    rounds = 0
    exchanges: list[DamageRoundExchange] = []
    spawn_events: list[MockArmySpawnEvent] = []

    while True:
        exchange = resolve_settlement_combat_round(
            dragon, settlement, world, citadel_coord=citadel_coord
        )
        if isinstance(exchange, MoveAttempt):
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
            if on_settlement_defeated is not None:
                on_settlement_defeated(dragon, settlement)
            if settlements is not None and map_width is not None:
                spawn_events.extend(settlement.on_raid_defeat(settlements, map_width=map_width))
            return SettlementCombatLoopResult(
                rounds_resolved=rounds,
                retreated=False,
                exchanges=tuple(exchanges),
                spawn_events=tuple(spawn_events),
            )

        if dragon.hp == 0:
            return SettlementCombatLoopResult(
                rounds_resolved=rounds,
                retreated=False,
                exchanges=tuple(exchanges),
                spawn_events=tuple(spawn_events),
            )

        if not should_continue():
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
    map_width: int,
    citadel_coord: OffsetCoord,
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
        map_width=map_width,
        on_settlement_defeated=apply_raid_victory_loot,
    )
    return SettlementRaidResolution(combat=combat, gold_gained=dragon.gold - gold_before)


__all__ = [
    "DEFAULT_NEARBY_RADIUS_MAP_WIDTH_PERCENT",
    "City",
    "Fort",
    "MockArmySpawnEvent",
    "RAID_DIRECT_AGGRESSION",
    "RAID_ECO_LOSS_DIVISOR",
    "RAID_NEARBY_AGGRESSION",
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
    "is_within_nearby_radius",
    "nearby_aggression_radius",
    "raid_victory_gold_from_eco",
    "resolve_settlement_combat_round",
    "resolve_settlement_raid",
    "run_settlement_combat_loop",
    "settlement_hex_distance",
    "validate_settlement_raid",
]
