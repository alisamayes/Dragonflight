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
    DRAGON_CITADEL_END_OF_DAY_BONUS_HEAL_PERCENT_OF_MAX_PER_HOUR_REMAINING,
    HOURS_PER_DAMAGE_ROUND,
    HOURS_PER_DRAGON_DAY,
)
from .hex_coord import OffsetCoord, distance, offset_to_axial
from .terrain import Terrain

if TYPE_CHECKING:
    from .game_tuning import GameTuning
    from .map_state import GameMap


class DragonKind(Enum):
    """Playable dragon archetypes (spec §7 + ``Documentation/dragon_types.md``)."""

    RED_FIRE = "red_fire"
    BLACK_TANK = "black_tank"
    GREEN_LIFE = "green_life"
    YELLOW_CHRONO = "yellow_chrono"
    PURPLE_FROST = "purple_frost"
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
    """Mutable runtime state for the single player dragon (spec §7).

    :attr:`hp` is **current** hit points; :attr:`max_hp` is the pool ceiling. They start
    equal; combat reduces ``hp`` only unless a future system raises ``max_hp``.
    :attr:`current_hp` is a convenience alias for ``hp`` (clamped when set).
    """

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
    gold: int = 0
    hp_upgrades: int = 0
    atk_upgrades: int = 0
    dfn_upgrades: int = 0
    flight_range_upgrades: int = 0
    speed_upgrades: int = 0
    _activatable_uses_remaining_today: tuple[int, int] = field(default=(1, 1))
    unlocked_ability_names: tuple[str, ...] = field(default_factory=tuple)
    ability_cooldowns: dict[str, int] = field(default_factory=dict)
    ability_extra_charges_today: dict[str, int] = field(default_factory=dict)
    active_ability_hours: dict[str, float] = field(default_factory=dict)
    passive_stacks: dict[str, int] = field(default_factory=dict)
    marked_ability_tiles: dict[str, tuple[OffsetCoord, ...]] = field(default_factory=dict)

    @property
    def current_hp(self) -> int:
        """Current hit points; mirrors :attr:`hp`."""
        return self.hp

    @current_hp.setter
    def current_hp(self, value: int) -> None:
        self.hp = max(0, min(int(value), self.max_hp))

    @classmethod
    def new_red_fire_at(cls, citadel_coord: OffsetCoord) -> Dragon:
        """Factory for the Redgon (red fire) dragon at the citadel (see ``dragon_playables``)."""
        from .dragon_playables import Redgon

        return Redgon.new_at(citadel_coord)

    def begin_new_day_at_citadel(
        self,
        citadel_coord: OffsetCoord,
        *,
        tuning: GameTuning | None = None,
    ) -> None:
        """Phase boundary: citadel rest heal, then reset daily hours (spec §2 Citadel → next day).

        Healing uses hours still on the clock **before** the reset: base percent of ``max_hp``
        (from tuning or defaults) plus bonus percent per hour remaining (see
        :mod:`dragonflight.dragon_defaults`).
        """
        from .dragon_abilities import begin_new_turn, synchronize_unlocked_abilities

        synchronize_unlocked_abilities(self)
        self._apply_citadel_end_of_day_healing(tuning=tuning)
        self.position = citadel_coord
        self.hours_remaining = HOURS_PER_DRAGON_DAY
        self._activatable_uses_remaining_today = (1, 1)
        begin_new_turn(self)

    def _citadel_end_of_day_heal_points(
        self,
        *,
        tuning: GameTuning | None = None,
    ) -> int:
        """Integer HP restored this dock from ``max_hp`` and :attr:`hours_remaining`."""

        from .game_tuning import resolve_tuning

        t = resolve_tuning(tuning)
        hrs = max(0.0, float(self.hours_remaining))
        total_percent = (
            float(t.dragon_citadel_end_of_day_base_heal_percent_of_max)
            + float(DRAGON_CITADEL_END_OF_DAY_BONUS_HEAL_PERCENT_OF_MAX_PER_HOUR_REMAINING) * hrs
        )
        return int(round(self.max_hp * total_percent / 100.0))

    def _apply_citadel_end_of_day_healing(
        self,
        *,
        tuning: GameTuning | None = None,
    ) -> None:
        gained = self._citadel_end_of_day_heal_points(tuning=tuning)
        self.hp = min(self.max_hp, self.hp + gained)

    def hex_distance_to(self, target: OffsetCoord) -> int:
        """Straight-line axial distance ignoring terrain — valid for dragon flight (spec §5)."""
        return distance(offset_to_axial(self.position), offset_to_axial(target))

    def _travel_hours_for_hex_distance(self, hex_distance: int) -> float:
        """Hours spent flying ``hex_distance`` hexes at the dragon's cruising speed."""
        if hex_distance <= 0:
            return 0.0
        from .dragon_abilities import effective_speed_hexes_per_hour

        return hex_distance / effective_speed_hexes_per_hour(self)

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

    def validate_damage_round_preserves_return_to_citadel(
        self,
        citadel_coord: OffsetCoord,
    ) -> MoveAttempt:
        """Return whether one combat round can be committed without trapping the dragon off-home.

        Mirrors the mandatory-return budget used by :meth:`validate_move`: after spending
        :data:`~dragonflight.dragon_defaults.HOURS_PER_DAMAGE_ROUND`, the dragon must still
        have enough clock to fly from :attr:`position` back to ``citadel_coord`` at
        :attr:`speed_hexes_per_hour`.
        """
        if self.hours_remaining + 1e-9 < HOURS_PER_DAMAGE_ROUND:
            return MoveAttempt(ok=False, reason="not enough daily time for a damage round")

        hours_after_round = self.hours_remaining - HOURS_PER_DAMAGE_ROUND
        dist_home = distance(
            offset_to_axial(self.position),
            offset_to_axial(citadel_coord),
        )
        hours_back = self._travel_hours_for_hex_distance(dist_home)
        if hours_after_round + 1e-9 < hours_back:
            return MoveAttempt(
                ok=False,
                reason=(
                    "cannot attack: not enough hours left to finish a combat round and "
                    "return to the citadel before nightfall"
                ),
            )
        return MoveAttempt(ok=True, reason="", hex_distance=dist_home, hours_spent=0.0)

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

        from .dragon_abilities import effective_flight_range

        if dist > effective_flight_range(self):
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
        from .dragon_abilities import apply_time_spent

        apply_time_spent(self, hours)
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

        from .dragon_abilities import (
            apply_time_spent,
            effective_attack,
            effective_defence,
            enemy_can_retaliate,
            mitigated_damage_taken,
            thorns_damage,
            vivify_attack_bonus,
        )

        dragon_to_target = damage_dragon_attacks(
            effective_attack(self) + vivify_attack_bonus(self),
            target_dfn,
        )
        raw_target_to_dragon = (
            damage_human_or_army_attacks(target_atk, effective_defence(self))
            if enemy_can_retaliate(self)
            else 0
        )
        target_to_dragon = mitigated_damage_taken(self, raw_target_to_dragon)
        dragon_to_target += thorns_damage(self, raw_target_to_dragon)

        next_target_hp = max(0, target_hp - dragon_to_target)
        next_dragon_hp = max(0, self.hp - target_to_dragon)

        self.hours_remaining -= HOURS_PER_DAMAGE_ROUND
        apply_time_spent(self, HOURS_PER_DAMAGE_ROUND)
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
        """Resolve one damage round vs an army using the same rules as settlement combat.

        Pass ``army_dfn`` after tile modifiers (e.g. Tremors) at the resolver boundary.
        """

        from .dragon_abilities import (
            effective_attack,
            outgoing_combat_damage_multiplier,
            vivify_attack_bonus,
        )

        base_attack = effective_attack(self, world=world) + vivify_attack_bonus(self)
        boosted_attack = max(
            1, int(round(base_attack * outgoing_combat_damage_multiplier(self)))
        )
        if self.hours_remaining + 1e-9 < HOURS_PER_DAMAGE_ROUND:
            return MoveAttempt(ok=False, reason="not enough daily time for a damage round")
        dragon_to_target = damage_dragon_attacks(boosted_attack, army_dfn)
        from .dragon_abilities import (
            apply_time_spent,
            effective_defence,
            enemy_can_retaliate,
            mitigated_damage_taken,
            thorns_damage,
        )

        raw_target_to_dragon = (
            damage_human_or_army_attacks(army_atk, effective_defence(self))
            if enemy_can_retaliate(self)
            else 0
        )
        target_to_dragon = mitigated_damage_taken(self, raw_target_to_dragon)
        next_target_hp = max(
            0, army_hp - dragon_to_target - thorns_damage(self, raw_target_to_dragon)
        )
        next_dragon_hp = max(0, self.hp - target_to_dragon)
        self.hours_remaining -= HOURS_PER_DAMAGE_ROUND
        apply_time_spent(self, HOURS_PER_DAMAGE_ROUND)
        self.hp = next_dragon_hp
        return DamageRoundExchange(
            dragon_hp_after=self.hp,
            target_hp_after=next_target_hp,
            damage_to_target=army_hp - next_target_hp,
            damage_to_dragon=target_to_dragon,
            hours_spent=HOURS_PER_DAMAGE_ROUND,
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
        from .dragon_abilities import (
            effective_attack,
            outgoing_combat_damage_multiplier,
            vivify_attack_bonus,
        )

        base_attack = effective_attack(self, world=world) + vivify_attack_bonus(self)
        boosted_attack = max(
            1, int(round(base_attack * outgoing_combat_damage_multiplier(self)))
        )
        if self.hours_remaining + 1e-9 < HOURS_PER_DAMAGE_ROUND:
            return MoveAttempt(ok=False, reason="not enough daily time for a damage round")
        dragon_to_target = damage_dragon_attacks(boosted_attack, settlement_dfn)
        from .dragon_abilities import (
            apply_time_spent,
            effective_defence,
            enemy_can_retaliate,
            mitigated_damage_taken,
            thorns_damage,
        )

        raw_target_to_dragon = (
            damage_human_or_army_attacks(settlement_defence_atk_proxy, effective_defence(self))
            if enemy_can_retaliate(self)
            else 0
        )
        target_to_dragon = mitigated_damage_taken(self, raw_target_to_dragon)
        next_target_hp = max(
            0, settlement_hp - dragon_to_target - thorns_damage(self, raw_target_to_dragon)
        )
        next_dragon_hp = max(0, self.hp - target_to_dragon)
        self.hours_remaining -= HOURS_PER_DAMAGE_ROUND
        apply_time_spent(self, HOURS_PER_DAMAGE_ROUND)
        self.hp = next_dragon_hp
        return DamageRoundExchange(
            dragon_hp_after=self.hp,
            target_hp_after=next_target_hp,
            damage_to_target=settlement_hp - next_target_hp,
            damage_to_dragon=target_to_dragon,
            hours_spent=HOURS_PER_DAMAGE_ROUND,
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

        # Combat rounds, aggression spillover, loot scaling, eco/power hits — spec §§6-8, §11 — TBD.
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
        from .dragon_abilities import synchronize_unlocked_abilities

        synchronize_unlocked_abilities(self)

    def grant_experience(self, amount: int) -> None:
        """Accumulate XP without automatic levelling until progression rules exist."""
        self.experience_points += max(0, amount)

    def spend_gold_stat_upgrade(self, stat_name: str, gold_cost: int) -> bool:
        """Buy one stat tier at the current level (no draft sequencing across stats).

        ``gold_cost`` must match the computed price for the next tier of ``stat_name``.
        """
        from .dragon_progression import (
            apply_one_dragon_stat_upgrade,
            dragon_stat_upgrade_gold_cost,
            dragon_stat_upgrade_lifetime_count,
            dragon_upgrade_baseline_from_dragon,
            parse_dragon_upgrade_stat_name,
        )

        stat = parse_dragon_upgrade_stat_name(stat_name)
        if stat is None:
            return False
        baseline = dragon_upgrade_baseline_from_dragon(self)
        n = dragon_stat_upgrade_lifetime_count(baseline, stat) + 1
        expected = dragon_stat_upgrade_gold_cost(int(self.level), n)
        if gold_cost != expected or self.gold < expected:
            return False
        self.gold -= expected
        apply_one_dragon_stat_upgrade(self, stat)
        self.level += 1
        from .dragon_abilities import synchronize_unlocked_abilities

        synchronize_unlocked_abilities(self)
        return True

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
        """Compatibility wrapper returning count of currently unlocked passives."""

        from .dragon_abilities import unlocked_ability_specs

        return sum(1 for spec in unlocked_ability_specs(self) if spec.category == "passive")

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
