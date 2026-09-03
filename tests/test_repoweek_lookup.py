"""`repoweek_lookup.py` (#21) - the Django-aware piece of week-over-week
deltas. The delta-text formatting itself is covered, database-free, in
`tests/test_momentum_delta.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from portfolio.models import RepoWeek
from portfolio.services.repoweek_lookup import previous_momentum_for_repo


def make_repo_week(
    repo: str,
    week: str,
    *,
    commits: int = 4,
    active_days: int = 2,
    lines_added: int = 120,
    lines_removed: int = 30,
    files_touched: int = 7,
    partial: bool = False,
) -> RepoWeek:
    return RepoWeek.objects.create(
        repo=repo,
        week=week,
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 7, 23, 59, 59, 999999, tzinfo=UTC),
        commits=commits,
        active_days=active_days,
        lines_added=lines_added,
        lines_removed=lines_removed,
        files_touched=files_touched,
        partial=partial,
    )


@pytest.mark.django_db
def test_no_previous_row_is_none():
    make_repo_week("me/demo", "2026-W36", commits=4)  # current week only, no prior row

    assert previous_momentum_for_repo("me/demo", "2026-W36") is None


@pytest.mark.django_db
def test_previous_row_of_all_zeros_is_returned_not_none():
    make_repo_week(
        "me/demo",
        "2026-W35",
        commits=0,
        active_days=0,
        lines_added=0,
        lines_removed=0,
        files_touched=0,
    )
    make_repo_week("me/demo", "2026-W36", commits=3)

    previous = previous_momentum_for_repo("me/demo", "2026-W36")

    assert previous is not None
    assert previous.commits == 0
    assert previous.active_days == 0
    assert previous.lines_added == 0
    assert previous.lines_removed == 0
    assert previous.files_touched == 0


@pytest.mark.django_db
def test_previous_row_carries_its_real_numbers():
    make_repo_week(
        "me/demo",
        "2026-W35",
        commits=4,
        active_days=2,
        lines_added=120,
        lines_removed=30,
        files_touched=7,
    )
    make_repo_week("me/demo", "2026-W36", commits=10)

    previous = previous_momentum_for_repo("me/demo", "2026-W36")

    assert previous.commits == 4
    assert previous.active_days == 2
    assert previous.lines_added == 120
    assert previous.lines_removed == 30
    assert previous.files_touched == 7


@pytest.mark.django_db
def test_year_boundary_week_pair_is_found():
    # 2026 has 53 ISO weeks - the true previous week of 2027-W01 is 2026-W53.
    make_repo_week("me/demo", "2026-W53", commits=6)
    make_repo_week("me/demo", "2027-W01", commits=2)

    previous = previous_momentum_for_repo("me/demo", "2027-W01")

    assert previous is not None
    assert previous.commits == 6


@pytest.mark.django_db
def test_partial_previous_row_still_returns_its_lines_and_files_numbers():
    make_repo_week(
        "me/demo",
        "2026-W35",
        commits=90,
        active_days=5,
        lines_added=500,
        lines_removed=200,
        files_touched=40,
        partial=True,
    )
    make_repo_week("me/demo", "2026-W36", commits=3)

    previous = previous_momentum_for_repo("me/demo", "2026-W36")

    # The delta is not suppressed or hidden just because the source row was
    # a diffstat-capped undercount (D2) - the caller shows the real stored
    # numbers, caveat handled separately from the delta itself.
    assert previous.lines_added == 500
    assert previous.lines_removed == 200
    assert previous.files_touched == 40


@pytest.mark.django_db
def test_a_row_more_than_one_week_back_is_not_treated_as_previous():
    make_repo_week("me/demo", "2026-W34", commits=8)  # two weeks back, not one
    make_repo_week("me/demo", "2026-W36", commits=3)

    assert previous_momentum_for_repo("me/demo", "2026-W36") is None


@pytest.mark.django_db
def test_only_matches_the_same_repo():
    make_repo_week("me/other", "2026-W35", commits=9)
    make_repo_week("me/demo", "2026-W36", commits=3)

    assert previous_momentum_for_repo("me/demo", "2026-W36") is None
