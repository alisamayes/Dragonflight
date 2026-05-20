"""Army entities, phase resolution, and dragon combat (spec numnum2, 8, 9, 10)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Protocol, cast

from .army_pathfinding import advance_along_path, army_sort_key
from .citadel import CitadelState
from .dragon import DamageRoundExchange, Dragon, MoveAttempt
from .hex_coord import OffsetCoord
from .map_state import GameMap

if TYPE_CHECKING:
    from .game_tuning import GameTuning

DEFAULT_ARMY_MOVEMENT_SPEED: int = 12
ARMY_HP_PERCENT_OF_SETTLEMENT_MAX: int = 66
ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK: int = 90
ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN: int = 50
HEROES_PARTY_WAVE_INTERVAL_TURNS: int = 5
HEROES_PARTY_STAT_BONUS_PER_TURN: int = 2
STANDARD_ARMY_VICTORY_GOLD_PERCENT_OF_ECO: int = 10
HEROES_PARTY_VICTORY_GOLD_PERCENT_OF_ECO: int = 25


class ArmyKind(Enum):
    """Distinguishes standard aggression armies from late-game Hero's Party waves."""

    STANDARD = "standard"
    HEROES_PARTY = "heroes_party"


class _ArmySpawnSettlement(Protocol):
    max_hp: int
    atk: int
    dfn: int
    eco: int
    position: OffsetCoord


class _StandaloneSpawnPayload(Protocol):
    position: OffsetCoord
    atk: int
    dfn: int


class _HeroesPartySpawnCity(Protocol):
    max_hp: int
    atk: int
    dfn: int
    eco: int
    position: OffsetCoord


@dataclass(slots=True)
class Army:
    """Land army stack moving toward the citadel during the army phase."""

    hp: int
    max_hp: int
    atk: int
    dfn: int
    movement_speed: int
    position: OffsetCoord
    kind: ArmyKind = ArmyKind.STANDARD
    victory_gold: int = 0
    source_coord: OffsetCoord | None = None

    @classmethod
    def spawn_from_settlement(
        cls,
        settlement: _ArmySpawnSettlement,
        *,
        tuning: GameTuning | None = None,
    ) -> Army:
        """Create an army using MVP spawn ratios (spec num9)."""

        from .game_tuning import resolve_tuning

        movement_speed = resolve_tuning(tuning).army_movement_speed
        hp_val = settlement.max_hp * ARMY_HP_PERCENT_OF_SETTLEMENT_MAX // 100
        return cls(
            hp=hp_val,
            max_hp=hp_val,
            atk=settlement.atk * ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK // 100,
            dfn=settlement.dfn * ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN // 100,
            movement_speed=movement_speed,
            position=settlement.position,
            kind=ArmyKind.STANDARD,
            victory_gold=standard_army_victory_gold_from_eco(settlement.eco),
            source_coord=settlement.position,
        )

    @classmethod
    def spawn_heroes_party_from_city(
        cls,
        city: _HeroesPartySpawnCity,
        *,
        turn_count: int,
        tuning: GameTuning | None = None,
    ) -> Army:
        """Spawn a Hero's Party stack from a live city (late-game wave rules)."""

        from .game_tuning import resolve_tuning

        movement_speed = resolve_tuning(tuning).army_movement_speed
        hp_val = city.max_hp
        bonus = HEROES_PARTY_STAT_BONUS_PER_TURN * turn_count
        return cls(
            hp=hp_val,
            max_hp=hp_val,
            atk=city.atk + bonus,
            dfn=city.dfn + bonus,
            movement_speed=movement_speed,
            position=city.position,
            kind=ArmyKind.HEROES_PARTY,
            victory_gold=heroes_party_victory_gold_from_eco(city.eco),
            source_coord=city.position,
        )

    def is_defeated(self) -> bool:
        return self.hp <= 0


@dataclass(frozen=True, slots=True)
class ArmyPhaseResult:
    """Outcome of end-of-turn army phase resolution."""

    armies: tuple[Army, ...]
    citadel_hp: int
    citadel_attacks: int
    merged_stacks: int
    game_over: bool
    messages: tuple[str, ...] = ()


def merge_army_stacks(armies: list[Army]) -> list[Army]:
    """Collapse co-located armies into one stack per hex (spec num2, num9).

    Combined HP/``max_hp``/ATK/DFN use sum. ``movement_speed`` uses max so
    merged stacks retain the fastest march rate among contributors.
    """

    by_position: dict[OffsetCoord, list[Army]] = {}
    for army in armies:
        by_position.setdefault(army.position, []).append(army)

    merged: list[Army] = []
    for position, group in by_position.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        merged.append(
            Army(
                hp=sum(a.hp for a in group),
                max_hp=sum(a.max_hp for a in group),
                atk=sum(a.atk for a in group),
                dfn=sum(a.dfn for a in group),
                movement_speed=max(a.movement_speed for a in group),
                position=position,
                kind=(
                    ArmyKind.HEROES_PARTY
                    if any(a.kind == ArmyKind.HEROES_PARTY for a in group)
                    else ArmyKind.STANDARD
                ),
                victory_gold=sum(a.victory_gold for a in group),
                source_coord=next(
                    (a.source_coord for a in group if a.source_coord is not None),
                    None,
                ),
            )
        )
    return merged


def army_from_spawn_event(
    event: Army | object,
    settlement: _ArmySpawnSettlement | None = None,
    *,
    tuning: GameTuning | None = None,
) -> Army:
    """Bridge aggression spawns (``Army``) or legacy ``MockArmySpawnEvent`` for playtest."""

    if isinstance(event, Army):
        return event
    if settlement is not None:
        return Army.spawn_from_settlement(settlement, tuning=tuning)
    orphan = cast(_StandaloneSpawnPayload, event)
    position = orphan.position
    max_hp = 500
    atk = int(orphan.atk)
    dfn = int(orphan.dfn)
    from .game_tuning import resolve_tuning

    movement_speed = resolve_tuning(tuning).army_movement_speed
    hp_val = max(1, max_hp * ARMY_HP_PERCENT_OF_SETTLEMENT_MAX // 100)
    return Army(
        hp=hp_val,
        max_hp=hp_val,
        atk=max(1, atk * ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK // 100),
        dfn=max(0, dfn * ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN // 100),
        movement_speed=movement_speed,
        position=position,
        kind=ArmyKind.STANDARD,
        victory_gold=0,
        source_coord=orphan.position,
    )


def standard_army_victory_gold_from_eco(eco: int) -> int:
    """Gold granted when the dragon defeats a standard aggression army."""

    return int(eco) * STANDARD_ARMY_VICTORY_GOLD_PERCENT_OF_ECO // 100


def heroes_party_victory_gold_from_eco(eco: int) -> int:
    """Gold granted when the dragon defeats a Hero's Party stack."""

    return int(eco) * HEROES_PARTY_VICTORY_GOLD_PERCENT_OF_ECO // 100


def should_spawn_heroes_party_wave(day_index: int) -> bool:
    """Return whether ``day_index`` triggers a Hero's Party wave (every 5 turns)."""

    return day_index > 0 and day_index % HEROES_PARTY_WAVE_INTERVAL_TURNS == 0


def eligible_heroes_party_cities(settlements: Iterable[object]) -> list[object]:
    """Live cities sorted by ``(row, col)`` for deterministic wave picks."""

    from .settlement import SettlementType

    cities = [
        s
        for s in settlements
        if getattr(s, "settlement_type", None) == SettlementType.CITY and int(getattr(s, "hp", 0)) > 0
    ]
    return sorted(cities, key=lambda s: (s.position.row, s.position.col))


@dataclass(slots=True)
class HeroesPartyCityPool:
    """Shuffled cycle of city coords for Hero's Party wave selection."""

    queue: list[OffsetCoord] = field(default_factory=list)


def pick_heroes_party_cities(
    eligible_cities: list[object],
    limit: int,
    pool: HeroesPartyCityPool,
    rng: random.Random,
) -> tuple[list[object], HeroesPartyCityPool]:
    """Pick up to ``limit`` cities from the rotating shuffled pool."""

    if limit <= 0:
        return [], pool

    by_coord = {s.position: s for s in eligible_cities}
    queue = [coord for coord in pool.queue if coord in by_coord]

    if not queue:
        coords = [s.position for s in eligible_cities]
        queue = list(coords)
        rng.shuffle(queue)

    picked: list[object] = []
    while len(picked) < limit and queue:
        coord = queue.pop(0)
        city = by_coord.get(coord)
        if city is not None:
            picked.append(city)

    return picked, HeroesPartyCityPool(queue=queue)


def spawn_heroes_party_wave(
    settlements: Iterable[object],
    day_index: int,
    *,
    tuning: GameTuning | None = None,
    pool: HeroesPartyCityPool | None = None,
    rng: random.Random | None = None,
) -> tuple[list[Army], HeroesPartyCityPool]:
    """Spawn Hero's Party armies from the rotating city pool when due."""

    current_pool = pool if pool is not None else HeroesPartyCityPool()
    if not should_spawn_heroes_party_wave(day_index):
        return [], current_pool
    from .game_tuning import resolve_tuning

    limit = resolve_tuning(tuning).heroes_party_cities_per_wave
    if limit <= 0:
        return [], current_pool

    eligible = eligible_heroes_party_cities(settlements)
    shuffle_rng = rng if rng is not None else random.Random()
    cities, updated_pool = pick_heroes_party_cities(
        eligible,
        limit,
        current_pool,
        shuffle_rng,
    )
    armies = [
        Army.spawn_heroes_party_from_city(city, turn_count=day_index, tuning=tuning)
        for city in cities
    ]
    return armies, updated_pool


def grant_army_victory_loot(dragon: Dragon, army: Army) -> int:
    """Grant stored ``victory_gold`` once, then zero it on the army."""

    if army.victory_gold <= 0:
        return 0
    amount = army.victory_gold
    dragon.gold += amount
    army.victory_gold = 0
    return amount


def run_army_phase(
    game_map: GameMap,
    armies: list[Army],
    *,
    citadel_coord: OffsetCoord,
    citadel_hp: int,
) -> ArmyPhaseResult:
    """Resolve army movement, merge, and citadel attacks (spec num2 Phase 4)."""

    citadel = CitadelState(position=citadel_coord, hp=citadel_hp)
    active = [army for army in armies if not army.is_defeated()]
    ordered = sorted(
        active,
        key=lambda army: army_sort_key(army.position, citadel_coord, game_map),
    )

    for army in ordered:
        army.position = advance_along_path(
            army.position,
            citadel_coord,
            army.movement_speed,
            game_map,
        )

    before_merge = len(active)
    merged = merge_army_stacks(active)
    merged_stacks = before_merge - len(merged)

    attackers = [army for army in merged if army.position == citadel_coord]
    citadel_attacks = len(attackers)
    messages: list[str] = []
    for _ in attackers:
        citadel.apply_army_attack()
        messages.append("An army reached the citadel and dealt 1 damage.")

    surviving = tuple(army for army in merged if army.position != citadel_coord)
    return ArmyPhaseResult(
        armies=surviving,
        citadel_hp=citadel.hp,
        citadel_attacks=citadel_attacks,
        merged_stacks=merged_stacks,
        game_over=citadel.is_destroyed(),
        messages=tuple(messages),
    )


def validate_dragon_vs_army(
    dragon: Dragon,
    army: Army,
    world: GameMap | None = None,
    *,
    citadel_coord: OffsetCoord | None = None,
) -> tuple[bool, str]:
    """Return whether the dragon may initiate army combat at the simulation boundary."""

    if army.is_defeated():
        return False, "army already defeated"
    if world is None:
        if dragon.position != army.position:
            return False, "dragon must occupy the army hex to attack"
        if citadel_coord is not None:
            budget = dragon.validate_damage_round_preserves_return_to_citadel(citadel_coord)
            if not budget.ok:
                return False, budget.reason
        return True, ""
    tile = world.get(army.position)
    if tile is None:
        return False, "army tile not on loaded map"
    if dragon.position != army.position:
        return False, "dragon must occupy the army hex to attack"
    return True, ""


def resolve_army_combat_round(
    dragon: Dragon,
    army: Army,
    world: GameMap,
    *,
    citadel_coord: OffsetCoord,
) -> DamageRoundExchange | MoveAttempt:
    """Run one 30-minute dragon-vs-army damage round (spec num8)."""

    ok, reason = validate_dragon_vs_army(dragon, army, world)
    if not ok:
        return MoveAttempt(ok=False, reason=reason)

    budget = dragon.validate_damage_round_preserves_return_to_citadel(citadel_coord)
    if not budget.ok:
        return budget

    from .dragon_abilities import (
        apply_ice_talons_to_army,
        enemy_defence_for_round,
        on_combat_round_started,
    )

    on_combat_round_started(dragon)
    exchange = dragon.attack_army(
        army_hp=army.hp,
        army_atk=army.atk,
        army_dfn=enemy_defence_for_round(dragon, army.position, army.dfn),
        world=world,
    )
    if isinstance(exchange, DamageRoundExchange):
        army.hp = exchange.target_hp_after
        apply_ice_talons_to_army(dragon, army)
    return exchange


def collect_spawned_armies(spawned: list[Army]) -> list[Army]:
    """Registry helper: filter defeated spawns and return live armies."""

    return [army for army in spawned if not army.is_defeated()]


__all__ = [
    "ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK",
    "ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN",
    "ARMY_HP_PERCENT_OF_SETTLEMENT_MAX",
    "DEFAULT_ARMY_MOVEMENT_SPEED",
    "HEROES_PARTY_STAT_BONUS_PER_TURN",
    "HEROES_PARTY_VICTORY_GOLD_PERCENT_OF_ECO",
    "HEROES_PARTY_WAVE_INTERVAL_TURNS",
    "Army",
    "ArmyKind",
    "ArmyPhaseResult",
    "army_from_spawn_event",
    "collect_spawned_armies",
    "eligible_heroes_party_cities",
    "HeroesPartyCityPool",
    "STANDARD_ARMY_VICTORY_GOLD_PERCENT_OF_ECO",
    "pick_heroes_party_cities",
    "grant_army_victory_loot",
    "heroes_party_victory_gold_from_eco",
    "standard_army_victory_gold_from_eco",
    "merge_army_stacks",
    "resolve_army_combat_round",
    "run_army_phase",
    "should_spawn_heroes_party_wave",
    "spawn_heroes_party_wave",
    "validate_dragon_vs_army",
]
