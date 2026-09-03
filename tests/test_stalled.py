"""Stalled detection (#14), tested from fixtures. No network, no database.

`weeks_since_last_commit` / `stalled_status` are pure: labels and plain
lifecycle values go in, a `StalledStatus` comes out. Reading `RepoWeek` from
the database is covered separately in `tests/test_stalled_lookup.py`.
"""

from __future__ import annotations

from datetime import UTC, date

from portfolio.services.stalled import (
    STALLED_THRESHOLD_WEEKS,
    StalledStatus,
    is_stalled,
    stalled_status,
    weeks_since_last_commit,
)

UTC_TZ = UTC


# --- weeks_since_last_commit: the raw number -------------------------------------


def test_commit_in_the_reported_week_is_zero():
    assert weeks_since_last_commit("2026-W36", "2026-W36", UTC_TZ) == 0


def test_stalled_at_exactly_the_threshold():
    # W31 -> W35 is 4 whole ISO weeks.
    assert weeks_since_last_commit("2026-W31", "2026-W35", UTC_TZ) == STALLED_THRESHOLD_WEEKS


def test_just_under_the_threshold_is_not_stalled():
    # W32 -> W35 is 3 whole ISO weeks - one short of the 4-week threshold.
    weeks = weeks_since_last_commit("2026-W32", "2026-W35", UTC_TZ)
    assert weeks == 3
    assert is_stalled(weeks) is False


def test_never_committed_reports_none_not_zero():
    assert weeks_since_last_commit(None, "2026-W36", UTC_TZ) is None


def test_none_is_always_stalled():
    assert is_stalled(None) is True


def test_stalled_threshold_is_a_named_constant():
    assert STALLED_THRESHOLD_WEEKS == 4
    assert is_stalled(STALLED_THRESHOLD_WEEKS) is True
    assert is_stalled(STALLED_THRESHOLD_WEEKS - 1) is False


# --- weeks_since_last_commit: measured against end of reported week, not today ---


def test_old_week_reruns_the_same_answer_regardless_of_today():
    # A long-past week, computed today (2026) - the answer must depend only on
    # the two week labels, never on "now".
    weeks = weeks_since_last_commit("2020-W01", "2020-W05", UTC_TZ)
    assert weeks == 4


# --- stalled_status: project lifecycle rules --------------------------------------


def test_active_repo_with_commit_this_week_is_not_stalled():
    result = stalled_status(
        last_commit_week="2026-W36",
        reported_week="2026-W36",
        status="active",
        paused_until=None,
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result == StalledStatus(weeks_since_last_commit=0, stalled=False)


def test_active_repo_silent_four_plus_weeks_is_stalled():
    result = stalled_status(
        last_commit_week="2026-W31",
        reported_week="2026-W35",
        status="active",
        paused_until=None,
        reference_date=date(2026, 8, 30),
        tz=UTC_TZ,
    )
    assert result.stalled is True
    assert result.weeks_since_last_commit == 4


def test_never_committed_active_repo_is_stalled_immediately():
    result = stalled_status(
        last_commit_week=None,
        reported_week="2026-W36",
        status="active",
        paused_until=None,
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result == StalledStatus(weeks_since_last_commit=None, stalled=True)


def test_paused_project_not_flagged_while_pause_in_force():
    result = stalled_status(
        last_commit_week="2026-W10",
        reported_week="2026-W36",
        status="paused",
        paused_until=date(2026, 12, 31),
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result.stalled is False
    # The underlying number is still reported even though the flag is silenced.
    assert result.weeks_since_last_commit is not None


def test_paused_project_reflagged_once_pause_date_passes():
    result = stalled_status(
        last_commit_week="2026-W10",
        reported_week="2026-W36",
        status="paused",
        paused_until=date(2026, 9, 1),
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result.stalled is True


def test_paused_project_with_no_paused_until_is_never_flagged():
    result = stalled_status(
        last_commit_week=None,
        reported_week="2026-W36",
        status="paused",
        paused_until=None,
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result.stalled is False


def test_shipped_project_is_never_flagged_even_if_ancient():
    result = stalled_status(
        last_commit_week=None,
        reported_week="2026-W36",
        status="shipped",
        paused_until=None,
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result.stalled is False


def test_dropped_project_is_never_flagged_even_if_ancient():
    result = stalled_status(
        last_commit_week=None,
        reported_week="2026-W36",
        status="dropped",
        paused_until=None,
        reference_date=date(2026, 9, 6),
        tz=UTC_TZ,
    )
    assert result.stalled is False


def test_pause_reference_date_is_the_reported_week_end_not_today():
    # An old week, re-run "today": the pause was still in force back then
    # (reference_date is the old week's Sunday), even though `paused_until`
    # has long since passed by today's real date.
    result = stalled_status(
        last_commit_week="2020-W01",
        reported_week="2020-W02",
        status="paused",
        paused_until=date(2020, 1, 20),
        reference_date=date(2020, 1, 12),  # end of the reported week, back then
        tz=UTC_TZ,
    )
    assert result.stalled is False
