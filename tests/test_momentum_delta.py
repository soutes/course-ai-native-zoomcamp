"""`momentum_delta.py` (#21) - pure delta-text formatting, tested from plain
values. No Django, no database, no network.
"""

from __future__ import annotations

from portfolio.services.momentum_delta import (
    PreviousMomentum,
    format_delta,
    momentum_delta_text,
)


def test_format_delta_none_is_first_week_tracked():
    assert format_delta(None) == "(first week tracked)"


def test_format_delta_zero_is_distinct_from_no_row():
    assert format_delta(0) == "(last week: 0)"
    assert format_delta(0) != format_delta(None)


def test_format_delta_states_the_previous_value_plainly():
    assert format_delta(4) == "(last week: 4)"


def test_format_delta_a_drop_is_worded_the_same_as_a_rise():
    # No "+"/"-", no color/symbol hints anywhere in the text - a decrease from
    # a much larger previous value reads exactly like an increase would.
    assert format_delta(100) == "(last week: 100)"


def test_momentum_delta_text_no_previous_row_is_first_week_tracked_for_all_five():
    text = momentum_delta_text(None)
    assert text.commits == "(first week tracked)"
    assert text.active_days == "(first week tracked)"
    assert text.lines_added == "(first week tracked)"
    assert text.lines_removed == "(first week tracked)"
    assert text.files_touched == "(first week tracked)"


def test_momentum_delta_text_all_zero_previous_row_is_last_week_zero_for_all_five():
    previous = PreviousMomentum(
        commits=0, active_days=0, lines_added=0, lines_removed=0, files_touched=0
    )
    text = momentum_delta_text(previous)
    assert text.commits == "(last week: 0)"
    assert text.active_days == "(last week: 0)"
    assert text.lines_added == "(last week: 0)"
    assert text.lines_removed == "(last week: 0)"
    assert text.files_touched == "(last week: 0)"


def test_momentum_delta_text_carries_each_number_independently():
    previous = PreviousMomentum(
        commits=4, active_days=2, lines_added=120, lines_removed=30, files_touched=7
    )
    text = momentum_delta_text(previous)
    assert text.commits == "(last week: 4)"
    assert text.active_days == "(last week: 2)"
    assert text.lines_added == "(last week: 120)"
    assert text.lines_removed == "(last week: 30)"
    assert text.files_touched == "(last week: 7)"
