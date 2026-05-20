"""Named default baselines for dragon tuning (spec num7; balance is provisional).

Centralise MVP placeholders here so gameplay code does not scatter magic numbers.
Tune values during balancing without hunting literals across modules.
"""

from __future__ import annotations

#: One in-game dragon day equals 24 clock hours available for movement and combat rounds.
HOURS_PER_DRAGON_DAY: float = 24.0

#: When the dragon ends the day at the citadel, heal this percent of :attr:`~dragon.Dragon.max_hp`
#: before the hourly bonus (spec num2 Citadel Phase).
DRAGON_CITADEL_END_OF_DAY_BASE_HEAL_PERCENT_OF_MAX: int = 50
#: Additional percent of ``max_hp`` healed per hour still remaining on the clock when docking
#: (rewards early return without wasting the day budget).
DRAGON_CITADEL_END_OF_DAY_BONUS_HEAL_PERCENT_OF_MAX_PER_HOUR_REMAINING: int = 2

#: Each discrete combat damage round consumes 30 minutes of the dragon daily budget (spec num8).
MINUTES_PER_DAMAGE_ROUND: int = 30

#: Fractional-hour form of :data:`MINUTES_PER_DAMAGE_ROUND` for time accounting.
HOURS_PER_DAMAGE_ROUND: float = MINUTES_PER_DAMAGE_ROUND / 60.0

# --- Red Fire Dragon (MVP) placeholder baselines --------------------------------

DEFAULT_DRAGON_LEVEL: int = 1

#: Survivability pool requested for scaffolding (full stat block otherwise 10s).
DEFAULT_DRAGON_MAX_HP: int = 50

#: Combat and mobility stats scaffolded at 10 until systems consume real baselines per species.
DEFAULT_DRAGON_ATK: int = 10
DEFAULT_DRAGON_DFN: int = 10
DEFAULT_DRAGON_FLIGHT_RANGE_HEXES: int = 10
DEFAULT_DRAGON_SPEED_HEXES_PER_HOUR: float = 10.0

# --- Dragon stat shop (spec num7; end-of-day draft at citadel hub) -----------------

#: Flat gold component in ``200 + level*20 + n*20``.
DRAGON_STAT_UPGRADE_COST_BASE: int = 200
#: Gold added per dragon level at the moment of purchase in the draft sequence.
DRAGON_STAT_UPGRADE_COST_LEVEL_COEFF: int = 20
#: Gold added per 1-based ordinal ``n`` for that stat (lifetime + draft, incl. this buy).
DRAGON_STAT_UPGRADE_COST_COUNT_COEFF: int = 20

DRAGON_STAT_UPGRADE_HP_DELTA: int = 50
DRAGON_STAT_UPGRADE_ATK_DELTA: int = 10
DRAGON_STAT_UPGRADE_DFN_DELTA: int = 10
DRAGON_STAT_UPGRADE_FLIGHT_RANGE_HEXES_DELTA: int = 2
DRAGON_STAT_UPGRADE_SPEED_HEXES_PER_HOUR_DELTA: float = 1.0
