"""Tests for per-day simulation debug logging."""

from __future__ import annotations

from dragonflight.army import Army, ArmyKind, ArmyPhaseResult
from dragonflight.debug_day_log import (
    DayDebugLog,
    SettlementPhaseBefore,
    log_army_phase,
    log_dragon_end_of_day_heal,
    log_settlement_phase,
    log_world_event_roll,
    settlement_labels_by_coord,
    snapshot_armies_before_phase,
)
from dragonflight.hex_coord import OffsetCoord
from dragonflight.settlement import City, SettlementPhaseOutcome, Village
from dragonflight.world_events import WorldEventRollResult


class TestDayDebugLogStructure:
    def test_start_day_add_entry_and_format(self) -> None:
        log = DayDebugLog()
        log.start_day(2)
        log.add_entry("first line")
        log.add_entry("second line")

        record = log.get_day(2)
        assert record is not None
        assert record.day == 2
        assert record.entries == ["first line", "second line"]
        assert log.format_for_display(2) == ["first line", "second line"]
        assert log.days() == [2]

    def test_clear_resets_all_days(self) -> None:
        log = DayDebugLog()
        log.start_day(1)
        log.add_entry("line")
        log.clear()
        assert log.days() == []
        assert log.get_day(1) is None
        assert log.latest_day() is None

    def test_get_day_missing_returns_none(self) -> None:
        log = DayDebugLog()
        assert log.get_day(99) is None
        assert log.format_for_display(99) == []


class TestDebugLogHelpers:
    def test_world_event_roll_triggered_and_none(self) -> None:
        log = DayDebugLog()
        log.start_day(1)
        log_world_event_roll(
            log,
            50,
            WorldEventRollResult(triggered=True, event_id="storm_winds"),
        )
        log_world_event_roll(log, 50, WorldEventRollResult(triggered=False))
        lines = log.format_for_display(1)
        assert lines[0] == "World event roll: 50% -> storm_winds"
        assert lines[1] == "World event roll: 50% -> no world event"

    def test_dragon_heal_only_when_positive(self) -> None:
        log = DayDebugLog()
        log.start_day(1)
        log_dragon_end_of_day_heal(log, 100, 100)
        log_dragon_end_of_day_heal(log, 80, 120)
        lines = log.format_for_display(1)
        assert len(lines) == 1
        assert lines[0] == "Dragon heal: HP 80 -> 120 (+40)"

    def test_settlement_labels_and_phase_logging(self) -> None:
        v1 = Village(OffsetCoord(1, 0))
        v2 = Village(OffsetCoord(0, 1))
        city = City(OffsetCoord(2, 2))
        settlements = {
            v1.position: v1,
            v2.position: v2,
            city.position: city,
        }
        labels = settlement_labels_by_coord(settlements)
        assert labels[v1.position] == "Village 1"
        assert labels[v2.position] == "Village 2"
        assert labels[city.position] == "City 1"

        log = DayDebugLog()
        log.start_day(3)
        outcomes = {
            v1.position: (
                SettlementPhaseBefore(eco=500, atk=50, dfn=30, hp=500),
                SettlementPhaseOutcome(
                    action="grew",
                    eco_delta=10,
                    atk_delta=3,
                    dfn_delta=3,
                ),
                False,
            ),
            v2.position: (
                SettlementPhaseBefore(eco=500, atk=50, dfn=30, hp=400),
                SettlementPhaseOutcome(action="healed", hp_delta=50),
                False,
            ),
            city.position: (
                SettlementPhaseBefore(eco=1000, atk=70, dfn=80, hp=800),
                SettlementPhaseOutcome(action="none"),
                True,
            ),
        }
        log_settlement_phase(log, settlements, outcomes)
        lines = log.format_for_display(3)
        assert any("Village 1 (1,0): grow" in line for line in lines)
        assert any("Village 2 (0,1): heal HP 400 -> 450" in line for line in lines)
        assert any("City 1 (2,2): growth delayed" in line for line in lines)

    def test_army_phase_movement_and_merge(self) -> None:
        army_a = Army(
            hp=100,
            max_hp=100,
            atk=10,
            dfn=5,
            movement_speed=12,
            position=OffsetCoord(0, 0),
            kind=ArmyKind.VILLAGE,
        )
        army_b = Army(
            hp=100,
            max_hp=100,
            atk=10,
            dfn=5,
            movement_speed=12,
            position=OffsetCoord(1, 0),
            kind=ArmyKind.CITY,
        )
        before = snapshot_armies_before_phase([army_a, army_b])
        army_a.position = OffsetCoord(2, 0)
        army_b.position = OffsetCoord(2, 0)
        phase_result = ArmyPhaseResult(
            armies=(army_a,),
            citadel_hp=49,
            citadel_attacks=0,
            merged_stacks=1,
            game_over=False,
        )
        log = DayDebugLog()
        log.start_day(1)
        log_army_phase(
            log,
            before,
            [army_a, army_b],
            phase_result,
            citadel_coord=OffsetCoord(9, 9),
        )
        lines = log.format_for_display(1)
        assert any("Army #0 (village): (0,0) -> (2,0)" in line for line in lines)
        assert any("Army merge: 1 stack(s) combined" in line for line in lines)
