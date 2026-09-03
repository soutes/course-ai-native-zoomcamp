"""Time-to-decision (#32, D31 in docs/decisions.md).

Covers the pure aggregation in `portfolio.services.time_to_decision` -
`median_weeks_silent` - from plain `DroppedRow` fixtures, no database.
"""

from __future__ import annotations

from datetime import UTC, datetime

from portfolio.services.time_to_decision import DroppedRow, median_weeks_silent


def make_row(repo: str, weeks_silent: int | None) -> DroppedRow:
    return DroppedRow(
        repo=repo, end_date=datetime(2026, 1, 1, tzinfo=UTC), weeks_silent=weeks_silent
    )


def test_median_of_no_dropped_projects_is_none():
    assert median_weeks_silent([]) is None


def test_median_excludes_no_commit_history_rows():
    rows = [make_row("me/ghost", None)]
    assert median_weeks_silent(rows) is None


def test_median_includes_drop_while_active_zeros():
    rows = [make_row("me/a", 0), make_row("me/b", 0)]
    assert median_weeks_silent(rows) == 0


def test_median_of_odd_count_is_the_middle_value():
    rows = [make_row("me/a", 2), make_row("me/b", 6), make_row("me/c", 10)]
    assert median_weeks_silent(rows) == 6


def test_median_of_even_count_averages_the_two_middle_values():
    rows = [make_row("me/a", 2), make_row("me/b", 5), make_row("me/c", 8), make_row("me/d", 11)]
    assert median_weeks_silent(rows) == 6.5


def test_median_excludes_no_history_but_includes_the_rest():
    rows = [make_row("me/a", 4), make_row("me/ghost", None), make_row("me/b", 8)]
    assert median_weeks_silent(rows) == 6
