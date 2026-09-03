"""`persist_repo_week` (#13) - the one Django-aware piece of momentum stats.

Everything here needs a database; the counting itself is covered, database-free,
in `tests/test_momentum.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError

from portfolio.models import RepoWeek
from portfolio.services.momentum import RepoWeekStats
from portfolio.services.repoweek import persist_repo_week

WINDOW = (
    datetime(2026, 8, 31, 0, 0, 0, tzinfo=UTC),
    datetime(2026, 9, 6, 23, 59, 59, 999999, tzinfo=UTC),
)


@pytest.mark.django_db
def test_persist_creates_a_row_for_every_tracked_repo_including_zero_commits():
    stats = RepoWeekStats(
        commits=0, active_days=0, lines_added=0, lines_removed=0, files_touched=0, partial=False
    )

    row = persist_repo_week("me/silent-repo", "2026-W36", WINDOW, stats)

    assert row.pk is not None
    assert RepoWeek.objects.count() == 1
    assert row.repo == "me/silent-repo"
    assert row.week == "2026-W36"
    assert row.commits == 0
    assert row.partial is False


@pytest.mark.django_db
def test_rerunning_the_same_week_updates_the_existing_row_not_a_duplicate():
    first = RepoWeekStats(
        commits=3, active_days=2, lines_added=10, lines_removed=1, files_touched=4, partial=False
    )
    second = RepoWeekStats(
        commits=5, active_days=3, lines_added=20, lines_removed=6, files_touched=7, partial=True
    )

    persist_repo_week("me/demo", "2026-W36", WINDOW, first)
    row = persist_repo_week("me/demo", "2026-W36", WINDOW, second)

    assert RepoWeek.objects.filter(repo="me/demo", week="2026-W36").count() == 1
    row.refresh_from_db()
    assert row.commits == 5
    assert row.active_days == 3
    assert row.lines_added == 20
    assert row.lines_removed == 6
    assert row.files_touched == 7
    assert row.partial is True


@pytest.mark.django_db
def test_same_repo_different_weeks_are_separate_rows():
    stats = RepoWeekStats(
        commits=1, active_days=1, lines_added=1, lines_removed=1, files_touched=1, partial=False
    )

    persist_repo_week("me/demo", "2026-W35", WINDOW, stats)
    persist_repo_week("me/demo", "2026-W36", WINDOW, stats)

    assert RepoWeek.objects.filter(repo="me/demo").count() == 2


@pytest.mark.django_db
def test_unique_constraint_holds_at_the_database_level():
    RepoWeek.objects.create(
        repo="me/demo",
        week="2026-W36",
        window_start=WINDOW[0],
        window_end=WINDOW[1],
        commits=1,
        active_days=1,
        lines_added=1,
        lines_removed=1,
        files_touched=1,
        partial=False,
    )

    with pytest.raises(IntegrityError):
        RepoWeek.objects.create(
            repo="me/demo",
            week="2026-W36",
            window_start=WINDOW[0],
            window_end=WINDOW[1],
            commits=2,
            active_days=1,
            lines_added=1,
            lines_removed=1,
            files_touched=1,
            partial=False,
        )
