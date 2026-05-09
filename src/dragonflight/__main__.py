"""Entry point for ``python -m dragonflight`` / the ``dragonflight`` console script.

Slice 1 wiring: load the bundled example map and open a Pygame window that
renders it as flat-top coloured hexes (spec §4 Perspective bullet). All real
behaviour lives in ``map_loader`` and ``render``; this module only resolves
the map path, dispatches, and turns expected failures into clean
human-readable error messages instead of raw tracebacks at the console.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .map_loader import MapLoadError, load_map
from .render import run_demo

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
    """Open the Slice 1 demo window with the bundled example map.

    Exits non-zero with a clear ``stderr`` message on expected failures
    (missing map file, invalid map JSON). Unexpected exceptions still
    propagate so bugs surface during development.
    """
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

    run_demo(game_map)


if __name__ == "__main__":
    main()
