"""Stale goal detection (#30), tested from fixtures. No network, no database.

`weeks_since_goal_set` / `is_goal_stale` / `stale_goal_status` are pure: dates
and plain lifecycle values go in, a `StaleGoalStatus` comes out. Reading
`Project.goal_set_at` and summing `RepoWeek` is covered separately in
`tests/test_goal_stale_lookup.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from portfolio.services.goal_stale import (
    STALE_GOAL_THRESHOLD_WEEKS,
    StaleGoalStatus,
    is_goal_stale,
    stale_goal_status,
    weeks_since_goal_set,
)

UTC_TZ = UTC


# --- weeks_since_goal_set: the raw number -----------------------------------------


def test_goal_set_the_same_monday_is_zero():
    assert weeks_since_goal_set(datetime(2026, 8, 31, tzinfo=UTC), "2026-W36", UTC_TZ) == 0


def test_exactly_eight_weeks():
    # 2026-W28's Monday is 8 whole ISO weeks before 2026-W36's Monday.
    weeks = weeks_since_goal_set(datetime(2026, 7, 6, tzinfo=UTC), "2026-W36", UTC_TZ)
    assert weeks == STALE_GOAL_THRESHOLD_WEEKS


def test_just_under_eight_weeks():
    weeks = weeks_since_goal_set(datetime(2026, 7, 13, tzinfo=UTC), "2026-W36", UTC_TZ)
    assert weeks == 7


def test_naive_datetime_is_used_as_is():
    # goal_set_at without tzinfo (defensive - Django stores it aware under USE_TZ=True).
    weeks = weeks_since_goal_set(datetime(2026, 7, 6), "2026-W36", UTC_TZ)
    assert weeks == STALE_GOAL_THRESHOLD_WEEKS


def test_old_week_reruns_the_same_answer_regardless_of_today():
    # 2020-W01's Monday (2019-12-30) to 2020-W05's Monday (2020-01-27) is 4 whole weeks.
    weeks = weeks_since_goal_set(datetime(2019, 12, 30, tzinfo=UTC), "2020-W05", UTC_TZ)
    assert weeks == 4


# --- is_goal_stale: threshold + commit window ---------------------------------------


def test_stale_threshold_is_a_named_constant():
    assert STALE_GOAL_THRESHOLD_WEEKS == 8


def test_flagged_at_threshold_with_zero_commits():
    assert (
        is_goal_stale(
            goal="Ship v1.",
            weeks_since_goal_set=STALE_GOAL_THRESHOLD_WEEKS,
            commits_in_window=0,
            status="active",
            paused_until=None,
            reference_date=date(2026, 9, 6),
        )
        is True
    )


def test_not_flagged_one_week_under_threshold():
    assert (
        is_goal_stale(
            goal="Ship v1.",
            weeks_since_goal_set=STALE_GOAL_THRESHOLD_WEEKS - 1,
            commits_in_window=0,
            status="active",
            paused_until=None,
            reference_date=date(2026, 9, 6),
        )
        is False
    )


def test_not_flagged_when_a_commit_exists_in_the_window():
    # Even a single, mid-window commit clears the flag.
    assert (
        is_goal_stale(
            goal="Ship v1.",
            weeks_since_goal_set=STALE_GOAL_THRESHOLD_WEEKS,
            commits_in_window=1,
            status="active",
            paused_until=None,
            reference_date=date(2026, 9, 6),
        )
        is False
    )


def test_no_goal_set_is_never_flagged():
    assert (
        is_goal_stale(
            goal="",
            weeks_since_goal_set=99,
            commits_in_window=0,
            status="active",
            paused_until=None,
            reference_date=date(2026, 9, 6),
        )
        is False
    )


def test_shipped_project_is_never_flagged():
    assert (
        is_goal_stale(
            goal="Ship v1.",
            weeks_since_goal_set=99,
            commits_in_window=0,
            status="shipped",
            paused_until=None,
            reference_date=date(2026, 9, 6),
        )
        is False
    )


def test_dropped_project_is_never_flagged():
    assert (
        is_goal_stale(
            goal="Ship v1.",
            weeks_since_goal_set=99,
            commits_in_window=0,
            status="dropped",
            paused_until=None,
            reference_date=date(2026, 9, 6),
        )
        is False
    )


def test_paused_project_not_flagged_while_pause_in_force():
    assert (
        is_goal_stale(
            goal="Ship v1.",
            weeks_since_goal_set=99,
            commits_in_window=0,
            status="paused",
            paused_until=date(2026, 12, 31),
            reference_date=date(2026, 9, 6),
        )
        is False
    )


def test_paused_project_reflagged_once_pause_date_passes():
    assert (
        is_goal_stale(
            goal="Ship v1.",
            weeks_since_goal_set=99,
            commits_in_window=0,
            status="paused",
            paused_until=date(2026, 9, 1),
            reference_date=date(2026, 9, 6),
        )
        is True
    )


# --- stale_goal_status: end-to-end pure combination ----------------------------------


def test_stale_goal_status_combines_weeks_and_flag():
    result = stale_goal_status(
        goal="Ship v1.",
        goal_set_at=datetime(2026, 7, 6, tzinfo=UTC),
        reported_week="2026-W36",
        commits_in_window=0,
        status="active",
        paused_until=None,
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result == StaleGoalStatus(weeks_since_goal_set=8, stale=True)


def test_stale_goal_status_no_goal_set_at_is_never_flagged():
    result = stale_goal_status(
        goal="",
        goal_set_at=None,
        reported_week="2026-W36",
        commits_in_window=0,
        status="active",
        paused_until=None,
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result == StaleGoalStatus(weeks_since_goal_set=0, stale=False)
