"""`stalled_lookup.py` (#14) - the Django-aware piece of stalled detection.

Everything here needs a database; the weeks-since-last-commit arithmetic and
the lifecycle rules are covered, database-free, in `tests/test_stalled.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from portfolio.models import Project, RepoWeek
from portfolio.services.stalled_lookup import (
    most_recent_commit_week,
    stalled_status_for_project,
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


# --- most_recent_commit_week ------------------------------------------------------


@pytest.mark.django_db
def test_finds_the_most_recent_week_with_commits():
    make_repo_week("me/demo", "2026-W30", commits=2)
    make_repo_week("me/demo", "2026-W33", commits=1)
    make_repo_week("me/demo", "2026-W36", commits=0)  # zero-commit row, must be skipped

    assert most_recent_commit_week("me/demo", "2026-W36") == "2026-W33"


@pytest.mark.django_db
def test_ignores_weeks_after_upto_week():
    make_repo_week("me/demo", "2026-W36", commits=3)

    # A week after the reported one must not count, even if it exists in the DB
    # (e.g. re-running an old week's report).
    assert most_recent_commit_week("me/demo", "2026-W30") is None


@pytest.mark.django_db
def test_no_rows_at_all_is_none():
    assert most_recent_commit_week("me/never-tracked", "2026-W36") is None


@pytest.mark.django_db
def test_commit_stored_for_the_reported_week_itself_counts():
    make_repo_week("me/demo", "2026-W36", commits=1)

    assert most_recent_commit_week("me/demo", "2026-W36") == "2026-W36"


# --- stalled_status_for_project: end-to-end wiring --------------------------------


@pytest.mark.django_db
def test_active_project_never_committed_is_stalled_immediately():
    project = Project.objects.create(repo="me/ghost", status=Project.Status.ACTIVE)

    result = stalled_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.weeks_since_last_commit is None
    assert result.stalled is True


@pytest.mark.django_db
def test_active_project_commit_this_week_is_not_stalled():
    project = Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    make_repo_week("me/demo", "2026-W36", commits=1)

    result = stalled_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.weeks_since_last_commit == 0
    assert result.stalled is False


@pytest.mark.django_db
def test_shipped_project_is_never_flagged():
    project = Project.objects.create(repo="me/done", status=Project.Status.SHIPPED)

    result = stalled_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.stalled is False


@pytest.mark.django_db
def test_paused_project_reflagged_after_pause_passes_using_reported_week_end():
    project = Project.objects.create(
        repo="me/paused",
        status=Project.Status.PAUSED,
        paused_until=date(2026, 8, 1),  # already in the past relative to W36
    )

    result = stalled_status_for_project(project, "2026-W36", UTC_TZ)

    assert result.stalled is True
