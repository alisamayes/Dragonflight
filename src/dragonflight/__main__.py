"""Entry point for ``python -m dragonflight`` / the ``dragonflight`` console script.

Loads the bundled example map and opens the interactive Pygame session (dragon
movement, reachability tinting, hour bar). Map loading lives in ``map_loader``;
the session loop lives in ``movement_playtest``. This module resolves the map
path and turns expected failures into clean human-readable error messages
instead of raw tracebacks at the console.

For a non-interactive static map preview only, call
:func:`dragonflight.render.run_demo` from code or a small script.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .map_loader import MapLoadError, load_map
from .movement_playtest import run_movement_playtest

#: Project layout invariant — ``src/dragonflight/__main__.py`` sits two
#: directories below the project root, where ``assets/`` lives. Recorded as a
#: constant so the resolution rule is documented in one place rather than
#: implicit in the call site.
_PROJECT_ROOT_DEPTH: int = 2

#: Bundled example map authored by the Game Map Designer (Wave 1 output) and
#: validated by ``map_loader``'s loader tests. The path is resolved at call
#: time rather than import time so tests can monkeypatch the resolver if
#: future slices require it.
_EXAMPLE_MAP_RELATIVE: tuple[str, ...] = ("assets", "example_hexmap.json")


def _example_map_path() -> Path:
    """Return the absolute path to the bundled example map.

    Resolved relative to this module's location so the entry point works
    regardless of the current working directory.
    """
    project_root = Path(__file__).resolve().parents[_PROJECT_ROOT_DEPTH]
    return project_root.joinpath(*_EXAMPLE_MAP_RELATIVE)


def main() -> None:
    """Load the example map and run the interactive movement session (requires pygame)."""
    map_path = _example_map_path()
    if not map_path.exists():
        print(
            f"dragonflight: example map not found at {map_path}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        game_map = load_map(map_path)
    except MapLoadError as exc:
        print(
            f"dragonflight: failed to load map {map_path}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    run_movement_playtest(game_map)


if __name__ == "__main__":
    main()
