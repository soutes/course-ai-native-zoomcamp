"""The retro web page (#17) - reads a stored `WeeklyReport` row, no network."""

import pytest
from django.test import Client
from django.urls import reverse

from portfolio.models import WeeklyReport

MARKDOWN = """# Weekly Retro - 2026-W36

## What went well

- **me/weekly** - 5 commits, 3 active days, +40/-10 lines across 6 files

## What went wrong

- **me/other** - 0 commits this week, 2 weeks since its last commit

## What I'm doing

- **me/weekly** - branch `feature-x` ahead by 3 commits, open 4 days

## This week's focus

Get **me/other** committing again this week - it has been 2 weeks since its last commit.
"""


def make_report(week="2026-W36", markdown=MARKDOWN, **overrides):
    defaults = dict(week=week, markdown=markdown, data={})
    defaults.update(overrides)
    return WeeklyReport.objects.create(**defaults)


@pytest.mark.django_db
def test_retro_detail_renders_stored_week():
    make_report()

    response = Client().get(reverse("portfolio:retro_detail", kwargs={"week": "2026-W36"}))

    assert response.status_code == 200
    body = response.content.decode()
    for heading in [
        "What went well",
        "What went wrong",
        "What I&#x27;m doing",
        "This week&#x27;s focus",
    ]:
        assert heading in body
    # A number from the stored markdown makes it through unchanged.
    assert "5 commits" in body
    assert "2026-W36" in body


@pytest.mark.django_db
def test_retro_detail_404_when_week_has_no_report():
    response = Client().get(reverse("portfolio:retro_detail", kwargs={"week": "2026-W37"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_retro_detail_404_for_malformed_week():
    response = Client().get(reverse("portfolio:retro_detail", kwargs={"week": "2026-W99"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_retro_detail_404_for_garbage_week():
    response = Client().get(reverse("portfolio:retro_detail", kwargs={"week": "not-a-week"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_retro_list_orders_newest_first_and_links_each_week():
    make_report(week="2026-W10", markdown="# Weekly Retro - 2026-W10\n")
    make_report(week="2026-W36", markdown="# Weekly Retro - 2026-W36\n")
    make_report(week="2025-W52", markdown="# Weekly Retro - 2025-W52\n")

    response = Client().get(reverse("portfolio:retro_list"))

    assert response.status_code == 200
    body = response.content.decode()
    positions = [body.index(week) for week in ("2026-W36", "2026-W10", "2025-W52")]
    assert positions == sorted(positions)
    for week in ("2026-W36", "2026-W10", "2025-W52"):
        assert f'href="/retro/{week}/"' in body


@pytest.mark.django_db
def test_retro_list_empty_state():
    response = Client().get(reverse("portfolio:retro_list"))
    assert response.status_code == 200
    assert b"No retros stored yet" in response.content


@pytest.mark.django_db
def test_script_in_commit_subject_is_escaped_not_executed():
    markdown = (
        "# Weekly Retro - 2026-W36\n\n"
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

    response = Client().get(reverse("portfolio:retro_detail", kwargs={"week": "2026-W36"}))

    body = response.content.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


@pytest.mark.django_db
def test_retro_detail_renders_with_coaching_none():
    """`WeeklyReport` never stores an LLM field - the page must render regardless,
    exactly like the command with `coaching = None` (AGENTS.md)."""
    make_report()
    response = Client().get(reverse("portfolio:retro_detail", kwargs={"week": "2026-W36"}))
    assert response.status_code == 200
