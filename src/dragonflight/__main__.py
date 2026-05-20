"""Entry point for ``python -m dragonflight`` / the ``dragonflight`` console script.

Opens the interactive Pygame client: main menu → new game (map + dragon) →
play session. Map loading and validation happen when the player confirms
their choices; see ``map_loader`` and ``play_session``.

For a non-interactive static map preview only, call
:func:`dragonflight.render.run_demo` from code or a small script.
"""

from __future__ import annotations

from .play_session import run_play_session


def main() -> None:
    """Start the Pygame client (menu-first; requires pygame)."""
    run_play_session()


if __name__ == "__main__":
    main()
