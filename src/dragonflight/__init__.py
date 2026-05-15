"""Dragonflight — turn-based dragon raiding strategy game (MVP)."""

from .army import (
    Army,
    ArmyPhaseResult,
    collect_spawned_armies,
    merge_army_stacks,
    resolve_army_combat_round,
    run_army_phase,
    validate_dragon_vs_army,
)
from .citadel import DEFAULT_CITADEL_HP, CitadelState
from .combat_preview import (
    CombatDamagePreview,
    preview_army_round,
    preview_settlement_round,
)
from .game_tuning import GameTuning, default_game_tuning, resolve_tuning
from .settlement import (
    City,
    Fort,
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
    "Army",
    "ArmyPhaseResult",
    "CitadelState",
    "CombatDamagePreview",
    "City",
    "DEFAULT_CITADEL_HP",
    "Fort",
    "GameTuning",
    "Settlement",
    "SettlementCombatLoopResult",
    "SettlementPhaseOutcome",
    "SettlementType",
    "Village",
    "__version__",
    "collect_spawned_armies",
    "default_game_tuning",
    "merge_army_stacks",
    "nearby_aggression_radius",
    "preview_army_round",
    "preview_settlement_round",
    "resolve_army_combat_round",
    "resolve_settlement_combat_round",
    "resolve_tuning",
    "run_army_phase",
    "run_settlement_combat_loop",
    "validate_dragon_vs_army",
]
