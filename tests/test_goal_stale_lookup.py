"""`goal_stale_lookup.py` (#30) - the Django-aware piece of stale goal detection.

Everything here needs a database; the goal-age arithmetic and the lifecycle
rules are covered, database-free, in `tests/test_goal_stale.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from portfolio.models import Project, RepoWeek
from portfolio.services.goal_stale_lookup import (
    commits_since_goal_set,
    stale_goal_status_for_project,
)

UTC_TZ = UTC


def make_repo_week(repo: str, week: str, commits: int) -> RepoWeek:
    return RepoWeek.objects.create(
        repo=repo,
        week=week,
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 7, 23, 59, 59, 999999, tzinfo=UTC),
        commits=commits,
        active_days=min(commits, 1),
        lines_added=0,
        lines_removed=0,
        files_touched=0,
        partial=False,
    )


# --- commits_since_goal_set ---------------------------------------------------------


@pytest.mark.django_db
def test_sums_commits_across_the_whole_window():
    for week, commits in [
        ("2026-W28", 0),
        ("2026-W29", 0),
        ("2026-W30", 3),  # a lone, mid-window commit
        ("2026-W31", 0),
        ("2026-W32", 0),
        ("2026-W33", 0),
        ("2026-W34", 0),
        ("2026-W35", 0),
        ("2026-W36", 0),
    ]:
        make_repo_week("me/demo", week, commits)

    total = commits_since_goal_set("me/demo", datetime(2026, 7, 6, tzinfo=UTC), "2026-W36", UTC_TZ)

    assert total == 3


@pytest.mark.django_db
def test_zero_when_every_stored_week_in_the_window_is_silent():
    for week in ["2026-W28", "2026-W29", "2026-W30", "2026-W36"]:
        make_repo_week("me/demo", week, 0)

    total = commits_since_goal_set("me/demo", datetime(2026, 7, 6, tzinfo=UTC), "2026-W36", UTC_TZ)

    assert total == 0


@pytest.mark.django_db
def test_ignores_commits_before_the_window():
    make_repo_week("me/demo", "2026-W20", commits=5)  # before goal_set_at's week
    make_repo_week("me/demo", "2026-W36", commits=0)

    total = commits_since_goal_set("me/demo", datetime(2026, 7, 6, tzinfo=UTC), "2026-W36", UTC_TZ)

    assert total == 0


@pytest.mark.django_db
def test_no_rows_at_all_is_zero():
    total = commits_since_goal_set(
        "me/never-tracked", datetime(2026, 7, 6, tzinfo=UTC), "2026-W36", UTC_TZ
    )

    assert total == 0


# --- stale_goal_status_for_project: end-to-end wiring --------------------------------


@pytest.mark.django_db
def test_flagged_when_silent_for_the_whole_eight_plus_week_window():
    project = Project.objects.create(
        repo="me/ghost",
        status=Project.Status.ACTIVE,
        goal="Ship v1.",
        goal_set_at=datetime(2026, 7, 6, tzinfo=UTC),
    )
    for week in ["2026-W28", "2026-W30", "2026-W33", "2026-W36"]:
        make_repo_week("me/ghost", week, commits=0)

    result = stale_goal_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.weeks_since_goal_set == 8
    assert result.stale is True


@pytest.mark.django_db
def test_lone_mid_window_commit_clears_the_flag():
    project = Project.objects.create(
        repo="me/mostly-quiet",
        status=Project.Status.ACTIVE,
        goal="Ship v1.",
        goal_set_at=datetime(2026, 7, 6, tzinfo=UTC),
    )
    make_repo_week("me/mostly-quiet", "2026-W28", commits=0)
    make_repo_week("me/mostly-quiet", "2026-W31", commits=1)  # one lone commit, mid-window
    make_repo_week("me/mostly-quiet", "2026-W36", commits=0)

    result = stale_goal_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.stale is False


@pytest.mark.django_db
def test_no_goal_is_never_flagged():
    project = Project.objects.create(
        repo="me/no-goal",
        status=Project.Status.ACTIVE,
        goal="",
        goal_set_at=datetime(2026, 7, 6, tzinfo=UTC),
    )
    make_repo_week("me/no-goal", "2026-W36", commits=0)

    result = stale_goal_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.stale is False


@pytest.mark.django_db
def test_tracked_less_than_eight_weeks_is_never_flagged():
    project = Project.objects.create(
        repo="me/young-goal",
        status=Project.Status.ACTIVE,
        goal="Ship v1.",
        goal_set_at=datetime(2026, 8, 3, tzinfo=UTC),  # < 8 weeks before W36
    )
    make_repo_week("me/young-goal", "2026-W36", commits=0)

    result = stale_goal_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.stale is False


@pytest.mark.django_db
def test_paused_project_not_flagged_while_pause_in_force():
    project = Project.objects.create(
        repo="me/paused",
        status=Project.Status.PAUSED,
        goal="Ship v1.",
        goal_set_at=datetime(2026, 7, 6, tzinfo=UTC),
        paused_until=date(2026, 12, 31),
    )
    make_repo_week("me/paused", "2026-W36", commits=0)

    result = stale_goal_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.stale is False


@pytest.mark.django_db
def test_shipped_project_is_never_flagged():
    project = Project.objects.create(
        repo="me/shipped",
        status=Project.Status.SHIPPED,
        goal="Ship v1.",
        goal_set_at=datetime(2026, 7, 6, tzinfo=UTC),
    )
    make_repo_week("me/shipped", "2026-W36", commits=0)

    result = stale_goal_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.stale is False
