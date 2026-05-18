"""Canonical simulation-side terrain identity.

This module is the single source of truth for what kinds of terrain the game
recognises. Rendering colours, art assets, and movement modifiers all key off
``Terrain`` values declared here, but those concerns live elsewhere
(rendering in ``render`` once it lands; movement rules in the sim systems).

The string values match Dragonflight's spec vocabulary (spec num5) and are the
target of ``map_loader``'s resolution rules; they are *not* the editor's raw
``hexType`` strings (those are normalised by the loader).
"""

from __future__ import annotations

from enum import Enum


class Terrain(Enum):
    """Terrain types recognised by the Dragonflight simulation (spec num5)."""

    GRASSLAND = "grassland"
    WOODLAND = "woodland"
    MOUNTAIN = "mountain"
    RIVER = "river"
    BRIDGE = "bridge"
    SETTLEMENT = "settlement"
    CITADEL = "citadel"
