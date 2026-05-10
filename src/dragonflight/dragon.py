"""Player dragon entity — stats, scaffolding actions, time budget guards (spec §§2, 7, 8).

Slice 2 focuses on structure: map loading/rendering stays elsewhere; richer combat
loops, raids, aggression, citadel docking, and gold upgrades wire in behind the
stub methods marked explicitly as placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .combat_math import damage_dragon_attacks, damage_human_or_army_attacks
from .dragon_defaults import (
    DEFAULT_DRAGON_ATK,
    DEFAULT_DRAGON_DFN,
    DEFAULT_DRAGON_FLIGHT_RANGE_HEXES,
    DEFAULT_DRAGON_LEVEL,
    DEFAULT_DRAGON_MAX_HP,
    DEFAULT_DRAGON_SPEED_HEXES_PER_HOUR,
    HOURS_PER_DAMAGE_ROUND,
    HOURS_PER_DRAGON_DAY,
)
from .hex_coord import OffsetCoord, distance, offset_to_axial
from .terrain import Terrain

if TYPE_CHECKING:
    from .map_state import GameMap


class DragonKind(Enum):
    """Playable dragon archetypes (spec §7). MVP builds only exercise ``RED_FIRE``."""

    RED_FIRE = "red_fire"
    BLACK_TANK = "black_tank"
    YELLOW_CHRONO = "yellow_chrono"
    BROWN_EARTH = "brown_earth"


@dataclass(frozen=True, slots=True)
class MoveAttempt:
    """Structured outcome for a movement request at the simulation boundary."""

    ok: bool
    reason: str
    hex_distance: int = 0
    hours_spent: float = 0.0


@dataclass(frozen=True, slots=True)
class DamageRoundExchange:
    """One automatic damage round (spec §8) without embedding full target types yet."""

    dragon_hp_after: int
    target_hp_after: int
    damage_to_target: int
    damage_to_dragon: int
    hours_spent: float


@dataclass(frozen=True, slots=True)
class RaidAttempt:
    """Placeholder carrier for raid results until economy + settlement sim exist."""

    ok: bool
    reason: str
    gold_gained: int = 0
    hours_spent: float = 0.0


@dataclass
class Dragon:
    """Mutable runtime state for the single player dragon (spec §7)."""

    kind: DragonKind
    position: OffsetCoord
    level: int = DEFAULT_DRAGON_LEVEL
    hp: int = DEFAULT_DRAGON_MAX_HP
    max_hp: int = DEFAULT_DRAGON_MAX_HP
    atk: int = DEFAULT_DRAGON_ATK
    dfn: int = DEFAULT_DRAGON_DFN
    flight_range_hexes: int = DEFAULT_DRAGON_FLIGHT_RANGE_HEXES
    speed_hexes_per_hour: float = DEFAULT_DRAGON_SPEED_HEXES_PER_HOUR
    hours_remaining: float = HOURS_PER_DRAGON_DAY
    experience_points: int = 0
    _activatable_uses_remaining_today: tuple[int, int] = field(default=(1, 1))

    @classmethod
    def new_red_fire_at(cls, citadel_coord: OffsetCoord) -> Dragon:
        """Factory for the MVP Red Fire Dragon sitting on the citadel at day start."""
        return cls(
            kind=DragonKind.RED_FIRE,
            position=citadel_coord,
            level=DEFAULT_DRAGON_LEVEL,
            hp=DEFAULT_DRAGON_MAX_HP,
            max_hp=DEFAULT_DRAGON_MAX_HP,
            atk=DEFAULT_DRAGON_ATK,
            dfn=DEFAULT_DRAGON_DFN,
            flight_range_hexes=DEFAULT_DRAGON_FLIGHT_RANGE_HEXES,
            speed_hexes_per_hour=DEFAULT_DRAGON_SPEED_HEXES_PER_HOUR,
            hours_remaining=HOURS_PER_DRAGON_DAY,
        )

    def begin_new_day_at_citadel(self, citadel_coord: OffsetCoord) -> None:
        """Phase boundary helper: reset daily hours and teleport home (spec §2 phase 5 → 1).

        Combat-time healing at the citadel (50 % max HP) belongs to the citadel phase;
        invoke that orchestration when that system exists — not here.
        """
        self.position = citadel_coord
        self.hours_remaining = HOURS_PER_DRAGON_DAY
        self._activatable_uses_remaining_today = (1, 1)

    def hex_distance_to(self, target: OffsetCoord) -> int:
        """Straight-line axial distance ignoring terrain — valid for dragon flight (spec §5)."""
        return distance(offset_to_axial(self.position), offset_to_axial(target))

    def _travel_hours_for_hex_distance(self, hex_distance: int) -> float:
        """Hours spent flying ``hex_distance`` hexes at the dragon's cruising speed."""
        if hex_distance <= 0:
            return 0.0
        return hex_distance / self.speed_hexes_per_hour

    def _can_commit_round_trip_budget(
        self,
        *,
        outbound_hexes: int,
        interim_return_hexes: int,
    ) -> tuple[bool, str]:
        """Return whether movement plus return to interim anchor fits the daily clock.

        The player must preserve enough slack to fly back home before nightfall
        (spec §2). Skeleton uses instantaneous return distance from proposed tile
        to ``citadel_coord`` supplied by callers.
        """
        hours_out = self._travel_hours_for_hex_distance(outbound_hexes)
        hours_back = self._travel_hours_for_hex_distance(interim_return_hexes)
        total = hours_out + hours_back
        if total > self.hours_remaining + 1e-9:
            return (
                False,
                "insufficient hours remaining for flight plus mandatory return trajectory",
            )
        return True, ""

    # -- Movement -----------------------------------------------------------------

    def validate_move(
        self,
        destination: OffsetCoord,
        world: GameMap,
        citadel_coord: OffsetCoord,
    ) -> MoveAttempt:
        """Run the same checks as :meth:`move` without mutating state (UI / previews).

        On success, :attr:`hex_distance` is populated; :attr:`hours_spent` is ``0.0``
        because no hours are consumed until :meth:`move` commits the action.
        """
        tile = world.get(destination)
        if tile is None:
            return MoveAttempt(ok=False, reason="destination not on loaded map")

        dist = self.hex_distance_to(destination)
        if dist == 0:
            return MoveAttempt(ok=False, reason="already at destination")

        if dist > self.flight_range_hexes:
            return MoveAttempt(ok=False, reason="destination exceeds flight range")

        distance_home_from_dest = distance(
            offset_to_axial(destination),
            offset_to_axial(citadel_coord),
        )
        feasible, feasibility_reason = self._can_commit_round_trip_budget(
            outbound_hexes=dist,
            interim_return_hexes=distance_home_from_dest,
        )
        if not feasible:
            return MoveAttempt(ok=False, reason=feasibility_reason)

        return MoveAttempt(ok=True, reason="", hex_distance=dist, hours_spent=0.0)

    def move(
        self,
        destination: OffsetCoord,
        world: GameMap,
        citadel_coord: OffsetCoord,
    ) -> MoveAttempt:
        """Attempt a single reposition ignoring terrain impediments.

        Validation only checks map bounds, flight-range cap, mandatory return
        time to ``citadel_coord``, and leftover daily hours. Routing across the
        grid is deliberately absent until pathfinding consumes this API.
        """
        preview = self.validate_move(destination, world, citadel_coord)
        if not preview.ok:
            return preview

        dist = preview.hex_distance
        hours = self._travel_hours_for_hex_distance(dist)
        self.position = destination
        self.hours_remaining -= hours
        return MoveAttempt(ok=True, reason="", hex_distance=dist, hours_spent=hours)

    # -- Combat scaffolding -------------------------------------------------------

    def attack_round_vs_target(
        self,
        *,
        target_hp: int,
        target_atk: int,
        target_dfn: int,
    ) -> DamageRoundExchange | MoveAttempt:
        """Resolve exactly one mirrored damage exchange, charging time if valid.

        Returns :class:`MoveAttempt` failure when half an hour budget is unavailable.
        """
        if self.hours_remaining + 1e-9 < HOURS_PER_DAMAGE_ROUND:
            return MoveAttempt(ok=False, reason="not enough daily time for a damage round")

        dragon_to_target = damage_dragon_attacks(self.atk, target_dfn)
        target_to_dragon = damage_human_or_army_attacks(target_atk, self.dfn)

        next_target_hp = max(0, target_hp - dragon_to_target)
        next_dragon_hp = max(0, self.hp - target_to_dragon)

        self.hours_remaining -= HOURS_PER_DAMAGE_ROUND
        self.hp = next_dragon_hp

        return DamageRoundExchange(
            dragon_hp_after=self.hp,
            target_hp_after=next_target_hp,
            damage_to_target=dragon_to_target,
            damage_to_dragon=target_to_dragon,
            hours_spent=HOURS_PER_DAMAGE_ROUND,
        )

    def attack_army(
        self,
        *,
        army_hp: int,
        army_atk: int,
        army_dfn: int,
        world: GameMap,
    ) -> DamageRoundExchange | MoveAttempt:
        """Convenience wrapper for army engagements (spec §8 Army Combat).

        Map parameter reserved for forthcoming range/line-of-flight checks —
        intentionally unused beyond signature stability for upcoming systems.
        """
        del world  # Future: choke points, retaliation triggers, morale hooks.
        return self.attack_round_vs_target(
            target_hp=army_hp,
            target_atk=army_atk,
            target_dfn=army_dfn,
        )

    def attack_settlement(
        self,
        *,
        settlement_hp: int,
        settlement_defence_atk_proxy: int,
        settlement_dfn: int,
        world: GameMap,
    ) -> DamageRoundExchange | MoveAttempt:
        """Thin wrapper distinguishing settlement combat while numbers stay symmetrical.

        ``settlement_defence_atk_proxy`` stands in until settlement objects expose combat stats.
        """
        del world
        return self.attack_round_vs_target(
            target_hp=settlement_hp,
            target_atk=settlement_defence_atk_proxy,
            target_dfn=settlement_dfn,
        )

    # -- Raiding / economy placeholders -------------------------------------------

    def raid_settlement_tile(
        self,
        settlement_coord: OffsetCoord,
        world: GameMap,
        citadel_coord: OffsetCoord,
    ) -> RaidAttempt:
        """Placeholder raid — validates settlement terrain and time-to-return only.

        Real rewards, eco/power shredding, aggression spikes, army spawns, and UI
        confirmation land here later (spec §§6, 8, 11).
        """
        tile = world.get(settlement_coord)
        if tile is None:
            return RaidAttempt(ok=False, reason="no tile at coordinate")
        if tile.terrain is not Terrain.SETTLEMENT:
            return RaidAttempt(ok=False, reason="target tile is not a settlement")

        dist_to_target = self.hex_distance_to(settlement_coord)
        if dist_to_target > self.flight_range_hexes:
            return RaidAttempt(ok=False, reason="settlement outside flight range")

        home_return = distance(
            offset_to_axial(settlement_coord),
            offset_to_axial(citadel_coord),
        )
        feasible, feasibility_reason = self._can_commit_round_trip_budget(
            outbound_hexes=dist_to_target,
            interim_return_hexes=home_return,
        )
        if not feasible:
            return RaidAttempt(ok=False, reason=feasibility_reason)

        hours_travel = self._travel_hours_for_hex_distance(dist_to_target)
        self.hours_remaining -= hours_travel
        self.position = settlement_coord

        # Combat rounds, aggression spillover, loot scaling, eco/power hits — spec §§6–8, §11 — TBD.
        return RaidAttempt(
            ok=True,
            reason="travel only; raid combat + payouts not simulated yet",
            gold_gained=0,
            hours_spent=hours_travel,
        )

    # -- Progression / meta placeholders ------------------------------------------

    def level_up(self) -> None:
        """Advance level counters; skill unlock cadence (5/10/15) remains TODO (spec §7)."""
        self.level += 1
        # Future: grant talent points, refresh passive/activatable loadouts per species.

    def grant_experience(self, amount: int) -> None:
        """Accumulate XP without automatic levelling until progression rules exist."""
        self.experience_points += max(0, amount)

    def spend_gold_stat_upgrade(self, stat_name: str, gold_cost: int) -> bool:
        """Placeholder shop hook for citadel spending (spec §7 Progression).

        Returns ``False`` until economy state is injected by the citadel system.
        """
        del stat_name, gold_cost
        return False

    def repair_at_citadel_stub(self, gold_paid: int) -> bool:
        """Placeholder for paid repairs / healing bundles at the citadel (spec §2)."""
        del gold_paid
        return False

    def retreat_from_combat_stub(self, *, attacker_prevents_easy_exit: bool = False) -> MoveAttempt:
        """Placeholder retreat path between damage rounds (spec §8 continuation vs retreat).

        ``attacker_prevents_easy_exit`` is reserved for future zone-control or choke rules.
        """
        del attacker_prevents_easy_exit
        return MoveAttempt(ok=False, reason="retreat flow not simulated yet")

    def use_passive_bonus_stub(self) -> int:
        """Reserved hook for racial passives once ability data exists (spec §7)."""
        return 0

    def consume_activatable_charge_stub(self, slot: int) -> bool:
        """Placeholder for daily-limited dragon actives (spec §7).

        Dragons are slated to expose two charges per day across two activatables.
        """
        if slot not in (0, 1):
            return False
        charges = list(self._activatable_uses_remaining_today)
        if charges[slot] <= 0:
            return False
        charges[slot] -= 1
        self._activatable_uses_remaining_today = (charges[0], charges[1])
        return True
