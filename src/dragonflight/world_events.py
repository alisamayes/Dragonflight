"""Random world events at the start of each player day (see Documentation/wolrd_event_details.md)."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .entity_stats import (
    ModifierExpiry,
    ModifierKind,
    StatKey,
    StatModifier,
    add_modifier,
)
from .hex_coord import OffsetCoord, distance, offset_to_axial
from .map_state import GameMap
from .terrain import Terrain

if TYPE_CHECKING:
    from .army import Army
    from .dragon import Dragon
    from .fog_of_war import FogOfWarState
    from .game_tuning import GameTuning
    from .settlement import Settlement

WORLD_EVENT_SOURCE_PREFIX = "world_event:"

DEFAULT_WORLD_EVENT_CHANCE_PERCENT: int = 50


@dataclass(frozen=True, slots=True)
class WorldEventSpec:
    """One authored world event (id, player-facing text, internal effect key)."""

    event_id: str
    description: str


@dataclass(slots=True)
class WorldEventDayState:
    """Active world-event hooks for the current player day."""

    active_event_id: str | None = None
    double_settlement_growth: bool = False
    double_settlement_healing: bool = False
    heavy_rain_eco_growth_mult: float = 1.0
    growth_delayed_coords: set[OffsetCoord] = field(default_factory=set)
    rivers_passable_for_armies: bool = False
    dark_eclipse: bool = False
    pending_revenge_raider: bool = False

    def clear(self) -> None:
        self.active_event_id = None
        self.double_settlement_growth = False
        self.double_settlement_healing = False
        self.heavy_rain_eco_growth_mult = 1.0
        self.growth_delayed_coords.clear()
        self.rivers_passable_for_armies = False
        self.dark_eclipse = False
        self.pending_revenge_raider = False


@dataclass(frozen=True, slots=True)
class WorldEventRollResult:
    """Outcome of the daily world-event roll."""

    triggered: bool
    event_id: str | None = None
    description: str = ""
    extra_messages: tuple[str, ...] = ()


WORLD_EVENTS: tuple[WorldEventSpec, ...] = (
    WorldEventSpec(
        "raider_army",
        "Rumours of this land's spoils and current instability due to your presence "
        "have caused a mercenary raiding party to appear. Seeing your grand Citadel "
        "on the horizon they are making a rush for it in hopes of looting your domain.",
    ),
    WorldEventSpec(
        "storm_winds",
        "Rough storm clouds roll in causing thunder and lightning to echo across the "
        "land. Howling winds rip through the air, buffeting you as you fly and making "
        "it difficult to travel.",
    ),
    WorldEventSpec(
        "town_militia",
        "All the settlements in the land have rallied their militia for a short time. "
        "Their citizens line the walls and bear makeshift weapons, ready to protect "
        "their homes in these troubled times.",
    ),
    WorldEventSpec(
        "settlement_investments",
        "The settlements of the lands have decided to invest extra spending into "
        "improving their homeland, fortify their settlements and build more "
        "infrastructure.",
    ),
    WorldEventSpec(
        "snowfall",
        "Heavy snow blankets the lands, coating the ground in a layer of white and "
        "freezing rivers. The human armies struggle to trudge through the thick "
        "snowfall, drastically slowing them down; however perhaps new routes have "
        "opened up to them.",
    ),
    WorldEventSpec(
        "heatwave",
        "The sun burns bright today, bathing your domain in harsh light and high "
        "temperatures. The heat helps enhance your fire, granting it additional "
        "power to burn your foes.",
    ),
    WorldEventSpec(
        "heavy_rain",
        "The clouds are dark and rain falls hard and heavy. The water coating "
        "everything makes it harder to burn, but the settlements below rejoice as "
        "their crops are well provided for, drinking from the damp earth.",
    ),
    WorldEventSpec(
        "arcane_fog",
        "Strange fog cloaks the land as tendrils of mist snake over the hills and "
        "through the forests, obscuring everything below. Otherworldly noises come "
        "from the fog that don't quite sound right and it's as if the land is moving. "
        "You find it difficult to see anything around you and the fog extends to your "
        "mind, removing even the memories of the landscape below. What could be "
        "causing this?",
    ),
    WorldEventSpec(
        "citadel_vigor",
        "The ancient magic of your home stirs, pleased by all the spoils you have "
        "returned with to add to your treasure trove. Roots sprout from the ground, "
        "wrapping around cracked bricks and strengthening them. Earth and stone meld "
        "into open holes in the walls left by attacks, forming new natural surfaces. "
        "Thorns and thickets sprout up around the ground further protecting your home "
        "and renewing its structure.",
    ),
    WorldEventSpec(
        "golden_caravan",
        "A wealthy merchant caravan has been spotted crossing through the land, its "
        "wagons laden with gold and exotic goods. They travel with a small guard "
        "escort, but their riches glitter in the sunlight, practically begging to be "
        "claimed. Of course, raiding them may draw the ire of distant kingdoms who "
        "funded the expedition.",
    ),
    WorldEventSpec(
        "earthquake",
        "The ground shakes violently as a tremor ripples across the land. Buildings "
        "crack, walls crumble, and great fissures tear open across roads and pathways. "
        "The settlements scramble to repair the damage while armies in the field "
        "struggle to maintain formation on the shifting earth.",
    ),
    WorldEventSpec(
        "dark_eclipse",
        "A black shroud envelops the sun, casting dark shadows everywhere.",
    ),
)

_EVENT_BY_ID: dict[str, WorldEventSpec] = {e.event_id: e for e in WORLD_EVENTS}


def world_event_by_id(event_id: str) -> WorldEventSpec | None:
    return _EVENT_BY_ID.get(event_id)


@dataclass(frozen=True, slots=True)
class ArmyMovementContext:
    """Pathfinding overrides for world events (e.g. snowfall river crossing)."""

    rivers_passable: bool = False
    forbid_stop_on_river: bool = False


def map_edge_coords(game_map: GameMap) -> list[OffsetCoord]:
    """Return border tiles on the authored map rectangle."""

    w, h = game_map.width, game_map.height
    return [
        coord
        for coord in game_map.tiles
        if coord.col in (0, w - 1) or coord.row in (0, h - 1)
    ]


def pick_random_edge_tile(game_map: GameMap, rng: random.Random) -> OffsetCoord | None:
    edges = map_edge_coords(game_map)
    if not edges:
        return None
    return rng.choice(edges)


def farthest_edge_tile(
    game_map: GameMap,
    origin: OffsetCoord,
    rng: random.Random,
) -> OffsetCoord | None:
    """Pick a border tile maximally distant from ``origin`` (ties broken randomly)."""

    edges = map_edge_coords(game_map)
    if not edges:
        return None
    origin_axial = offset_to_axial(origin)

    def dist_key(coord: OffsetCoord) -> int:
        return distance(origin_axial, offset_to_axial(coord))

    max_dist = max(dist_key(c) for c in edges)
    farthest = [c for c in edges if dist_key(c) == max_dist]
    return rng.choice(farthest)


def _day_end_mult(source: str, stat: StatKey, value: float) -> StatModifier:
    return StatModifier(
        stat=stat,
        kind=ModifierKind.PERCENT_MULT,
        value=value,
        expiry=ModifierExpiry.DAY_END,
        source=f"{WORLD_EVENT_SOURCE_PREFIX}{source}",
    )


def spawn_raider_army(
    game_map: GameMap,
    *,
    dragon_level: int,
    rng: random.Random,
) -> Army | None:
    from .army import Army, ArmyKind

    spawn = pick_random_edge_tile(game_map, rng)
    if spawn is None:
        return None
    level = max(1, int(dragon_level))
    hp = 400 + 10 * level
    return Army(
        hp=hp,
        max_hp=hp,
        atk=100 + 5 * level,
        dfn=50 + 5 * level,
        movement_speed=15,
        position=spawn,
        kind=ArmyKind.RAIDER,
        victory_gold=0,
        source_coord=spawn,
    )


def spawn_golden_caravan(
    game_map: GameMap,
    *,
    dragon_level: int,
    rng: random.Random,
) -> Army | None:
    from .army import Army, ArmyKind

    spawn = pick_random_edge_tile(game_map, rng)
    if spawn is None:
        return None
    goal = farthest_edge_tile(game_map, spawn, rng)
    if goal is None:
        return None
    level = max(1, int(dragon_level))
    hp = 150 + 5 * level
    gold_reward = 200 + 20 * level
    return Army(
        hp=hp,
        max_hp=hp,
        atk=50 + 5 * level,
        dfn=80 + 5 * level,
        movement_speed=10,
        position=spawn,
        kind=ArmyKind.GOLDEN_CARAVAN,
        victory_gold=gold_reward,
        source_coord=spawn,
        march_goal=goal,
    )


def apply_world_event(
    event_id: str,
    *,
    dragon: Dragon,
    game_map: GameMap,
    settlements: Iterable[Settlement],
    day_state: WorldEventDayState,
    citadel_hp: int,
    max_citadel_hp: int,
    fog: FogOfWarState | None = None,
    rng: random.Random | None = None,
) -> tuple[int, list[Army], tuple[str, ...]]:
    """Apply one event's effects. Returns ``(citadel_hp, spawned_armies, extra_msgs)``."""

    rng = rng or random.Random()
    spawned: list[Army] = []
    extra: list[str] = []
    day_state.active_event_id = event_id

    if event_id == "raider_army":
        army = spawn_raider_army(game_map, dragon_level=dragon.level, rng=rng)
        if army is not None:
            spawned.append(army)
            extra.append("A Raider Army appears on the map edge!")
        return citadel_hp, spawned, tuple(extra)

    if event_id == "storm_winds":
        add_modifier(
            dragon.stat_modifiers,
            _day_end_mult("storm_winds", StatKey.SPEED, 0.5),
        )
        return citadel_hp, spawned, tuple(extra)

    if event_id == "town_militia":
        for settlement in settlements:
            add_modifier(
                settlement.stat_modifiers,
                _day_end_mult("town_militia_atk", StatKey.ATK, 1.1),
            )
            add_modifier(
                settlement.stat_modifiers,
                _day_end_mult("town_militia_dfn", StatKey.DFN, 1.1),
            )
        return citadel_hp, spawned, tuple(extra)

    if event_id == "settlement_investments":
        day_state.double_settlement_growth = True
        day_state.double_settlement_healing = True
        return citadel_hp, spawned, tuple(extra)

    if event_id == "snowfall":
        day_state.rivers_passable_for_armies = True
        return citadel_hp, spawned, tuple(extra)

    if event_id == "heatwave":
        add_modifier(
            dragon.stat_modifiers,
            _day_end_mult("heatwave", StatKey.ATK, 1.15),
        )
        return citadel_hp, spawned, tuple(extra)

    if event_id == "heavy_rain":
        add_modifier(
            dragon.stat_modifiers,
            _day_end_mult("heavy_rain", StatKey.ATK, 0.85),
        )
        day_state.heavy_rain_eco_growth_mult = 1.5
        return citadel_hp, spawned, tuple(extra)

    if event_id == "arcane_fog":
        if fog is not None:
            from .fog_of_war import init_fog_from_dragon

            init_fog_from_dragon(fog, dragon, game_map)
        return citadel_hp, spawned, tuple(extra)

    if event_id == "citadel_vigor":
        if citadel_hp < max_citadel_hp:
            citadel_hp = min(max_citadel_hp, citadel_hp + 1)
            extra.append("The citadel's ancient magic restores 1 HP.")
        return citadel_hp, spawned, tuple(extra)

    if event_id == "golden_caravan":
        army = spawn_golden_caravan(game_map, dragon_level=dragon.level, rng=rng)
        if army is not None:
            spawned.append(army)
            extra.append("A Golden Caravan crosses the realm!")
        return citadel_hp, spawned, tuple(extra)

    if event_id == "earthquake":
        for settlement in settlements:
            if settlement.hp <= 0:
                continue
            loss = max(1, int(settlement.hp) * 10 // 100)
            settlement.hp = max(0, int(settlement.hp) - loss)
            day_state.growth_delayed_coords.add(settlement.position)
        extra.append("The earthquake damages settlements across the land.")
        return citadel_hp, spawned, tuple(extra)

    if event_id == "dark_eclipse":
        add_modifier(
            dragon.stat_modifiers,
            _day_end_mult("dark_eclipse", StatKey.FLIGHT_RANGE, 0.5),
        )
        day_state.dark_eclipse = True
        return citadel_hp, spawned, tuple(extra)

    return citadel_hp, spawned, tuple(extra)


def army_movement_context(day_state: WorldEventDayState | None) -> ArmyMovementContext | None:
    if day_state is None or not day_state.rivers_passable_for_armies:
        return None
    return ArmyMovementContext(rivers_passable=True, forbid_stop_on_river=True)


def army_speed_multiplier_for_day(day_state: WorldEventDayState | None) -> float:
    if day_state is None or day_state.active_event_id is None:
        return 1.0
    if day_state.active_event_id == "snowfall":
        return 0.5
    if day_state.active_event_id == "earthquake":
        return 0.75
    return 1.0


def apply_army_day_speed_modifiers(armies: Iterable[Army], day_state: WorldEventDayState | None) -> None:
    """Attach day-scoped speed penalties to active armies when events demand it."""

    if day_state is None or day_state.active_event_id is None:
        return
    mult = army_speed_multiplier_for_day(day_state)
    if mult >= 1.0:
        return
    for army in armies:
        add_modifier(
            army.stat_modifiers,
            StatModifier(
                stat=StatKey.SPEED,
                kind=ModifierKind.PERCENT_MULT,
                value=mult,
                expiry=ModifierExpiry.DAY_END,
                source=f"{WORLD_EVENT_SOURCE_PREFIX}{day_state.active_event_id}:speed",
            ),
        )


def army_effective_movement_speed(army: Army) -> int:
    from .entity_stats import StatLine, effective_statline_from_base

    synthetic = StatLine(
        max_hp=int(army.max_hp),
        atk=int(army.atk),
        dfn=int(army.dfn),
        flight_range=0,
        speed=float(army.movement_speed),
    )
    effective = effective_statline_from_base(synthetic, army.stat_modifiers)
    return max(1, int(math.floor(effective.speed)))


def roll_world_event(
    chance_percent: int,
    rng: random.Random,
) -> WorldEventRollResult:
    """Roll whether a world event fires; if so, pick one uniformly."""

    chance = max(0, min(100, int(chance_percent)))
    if rng.randint(1, 100) > chance:
        return WorldEventRollResult(triggered=False)
    spec = rng.choice(WORLD_EVENTS)
    return WorldEventRollResult(
        triggered=True,
        event_id=spec.event_id,
        description=spec.description,
    )


def settlement_phase_world_event_hooks(day_state: WorldEventDayState | None) -> tuple[bool, bool, float]:
    """Return ``(double_growth, double_heal, eco_growth_mult)`` for settlement phase."""

    if day_state is None or day_state.active_event_id is None:
        return False, False, 1.0
    return (
        day_state.double_settlement_growth,
        day_state.double_settlement_healing,
        day_state.heavy_rain_eco_growth_mult,
    )


def settlement_growth_is_delayed(day_state: WorldEventDayState | None, coord: OffsetCoord) -> bool:
    if day_state is None:
        return False
    return coord in day_state.growth_delayed_coords


def on_golden_caravan_defeated(
    day_state: WorldEventDayState,
    game_map: GameMap,
    *,
    dragon_level: int,
    rng: random.Random,
) -> Army | None:
    """Spawn a revenge Raider Army after the caravan is destroyed."""

    day_state.pending_revenge_raider = True
    return spawn_raider_army(game_map, dragon_level=dragon_level, rng=rng)


def storm_winds_speed_ceiling(raw_speed: float, dragon: Dragon) -> float:
    """Apply storm-winds rounding: ceil halved speed when that event is active."""

    for mod in dragon.stat_modifiers.modifiers:
        if mod.source == f"{WORLD_EVENT_SOURCE_PREFIX}storm_winds" and mod.stat is StatKey.SPEED:
            return max(0.001, float(math.ceil(raw_speed)))
    return raw_speed


__all__ = [
    "DEFAULT_WORLD_EVENT_CHANCE_PERCENT",
    "WORLD_EVENTS",
    "ArmyMovementContext",
    "WorldEventDayState",
    "WorldEventRollResult",
    "WorldEventSpec",
    "apply_army_day_speed_modifiers",
    "apply_world_event",
    "army_effective_movement_speed",
    "army_movement_context",
    "on_golden_caravan_defeated",
    "roll_world_event",
    "settlement_growth_is_delayed",
    "settlement_phase_world_event_hooks",
    "spawn_golden_caravan",
    "spawn_raider_army",
    "storm_winds_speed_ceiling",
    "world_event_by_id",
]
