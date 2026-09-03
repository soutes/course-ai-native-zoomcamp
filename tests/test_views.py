"""The dashboard (#36) renders the current week's stored `WeeklyReport`, or says so."""

import pytest
from django.test import Client
from django.urls import reverse

from portfolio.models import Project, WeeklyReport
from portfolio.services.week import week_label, week_window

CURRENT_WEEK = week_label(week_window())

MARKDOWN = f"""# Weekly Retro - {CURRENT_WEEK}

## What went well

- **me/weekly** - 5 commits, 3 active days, +40/-10 lines across 6 files

## What went wrong

- **me/other** - 0 commits this week, 4 weeks since its last commit - stalled

## What I'm doing

- **me/weekly** - branch `feature-x` ahead by 3 commits, open 4 days

## This week's focus

Get **me/other** committing again this week - it has been 4 weeks since its last commit.
"""

SNAPSHOT = {
    "week": CURRENT_WEEK,
    "repos": [
        {"repo": "me/weekly", "weeks_since_last_commit": 0, "stalled": False},
        {"repo": "me/other", "weeks_since_last_commit": 4, "stalled": True},
    ],
    "new_repos": [],
    "focus": "Get me/other committing again this week.",
}


def make_report(week=CURRENT_WEEK, markdown=MARKDOWN, data=None, **overrides):
    defaults = dict(week=week, markdown=markdown, data=data if data is not None else SNAPSHOT)
    defaults.update(overrides)
    return WeeklyReport.objects.create(**defaults)


@pytest.mark.django_db
def test_dashboard_renders_current_week_with_abandoned_count_and_sections():
    make_report()

    response = Client().get(reverse("portfolio:dashboard"))

    assert response.status_code == 200
    body = response.content.decode()
    assert CURRENT_WEEK in body
    assert "1" in body  # one stalled repo (me/other) in the snapshot above
    for heading in [
        "What went well",
        "What went wrong",
        "What I&#x27;m doing",
        "This week&#x27;s focus",
    ]:
        assert heading in body
    assert "5 commits" in body


@pytest.mark.django_db
def test_dashboard_shows_week_label_and_generation_timestamp():
    report = make_report()

    response = Client().get(reverse("portfolio:dashboard"))

    body = response.content.decode()
    assert CURRENT_WEEK in body
    assert str(report.generated_at.year) in body


@pytest.mark.django_db
def test_dashboard_no_current_week_data_links_to_most_recent():
    make_report(week="2020-W01", markdown="# Weekly Retro - 2020-W01\n")

    response = Client().get(reverse("portfolio:dashboard"))

    assert response.status_code == 200
    body = response.content.decode()
    assert CURRENT_WEEK in body
    assert "No report yet" in body
    assert "2020-W01" in body
    assert 'href="/retro/2020-W01/"' in body


@pytest.mark.django_db
def test_dashboard_no_reports_at_all_is_graceful_not_404():
    response = Client().get(reverse("portfolio:dashboard"))

    assert response.status_code == 200
    assert b"No retros stored yet" in response.content


@pytest.mark.django_db
def test_dashboard_links_to_the_per_week_retro_page():
    make_report()

    response = Client().get(reverse("portfolio:dashboard"))

    body = response.content.decode()
    assert f'href="/retro/{CURRENT_WEEK}/"' in body


@pytest.mark.django_db
def test_dashboard_script_in_commit_subject_is_escaped_not_executed():
    markdown = (
        f"# Weekly Retro - {CURRENT_WEEK}\n\n"
        "## What went well\n\n"
        '- **me/weekly** - latest commit: "<script>alert(1)</script>"\n\n'
        "## What went wrong\n\n"
        "- nothing\n\n"
        "## What I'm doing\n\n"
        "- nothing\n\n"
        "## This week's focus\n\n"
        "Stay safe.\n"
    )
    make_report(markdown=markdown)

    response = Client().get(reverse("portfolio:dashboard"))

    body = response.content.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


@pytest.mark.django_db
def test_dashboard_renders_with_coaching_none():
    """`WeeklyReport` never stores an LLM field - the page must render regardless
    (AGENTS.md: "`render` must work with `coaching = None`. Always.")."""
    make_report()
    response = Client().get(reverse("portfolio:dashboard"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_shipped_project_leaves_the_weekly_report():
    shipped = Project.objects.create(repo="me/done", status=Project.Status.SHIPPED)
    active = Project.objects.create(repo="me/live")
    assert not shipped.in_weekly_report
    assert active.in_weekly_report
