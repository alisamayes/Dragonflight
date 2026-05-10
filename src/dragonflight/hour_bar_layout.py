"""Pure layout for the 24-hour segmented day bar (Pygame-agnostic)."""

from __future__ import annotations


def hour_bar_segment_layout(inner_width: int, gap_px: int) -> tuple[tuple[int, ...], int]:
    """Lay out 24 equal hour column widths within ``inner_width`` with ``gap_px`` gutters.

    Subtracts ``23 * gap`` when there is horizontal room; otherwise gaps collapse to
    zero. Pixel widths are balanced with the standard remainder trick so every hour
    occupies the same width within a **one-pixel** tolerance. The 23 gaps (if any)
    are fixed at ``gap_px`` so each hour cell is visually the same size.

    Returns ``(24 segment widths, gap width used between columns)``.
    """
    if inner_width <= 0:
        return ((0,) * 24), 0

    gap = max(0, gap_px)
    width_for_cells = inner_width - 23 * gap
    if width_for_cells < 24:
        gap = 0
        width_for_cells = inner_width

    if width_for_cells < 24:
        # Ultra-narrow bar: assign one pixel to the earliest hours until the window widens.
        return tuple(1 if index < width_for_cells else 0 for index in range(24)), 0

    base = width_for_cells // 24
    remainder = width_for_cells % 24
    widths = tuple(base + (1 if index < remainder else 0) for index in range(24))
    return widths, gap
