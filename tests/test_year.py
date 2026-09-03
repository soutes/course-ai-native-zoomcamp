"""Yearly retrospective (#31, D30 in docs/decisions.md).

Covers `portfolio.services.year.year_summary` (the one shared function), the
`manage.py year` command, and the `/year/<year>/` view - all three read
`Project`/`RepoWeek` only, no GitHub call, no LLM call.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from portfolio.models import Project, RepoWeek
from portfolio.services.year import parse_year, year_summary

UTC_TZ = UTC


def make_project(repo: str, **overrides) -> Project:
    defaults = dict(status=Project.Status.ACTIVE)
    defaults.update(overrides)
    return Project.objects.create(repo=repo, **defaults)


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


TODAY = date(2026, 9, 3)  # ISO 2026-W36


# --- parse_year --------------------------------------------------------------------


def test_parse_year_accepts_four_digits():
    assert parse_year("2026") == 2026


@pytest.mark.parametrize("value", ["", "abc", "202", "20266", "-2026", "2026 ", " 2026"])
def test_parse_year_rejects_malformed_input(value):
    with pytest.raises(ValueError):
        parse_year(value)


# --- year_summary: shipped / dropped ------------------------------------------------


@pytest.mark.django_db
def test_shipped_project_appears_with_its_end_date():
    make_project(
        "me/done",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.shipped_count == 1
    assert summary.shipped[0].repo == "me/done"
    assert summary.shipped[0].end_date.date() == date(2026, 6, 1)
    assert summary.dropped == []
    assert summary.silent == []


@pytest.mark.django_db
def test_dropped_project_appears_with_its_end_date():
    make_project(
        "me/abandoned",
        status=Project.Status.DROPPED,
        status_changed_at=datetime(2026, 3, 15, tzinfo=UTC),
    )

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.dropped_count == 1
    assert summary.dropped[0].repo == "me/abandoned"
    assert summary.dropped[0].end_date.date() == date(2026, 3, 15)
    assert summary.shipped == []


@pytest.mark.django_db
def test_shipped_and_dropped_get_the_same_totals_shape():
    make_project(
        "me/a", status=Project.Status.SHIPPED, status_changed_at=datetime(2026, 1, 5, tzinfo=UTC)
    )
    make_project(
        "me/b", status=Project.Status.DROPPED, status_changed_at=datetime(2026, 2, 5, tzinfo=UTC)
    )

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.shipped_count == len(summary.shipped) == 1
    assert summary.dropped_count == len(summary.dropped) == 1


# --- year_summary: silent -----------------------------------------------------------


@pytest.mark.django_db
def test_silent_project_shows_weeks_since_last_commit():
    make_project("me/quiet", status=Project.Status.ACTIVE)
    make_repo_week("me/quiet", "2026-W20", commits=3)  # well before the W36 reference

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.silent_count == 1
    row = summary.silent[0]
    assert row.repo == "me/quiet"
    assert row.weeks_silent == 16  # W20 -> W36


@pytest.mark.django_db
def test_never_committed_project_shows_no_commit_history_not_a_number():
    make_project("me/ghost", status=Project.Status.ACTIVE)

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.silent_count == 1
    assert summary.silent[0].repo == "me/ghost"
    assert summary.silent[0].weeks_silent is None


@pytest.mark.django_db
def test_active_and_healthy_project_appears_in_no_group():
    make_project("me/healthy", status=Project.Status.ACTIVE)
    make_repo_week("me/healthy", "2026-W36", commits=2)  # committed this very reference week

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.shipped == []
    assert summary.dropped == []
    assert summary.silent == []


@pytest.mark.django_db
def test_paused_project_with_pause_in_force_is_not_silent():
    make_project(
        "me/resting",
        status=Project.Status.PAUSED,
        paused_until=date(2026, 12, 1),  # still in force at the W36 reference date
    )

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.silent == []


@pytest.mark.django_db
def test_paused_project_past_its_pause_can_be_silent():
    make_project(
        "me/resumed",
        status=Project.Status.PAUSED,
        paused_until=date(2026, 1, 1),  # expired well before the W36 reference date
    )

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.silent_count == 1
    assert summary.silent[0].repo == "me/resumed"


@pytest.mark.django_db
def test_shipped_project_never_appears_as_silent():
    make_project(
        "me/done",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2020, 1, 1, tzinfo=UTC),  # ends outside the requested year
    )

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.silent == []
    assert summary.shipped == []
    assert summary.dropped == []


# --- year_summary: ISO week-year boundary -------------------------------------------


@pytest.mark.django_db
def test_year_membership_uses_iso_week_year_not_calendar_year():
    # 2025-12-29 is a Monday whose ISO week-year is 2026 (2026-W01), not 2025.
    make_project(
        "me/boundary",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2025, 12, 29, tzinfo=UTC),
    )

    summary_2026 = year_summary(2026, UTC_TZ, today=TODAY)
    summary_2025 = year_summary(2025, UTC_TZ, today=TODAY)

    assert [row.repo for row in summary_2026.shipped] == ["me/boundary"]
    assert summary_2025.shipped == []


@pytest.mark.django_db
def test_ending_in_one_year_is_not_double_counted_in_an_earlier_silent_year():
    """A project silent in an earlier year and shipped in a later year is not a
    double-counted ending - the shipped bucket only ever holds one year."""
    make_project(
        "me/late-ship",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    summary_2026 = year_summary(2026, UTC_TZ, today=TODAY)
    summary_2025 = year_summary(2025, UTC_TZ, today=TODAY)

    assert summary_2026.shipped_count == 1
    assert summary_2025.shipped_count == 0
    assert summary_2025.dropped_count == 0


# --- year_summary: empty state -------------------------------------------------------


@pytest.mark.django_db
def test_empty_year_has_no_repo_weeks_and_no_endings():
    summary = year_summary(2019, UTC_TZ, today=TODAY)

    assert summary.is_empty is True
    assert summary.shipped == []
    assert summary.dropped == []


@pytest.mark.django_db
def test_year_with_one_ending_but_no_repo_weeks_is_not_empty():
    make_project(
        "me/solo",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    summary = year_summary(2026, UTC_TZ, today=TODAY)

    assert summary.is_empty is False
    assert summary.shipped_count == 1


@pytest.mark.django_db
def test_year_is_deterministic_across_repeated_calls():
    make_project(
        "me/done",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    make_project("me/quiet", status=Project.Status.ACTIVE)
    make_repo_week("me/quiet", "2026-W10", commits=1)

    first = year_summary(2026, UTC_TZ, today=TODAY)
    second = year_summary(2026, UTC_TZ, today=TODAY)

    assert [r.repo for r in first.shipped] == [r.repo for r in second.shipped]
    assert [(r.repo, r.weeks_silent) for r in first.silent] == [
        (r.repo, r.weeks_silent) for r in second.silent
    ]


# --- manage.py year ------------------------------------------------------------------


@pytest.mark.django_db
def test_year_command_prints_groups(capsys):
    make_project(
        "me/done",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    call_command("year", "2026", stdout=StringIO())

    out = capsys.readouterr().out
    assert "Shipped" in out
    assert "me/done" in out


@pytest.mark.django_db
def test_year_command_rejects_malformed_year():
    with pytest.raises(CommandError):
        call_command("year", "not-a-year", stdout=StringIO())


@pytest.mark.django_db
def test_year_command_empty_year_does_not_crash(capsys):
    call_command("year", "2019", stdout=StringIO())
    out = capsys.readouterr().out
    assert "Nothing recorded" in out


# --- /year/<year>/ view ---------------------------------------------------------------


@pytest.mark.django_db
def test_year_view_renders_groups_and_totals():
    make_project(
        "me/done",
        status=Project.Status.SHIPPED,
        status_changed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    make_project(
        "me/abandoned",
        status=Project.Status.DROPPED,
        status_changed_at=datetime(2026, 3, 15, tzinfo=UTC),
    )
    make_project("me/quiet", status=Project.Status.ACTIVE)
    make_repo_week("me/quiet", "2026-W10", commits=1)

    response = Client().get(reverse("portfolio:year", kwargs={"year": "2026"}))

    assert response.status_code == 200
    body = response.content.decode()
    assert "me/done" in body
    assert "me/abandoned" in body
    assert "me/quiet" in body
    # order: shipped, dropped, silent
    positions = [body.index(text) for text in ("Shipped", "Dropped", "Silent")]
    assert positions == sorted(positions)


@pytest.mark.django_db
def test_year_view_404s_for_malformed_year():
    response = Client().get(reverse("portfolio:year", kwargs={"year": "not-a-year"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_year_view_renders_empty_state_not_404():
    response = Client().get(reverse("portfolio:year", kwargs={"year": "2019"}))
    assert response.status_code == 200
    assert b"Nothing recorded" in response.content
