"""Dragonflight — turn-based dragon raiding strategy game (MVP)."""

from .settlement import (
    City,
    Fort,
    MockArmySpawnEvent,
    Settlement,
    SettlementCombatLoopResult,
    SettlementPhaseOutcome,
    SettlementType,
    Village,
    nearby_aggression_radius,
    resolve_settlement_combat_round,
    run_settlement_combat_loop,
)

__version__ = "0.1.0"

__all__ = [
    "City",
    "Fort",
    "MockArmySpawnEvent",
    "Settlement",
    "SettlementCombatLoopResult",
    "SettlementPhaseOutcome",
    "SettlementType",
    "Village",
    "__version__",
    "nearby_aggression_radius",
    "resolve_settlement_combat_round",
    "run_settlement_combat_loop",
]
