"""Army entities, phase resolution, and dragon combat (spec §§2, 8, 9, 10)."""

from __future__ import annotations

from dataclasses import dataclass

from .army_pathfinding import advance_along_path, army_sort_key
from .citadel import CitadelState
from .dragon import DamageRoundExchange, Dragon, MoveAttempt
from .hex_coord import OffsetCoord
from .map_state import GameMap

DEFAULT_ARMY_MOVEMENT_SPEED: int = 12
ARMY_HP_PERCENT_OF_SETTLEMENT_MAX: int = 66
ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK: int = 90
ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN: int = 50


@dataclass(slots=True)
class Army:
    """Land army stack moving toward the citadel during the army phase."""

    hp: int
    atk: int
    dfn: int
    movement_speed: int
    position: OffsetCoord

    @classmethod
    def spawn_from_settlement(cls, settlement: object) -> Army:
        """Create an army using MVP spawn ratios (spec §9)."""

        return cls(
            hp=settlement.max_hp * ARMY_HP_PERCENT_OF_SETTLEMENT_MAX // 100,
            atk=settlement.atk * ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK // 100,
            dfn=settlement.dfn * ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN // 100,
            movement_speed=DEFAULT_ARMY_MOVEMENT_SPEED,
            position=settlement.position,
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
    """Collapse co-located armies into one stack per hex (spec §2, §9).

    Combined HP/ATK/DFN use **sum**. ``movement_speed`` uses **max** so merged
    stacks retain the fastest march rate among contributors.
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
                atk=sum(a.atk for a in group),
                dfn=sum(a.dfn for a in group),
                movement_speed=max(a.movement_speed for a in group),
                position=position,
            )
        )
    return merged


def army_from_spawn_event(event: Army | object, settlement: object | None = None) -> Army:
    """Bridge aggression spawns (``Army``) or legacy ``MockArmySpawnEvent`` for playtest."""

    if isinstance(event, Army):
        return event
    if settlement is not None:
        return Army.spawn_from_settlement(settlement)
    position = event.position
    max_hp = 500
    atk = int(event.atk)
    dfn = int(event.dfn)
    return Army(
        hp=max(1, max_hp * ARMY_HP_PERCENT_OF_SETTLEMENT_MAX // 100),
        atk=max(1, atk * ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK // 100),
        dfn=max(0, dfn * ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN // 100),
        movement_speed=DEFAULT_ARMY_MOVEMENT_SPEED,
        position=position,
    )


def run_army_phase(
    game_map: GameMap,
    armies: list[Army],
    *,
    citadel_coord: OffsetCoord,
    citadel_hp: int,
) -> ArmyPhaseResult:
    """Resolve army movement, merge, and citadel attacks (spec §2 Phase 4)."""

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
    """Run one 30-minute dragon-vs-army damage round (spec §8)."""

    ok, reason = validate_dragon_vs_army(dragon, army, world)
    if not ok:
        return MoveAttempt(ok=False, reason=reason)

    budget = dragon.validate_damage_round_preserves_return_to_citadel(citadel_coord)
    if not budget.ok:
        return budget

    exchange = dragon.attack_army(
        army_hp=army.hp,
        army_atk=army.atk,
        army_dfn=army.dfn,
        world=world,
    )
    if isinstance(exchange, DamageRoundExchange):
        army.hp = exchange.target_hp_after
    return exchange


def collect_spawned_armies(spawned: list[Army]) -> list[Army]:
    """Registry helper: filter defeated spawns and return live armies."""

    return [army for army in spawned if not army.is_defeated()]


__all__ = [
    "ARMY_ATK_PERCENT_OF_SETTLEMENT_ATK",
    "ARMY_DFN_PERCENT_OF_SETTLEMENT_DFN",
    "ARMY_HP_PERCENT_OF_SETTLEMENT_MAX",
    "DEFAULT_ARMY_MOVEMENT_SPEED",
    "Army",
    "ArmyPhaseResult",
    "army_from_spawn_event",
    "collect_spawned_armies",
    "merge_army_stacks",
    "resolve_army_combat_round",
    "run_army_phase",
    "validate_dragon_vs_army",
]
