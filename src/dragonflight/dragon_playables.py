"""Concrete dragon species from ``Documentation/dragon_types.md``.

Each playable dragon is a :class:`~dragonflight.dragon.Dragon` subclass with
baseline stats and structured ability lines::

    unlock level - Passive|Ability - CD - duration - name

Combat behaviour for passives/actives is not simulated here yet; this module
anchors type identity, tuning numbers, and designer-facing ability metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from .dragon import Dragon, DragonKind
from .dragon_defaults import DEFAULT_DRAGON_LEVEL, HOURS_PER_DRAGON_DAY
from .hex_coord import OffsetCoord


@dataclass(frozen=True, slots=True)
class DragonAbilitySpec:
    """One row from the dragon-types doc (design metadata + future rule hooks)."""

    unlock_level: int
    category: Literal["passive", "ability"]
    cooldown: str
    duration: str
    name: str
    description: str


@dataclass
class Redgon(Dragon):
    """Red dragon — high attack and flight range (``dragon_types.md``)."""

    DISPLAY_NAME: ClassVar[str] = "Redgon (Red)"
    SELECTION_DESCRIPTION: ClassVar[str] = (
        "Redgon specializes in dealing high damage fast in hit and run tactics. Redgon has a higher than average attack and significantly higher speed and flight range."
        " This allows them to travel far across the map and even strike enemies from a distance with their abilities, dealing more damage the longer they fight."
    )

    ABILITIES: ClassVar[tuple[DragonAbilitySpec, ...]] = (
        DragonAbilitySpec(
            5,
            "passive",
            "No CD",
            "Constant",
            "Flame buffer",
            "Each combat round, stacking +3% damage multiplier on attacks, up to +30%.",
        ),
        DragonAbilitySpec(
            10,
            "ability",
            "1 turn CD",
            "Instant",
            "Plasma Lance",
            "Beam at a tile for 100% attack; ignores target defence.",
        ),
        DragonAbilitySpec(
            15,
            "ability",
            "3 turn CD",
            "3 hours",
            "Fiery Malice",
            "+50% attack, flight range, and speed; one extra Plasma Lance charge that day.",
        ),
    )

    @classmethod
    def new_at(cls, citadel_coord: OffsetCoord) -> Redgon:
        return cls(
            kind=DragonKind.RED_FIRE,
            position=citadel_coord,
            level=DEFAULT_DRAGON_LEVEL,
            hp=500,
            max_hp=500,
            atk=120,
            dfn=90,
            flight_range_hexes=7,
            speed_hexes_per_hour=8.0,
            hours_remaining=HOURS_PER_DRAGON_DAY,
        )


@dataclass
class Blackgon(Dragon):
    """Black dragon — heavy defence and thorns (``dragon_types.md``)."""

    DISPLAY_NAME: ClassVar[str] = "Blackgon (Black)"
    SELECTION_DESCRIPTION: ClassVar[str] = (
        "Blackgon boasts a heavy defence. Being an ancient dragon they are larger and slower than most other dragons but make up for it by being able to fight in sustained combat without needing to retreat."
        "They also have access to hardened scales that deal damage to attackers allowing them to turn their defence into offensive capabilities."
    )

    ABILITIES: ClassVar[tuple[DragonAbilitySpec, ...]] = (
        DragonAbilitySpec(
            5,
            "passive",
            "No CD",
            "Constant",
            "Spiked Scales",
            (
                "Thorns: each enemy strike also deals 10% of Blackgon's "
                "defence as damage to the attacker."
            ),
        ),
        DragonAbilitySpec(
            10,
            "ability",
            "1 turn CD",
            "12 hours",
            "Ancient's Roar",
            (
                "Enemies within flight range deal 30% less damage; armies also "
                "−40% move speed on their next move."
            ),
        ),
        DragonAbilitySpec(
            15,
            "ability",
            "3 turn CD",
            "3 hours",
            "Defend the Citadel",
            "Return to citadel in 1/3 time, ignoring range restrictions; +50% defence.",
        ),
    )

    @classmethod
    def new_at(cls, citadel_coord: OffsetCoord) -> Blackgon:
        return cls(
            kind=DragonKind.BLACK_TANK,
            position=citadel_coord,
            level=DEFAULT_DRAGON_LEVEL,
            hp=500,
            max_hp=500,
            atk=100,
            dfn=140,
            flight_range_hexes=5,
            speed_hexes_per_hour=4.0,
            hours_remaining=HOURS_PER_DRAGON_DAY,
        )


@dataclass
class Greengon(Dragon):
    """Green dragon — higher HP pool and healing focus (``dragon_types.md``)."""

    DISPLAY_NAME: ClassVar[str] = "Greengon (Green)"
    SELECTION_DESCRIPTION: ClassVar[str] = (
        "Greengon is the only dragon that is able to heal itself by harnessing healing crystal and their magic. Utilizing lifeforce they can passively sustain themselves"
        " and heal themselve in a pinch if needed. Furthermore they can turn their higher lifeforce into offensive power through their abilities."
    )

    ABILITIES: ClassVar[tuple[DragonAbilitySpec, ...]] = (
        DragonAbilitySpec(
            5,
            "passive",
            "No CD",
            "Constant",
            "Healing Crystal",
            "For every 1 in-game hour expended, heal 2% max HP.",
        ),
        DragonAbilitySpec(
            10,
            "ability",
            "1 turn CD",
            "5 hours",
            "Draconic Resurgence",
            "If under 50% max HP: restore 25% HP instantly; double passive healing for duration.",
        ),
        DragonAbilitySpec(
            15,
            "ability",
            "3 turn CD",
            "5 hours",
            "Vivify",
            "+20% map HP immediately; may sacrifice 20% current HP to add it to next attack.",
        ),
    )

    @classmethod
    def new_at(cls, citadel_coord: OffsetCoord) -> Greengon:
        return cls(
            kind=DragonKind.GREEN_LIFE,
            position=citadel_coord,
            level=DEFAULT_DRAGON_LEVEL,
            hp=650,
            max_hp=600,
            atk=90,
            dfn=100,
            flight_range_hexes=6,
            speed_hexes_per_hour=6.0,
            hours_remaining=HOURS_PER_DRAGON_DAY,
        )


@dataclass
class Yellowgon(Dragon):
    """Yellow dragon — chronomancy / mitigation (``dragon_types.md``)."""

    DISPLAY_NAME: ClassVar[str] = "Yellowgon (Yellow)"
    SELECTION_DESCRIPTION: ClassVar[str] = (
        "Yellowgon is able to manipulate time. Slowing it down to their advantage to affect the world around them, forsee and prevent incoming damage,"
        "and even temporarliy freeze it to travel or strike without consequences."
    )

    ABILITIES: ClassVar[tuple[DragonAbilitySpec, ...]] = (
        DragonAbilitySpec(
            5,
            "passive",
            "No CD",
            "Constant",
            "Foresight",
            "After each combat round, undo 10% of all damage taken that round.",
        ),
        DragonAbilitySpec(
            10,
            "ability",
            "1 turn CD",
            "1 hour",
            "Timestop",
            "For the next hour no time passes; enemies cannot retaliate.",
        ),
        DragonAbilitySpec(
            15,
            "ability",
            "5 turn CD",
            "24 hours",
            "Chrono-conic pulse",
            (
                "Armies move at half speed; settlements grow at half speed; "
                "damaged settlements lose half eco power."
            ),
        ),
    )

    @classmethod
    def new_at(cls, citadel_coord: OffsetCoord) -> Yellowgon:
        return cls(
            kind=DragonKind.YELLOW_CHRONO,
            position=citadel_coord,
            level=DEFAULT_DRAGON_LEVEL,
            hp=500,
            max_hp=500,
            atk=90,
            dfn=90,
            flight_range_hexes=5,
            speed_hexes_per_hour=5.0,
            hours_remaining=HOURS_PER_DRAGON_DAY,
        )


@dataclass
class Purplegon(Dragon):
    """Purple dragon — frost damage and control (``dragon_types.md``)."""

    DISPLAY_NAME: ClassVar[str] = "Purplegon (Purple)"
    SELECTION_DESCRIPTION: ClassVar[str] = (
        "Purplegon is a combat oriented dragon that harnesses elemental power to augment their attacks. Hindering or damaging enemies in both melee and ranged combat. They are also heavily armoured,"
        " imporiving their defence and offense at the cost of speed and flight range."
    )

    ABILITIES: ClassVar[tuple[DragonAbilitySpec, ...]] = (
        DragonAbilitySpec(
            5,
            "passive",
            "No CD",
            "Constant",
            "Ice Talons",
            "Each hit reduces enemy combat ATK by 10% (stacks; base ATK unchanged).",
        ),
        DragonAbilitySpec(
            10,
            "ability",
            "1 turn CD",
            "Instant",
            "Tempest Strike",
            (
                "Strike a tile for 100% attack; chains to another enemy at 50% "
                "per hop until no further targets."
            ),
        ),
        DragonAbilitySpec(
            15,
            "ability",
            "3 turn CD",
            "Instant",
            "Absolute Zero Breath",
            "5-tile line breath: 150% attack damage; struck enemies cannot recover HP.",
        ),
    )

    @classmethod
    def new_at(cls, citadel_coord: OffsetCoord) -> Purplegon:
        return cls(
            kind=DragonKind.PURPLE_FROST,
            position=citadel_coord,
            level=DEFAULT_DRAGON_LEVEL,
            hp=500,
            max_hp=500,
            atk=120,
            dfn=120,
            flight_range_hexes=4,
            speed_hexes_per_hour=4.0,
            hours_remaining=HOURS_PER_DRAGON_DAY,
        )


@dataclass
class Browngon(Dragon):
    """Brown dragon — earth / mountain synergy (``dragon_types.md``)."""

    DISPLAY_NAME: ClassVar[str] = "Browngon (Brown)"
    SELECTION_DESCRIPTION: ClassVar[str] = (
        "Browngon is a large and slow dragon that likes the stones of the earth as much as the open sky. They are in their element near the mountains and gain advantages"
        " when in range of them. They may even manipulate the earth around them to their advantage, creating unstable ground or even permanent terrain features."
    )

    ABILITIES: ClassVar[tuple[DragonAbilitySpec, ...]] = (
        DragonAbilitySpec(
            5,
            "passive",
            "No CD",
            "Constant",
            "Mountain's Boon",
            "With a mountain within 3 tiles: +2 speed and +10% attack.",
        ),
        DragonAbilitySpec(
            10,
            "ability",
            "1 turn CD",
            "24 hours",
            "Tremors",
            (
                "Earthquake on one tile ('lose ground'); fights there debuff "
                "hostile armies −15% defence."
            ),
        ),
        DragonAbilitySpec(
            15,
            "ability",
            "3 turn CD",
            "Constant",
            "Terrascape",
            "Raise a permanent mountain with routing/settlement spacing constraints.",
        ),
    )

    @classmethod
    def new_at(cls, citadel_coord: OffsetCoord) -> Browngon:
        return cls(
            kind=DragonKind.BROWN_EARTH,
            position=citadel_coord,
            level=DEFAULT_DRAGON_LEVEL,
            hp=550,
            max_hp=550,
            atk=100,
            dfn=110,
            flight_range_hexes=4,
            speed_hexes_per_hour=2.0,
            hours_remaining=HOURS_PER_DRAGON_DAY,
        )


_KIND_TO_CTOR: dict[DragonKind, type[Dragon]] = {
    DragonKind.RED_FIRE: Redgon,
    DragonKind.BLACK_TANK: Blackgon,
    DragonKind.GREEN_LIFE: Greengon,
    DragonKind.YELLOW_CHRONO: Yellowgon,
    DragonKind.PURPLE_FROST: Purplegon,
    DragonKind.BROWN_EARTH: Browngon,
}


def playable_dragon_kinds() -> tuple[DragonKind, ...]:
    """Stable UI ordering for new-game dragon selection."""
    return tuple(_KIND_TO_CTOR.keys())


def display_name_for_kind(kind: DragonKind) -> str:
    cls = _KIND_TO_CTOR.get(kind)
    if cls is None:
        return kind.value.replace("_", " ").title()
    return getattr(cls, "DISPLAY_NAME")


def selection_description_for_kind(kind: DragonKind) -> str:
    """Flavor text shown on the new-game dragon picker under the portrait."""
    cls = _KIND_TO_CTOR.get(kind)
    if cls is None:
        return ""
    return getattr(cls, "SELECTION_DESCRIPTION", "")


def new_playable_dragon(kind: DragonKind, citadel_coord: OffsetCoord) -> Dragon:
    """Spawn the correct subclass instance for ``kind`` at the citadel."""
    ctor = _KIND_TO_CTOR.get(kind)
    if ctor is None:
        msg = f"unsupported dragon kind for playable roster: {kind!r}"
        raise ValueError(msg)
    new_at = getattr(ctor, "new_at")
    return new_at(citadel_coord)


def default_playable_kind() -> DragonKind:
    """First dragon in the roster (used before the player chooses)."""
    return playable_dragon_kinds()[0]


__all__ = [
    "Blackgon",
    "Browngon",
    "DragonAbilitySpec",
    "Greengon",
    "Purplegon",
    "Redgon",
    "Yellowgon",
    "default_playable_kind",
    "display_name_for_kind",
    "new_playable_dragon",
    "playable_dragon_kinds",
    "selection_description_for_kind",
]
