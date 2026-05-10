"""Layout math for the movement playtest hour bar (pure, no pygame display)."""

from __future__ import annotations

from dragonflight.hour_bar_layout import hour_bar_segment_layout


class TestHourBarSegmentLayout:
    def test_partitions_inner_width_exactly_when_room_for_gaps(self) -> None:
        for inner in (960, 600, 200, 100):
            widths, gap = hour_bar_segment_layout(inner, 1)
            assert len(widths) == 24
            assert sum(widths) + 23 * gap == inner

        widths_flat, gap0 = hour_bar_segment_layout(800, 0)
        assert gap0 == 0
        assert sum(widths_flat) == 800

    def test_twenty_four_equal_slots_within_one_pixel(self) -> None:
        inner = 887
        widths, gap = hour_bar_segment_layout(inner, 1)
        assert max(widths) - min(widths) <= 1
