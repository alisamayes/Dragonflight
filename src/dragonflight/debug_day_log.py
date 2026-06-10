"""Per-day debug trace for playtest / simulation diagnostics.

Simulation code appends lines via :class:`DayDebugLog` helpers; the play session
debug overlay reads formatted lines through :meth:`DayDebugLog.format_for_display`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .hex_coord import OffsetCoord

if TYPE_CHECKING:
    from .army import Army, ArmyKind, ArmyPhaseResult
    from .settlement import Settlement, SettlementPhaseOutcome, SettlementType
    from .world_events import WorldEventRollResult


@dataclass
class DayDebugRecord:
    """Human-readable debug lines for one in-game day."""

    day: int
    entries: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SettlementPhaseBefore:
    """Settlement stats immediately before an end-of-phase tick."""

    eco: int
    atk: int
    dfn: int
    hp: int


@dataclass(frozen=True, slots=True)
class ArmyBeforeSnapshot:
    """Army identity and position before the army phase."""

    index: int
    kind: object
    position: OffsetCoord
    object_id: int


def _format_coord(coord: OffsetCoord) -> str:
    return f"({coord.col},{coord.row})"


def _settlement_type_label(settlement_type: SettlementType) -> str:
    from .settlement import SettlementType

    if settlement_type is SettlementType.VILLAGE:
        return "Village"
    if settlement_type is SettlementType.CITY:
        return "City"
    return "Fort"


def settlement_labels_by_coord(
    settlements_by_coord: dict[OffsetCoord, Settlement],
) -> dict[OffsetCoord, str]:
    """Label settlements as ``Village/City/Fort N`` by sorted index within type."""

    from .settlement import SettlementType

    labels: dict[OffsetCoord, str] = {}
    for settlement_type in (SettlementType.VILLAGE, SettlementType.CITY, SettlementType.FORT):
        type_name = _settlement_type_label(settlement_type)
        coords = sorted(
            (
                coord
                for coord, ent in settlements_by_coord.items()
                if ent.settlement_type is settlement_type
            ),
            key=lambda c: (c.row, c.col),
        )
        for index, coord in enumerate(coords, start=1):
            labels[coord] = f"{type_name} {index}"
    return labels


def snapshot_armies_before_phase(armies: list[Army]) -> list[ArmyBeforeSnapshot]:
    """Capture army index, kind, and position before ``run_army_phase``."""

    snapshots: list[ArmyBeforeSnapshot] = []
    for index, army in enumerate(armies):
        if army.is_defeated():
            continue
        snapshots.append(
            ArmyBeforeSnapshot(
                index=index,
                kind=army.kind,
                position=army.position,
                object_id=id(army),
            )
        )
    return snapshots


class DayDebugLog:
    """Append-only debug lines keyed by in-game day."""

    def __init__(self) -> None:
        self._records: dict[int, DayDebugRecord] = {}
        self._current_day: int | None = None

    def clear(self) -> None:
        self._records.clear()
        self._current_day = None

    def start_day(self, day: int) -> None:
        """Begin recording entries for ``day``."""

        self._current_day = day
        if day not in self._records:
            self._records[day] = DayDebugRecord(day=day)

    def add_entry(self, line: str) -> None:
        """Append one human-readable line to the current day."""

        if self._current_day is None:
            return
        self._records[self._current_day].entries.append(line)

    def get_day(self, day: int) -> DayDebugRecord | None:
        return self._records.get(day)

    def days(self) -> list[int]:
        return sorted(self._records)

    def format_for_display(self, day: int) -> list[str]:
        record = self.get_day(day)
        return list(record.entries) if record is not None else []

    def latest_day(self) -> int | None:
        days = self.days()
        return days[-1] if days else None

    def lines_for_day(self, day: int) -> list[str]:
        """Backward-compatible alias for :meth:`format_for_display`."""

        return self.format_for_display(day)


def log_world_event_roll(
    log: DayDebugLog,
    chance_percent: int,
    result: WorldEventRollResult,
) -> None:
    """Record the daily world-event roll and outcome."""

    if result.triggered and result.event_id:
        log.add_entry(
            f"World event roll: {chance_percent}% -> {result.event_id}",
        )
    else:
        log.add_entry(f"World event roll: {chance_percent}% -> no world event")


def log_world_event_effects(log: DayDebugLog, messages: Iterable[str]) -> None:
    for message in messages:
        log.add_entry(f"World event effect: {message}")


def log_dragon_end_of_day_heal(
    log: DayDebugLog,
    hp_before: int,
    hp_after: int,
) -> None:
    gained = hp_after - hp_before
    if gained > 0:
        log.add_entry(f"Dragon heal: HP {hp_before} -> {hp_after} (+{gained})")


def _army_kind_label(kind: ArmyKind | object) -> str:
    return str(getattr(kind, "value", kind))


def log_heroes_party_spawn(log: DayDebugLog, armies: list[Army]) -> None:
    if not armies:
        return
    for index, army in enumerate(armies):
        log.add_entry(
            f"Hero's Party spawned: army #{index} ({_army_kind_label(army.kind)}) at "
            f"{_format_coord(army.position)}",
        )


def log_citadel_hp_change(
    log: DayDebugLog,
    hp_before: int,
    hp_after: int,
    *,
    reason: str,
) -> None:
    if hp_before == hp_after:
        return
    log.add_entry(f"Citadel HP ({reason}): {hp_before} -> {hp_after}")


def log_settlement_phase(
    log: DayDebugLog,
    settlements_by_coord: dict[OffsetCoord, Settlement],
    outcomes: dict[OffsetCoord, tuple[SettlementPhaseBefore, SettlementPhaseOutcome, bool]],
) -> None:
    """Log per-settlement growth, heal, delay, or no-change from phase outcomes."""

    labels = settlement_labels_by_coord(settlements_by_coord)
    for coord in sorted(outcomes, key=lambda c: (c.row, c.col)):
        before, outcome, growth_delayed = outcomes[coord]
        ent = settlements_by_coord[coord]
        label = labels.get(coord, _settlement_type_label(ent.settlement_type))
        at = f"{label} {_format_coord(coord)}"

        if growth_delayed:
            log.add_entry(f"{at}: growth delayed")
            continue

        if outcome.action == "grew":
            eco_after = before.eco + outcome.eco_delta
            atk_after = before.atk + outcome.atk_delta
            dfn_after = before.dfn + outcome.dfn_delta
            log.add_entry(
                f"{at}: grow eco/atk/dfn "
                f"{before.eco}/{before.atk}/{before.dfn} -> "
                f"{eco_after}/{atk_after}/{dfn_after}",
            )
        elif outcome.action == "healed":
            hp_after = before.hp + outcome.hp_delta
            log.add_entry(f"{at}: heal HP {before.hp} -> {hp_after}")
        else:
            log.add_entry(f"{at}: no change")


def log_army_phase(
    log: DayDebugLog,
    armies_before: list[ArmyBeforeSnapshot],
    armies_in_place: list[Army],
    phase_result: ArmyPhaseResult,
    *,
    citadel_coord: OffsetCoord,
) -> None:
    """Log army movement, merges, and citadel attacks from one army phase."""

    by_id = {id(army): army for army in armies_in_place}
    for snap in armies_before:
        army = by_id.get(snap.object_id)
        if army is None:
            continue
        if army.position == citadel_coord and snap.position != citadel_coord:
            start = _format_coord(snap.position)
            end = _format_coord(citadel_coord)
            label = _army_kind_label(snap.kind)
            log.add_entry(
                f"Army #{snap.index} ({label}): {start} -> {end} (citadel attack)",
            )
        elif army.position != snap.position:
            log.add_entry(
                f"Army #{snap.index} ({_army_kind_label(snap.kind)}): "
                f"{_format_coord(snap.position)} -> {_format_coord(army.position)}",
            )
        else:
            log.add_entry(
                f"Army #{snap.index} ({_army_kind_label(snap.kind)}): "
                f"held at {_format_coord(snap.position)}",
            )

    if phase_result.merged_stacks > 0:
        log.add_entry(f"Army merge: {phase_result.merged_stacks} stack(s) combined")

    if phase_result.citadel_attacks > 0:
        log.add_entry(
            f"Citadel attacks: {phase_result.citadel_attacks} (HP -> {phase_result.citadel_hp})",
        )
