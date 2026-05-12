"""Entry point for ``python -m dragonflight`` / the ``dragonflight`` console script.

Opens the interactive Pygame client: **main menu** → new game (map + dragon) →
movement playtest. Map loading and validation happen when the player confirms
their choices; see ``map_loader`` and ``movement_playtest``.

For a non-interactive static map preview only, call
:func:`dragonflight.render.run_demo` from code or a small script.
"""

from __future__ import annotations

from .movement_playtest import run_movement_playtest


def main() -> None:
    """Start the Pygame client (menu-first; requires pygame)."""
    run_movement_playtest()


if __name__ == "__main__":
    main()
