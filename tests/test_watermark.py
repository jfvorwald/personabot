"""How the brain decides someone has said enough to be worth re-reading.

This froze every profile permanently after the first scan. The comparison was
`len(messages_this_scan) - count_at_last_scan`, which looks like a delta and
isn't: BRAIN_SCAN_LIMIT is a sliding window, so the left-hand side is
window-relative and drifts down as other people talk.
"""

from __future__ import annotations

import brain


def test_everything_is_new_on_a_first_scan():
    assert brain.count_new([100, 200, 300], since=0) == 3


def test_counts_only_messages_after_the_watermark():
    assert brain.count_new([100, 200, 300, 400], since=200) == 2


def test_nothing_new_when_caught_up():
    assert brain.count_new([100, 200, 300], since=300) == 0


def test_empty_history_counts_zero():
    assert brain.count_new([], since=500) == 0


def test_watermark_ahead_of_everything_counts_zero():
    """Can happen if the window slid past what we last read."""
    assert brain.count_new([100, 200], since=9999) == 0


def test_a_shrinking_window_still_reports_new_messages():
    """The regression, stated directly.

    A busy channel pushes this person's older messages out of the scan window,
    so their in-window count *falls* from 300 to 250 even though they posted 50
    new ones. Count-differencing yields 250 - 300 = -50, which never clears
    BRAIN_MIN_NEW, and the profile is skipped forever. Comparing ids is immune:
    the 50 genuinely-new messages are counted regardless of what fell off.
    """
    previous_scan_count = 300
    ids_in_window = list(range(1_000, 1_200)) + list(range(5_000, 5_050))
    watermark = 1_199  # newest id we had read last time

    assert brain.count_new(ids_in_window, watermark) == 50

    window_count = len(ids_in_window)  # 250
    assert window_count - previous_scan_count < 0, "count-differencing goes negative"


def test_ids_out_of_order_are_still_counted():
    assert brain.count_new([300, 100, 400, 200], since=200) == 2
