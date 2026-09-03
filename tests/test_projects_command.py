"""`manage.py projects` (#34) - list tracked projects grouped by status.

No GitHub, ever: these tests run with GITHUB_TOKEN/GITHUB_USER unset to prove it,
and no test touches the network.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from portfolio.models import Project


@pytest.fixture(autouse=True)
def _no_github_env(settings):
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_USER = ""


@pytest.mark.django_db
def test_lists_four_sections_in_order(capsys):
    Project.objects.create(repo="me/active-one", status=Project.Status.ACTIVE, goal="ship it")
    Project.objects.create(repo="me/paused-one", status=Project.Status.PAUSED)
    Project.objects.create(repo="me/shipped-one", status=Project.Status.SHIPPED)
    Project.objects.create(repo="me/dropped-one", status=Project.Status.DROPPED)

    call_command("projects")

    out = capsys.readouterr().out
    assert out.index("Active") < out.index("Paused on purpose")
    assert out.index("Paused on purpose") < out.index("Shipped")
    assert out.index("Shipped") < out.index("Dropped")
    for repo in ("me/active-one", "me/paused-one", "me/shipped-one", "me/dropped-one"):
        assert repo in out


@pytest.mark.django_db
def test_counts_sum_to_total(capsys):
    Project.objects.create(repo="me/a", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/b", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/c", status=Project.Status.PAUSED)

    call_command("projects")

    out = capsys.readouterr().out
    assert "Active (2)" in out
    assert "Paused on purpose (1)" in out
    assert "Shipped (0)" in out
    assert "Dropped (0)" in out
    assert Project.objects.count() == 3


@pytest.mark.django_db
def test_missing_status_changed_at_shows_placeholder(capsys):
    Project.objects.create(repo="me/fresh", status=Project.Status.ACTIVE)

    call_command("projects")

    out = capsys.readouterr().out
    assert "changed -" in out


@pytest.mark.django_db
def test_paused_shows_paused_until_or_placeholder(capsys):
    Project.objects.create(
        repo="me/paused-dated",
        status=Project.Status.PAUSED,
        paused_until=date(2026, 12, 1),
    )
    Project.objects.create(repo="me/paused-open", status=Project.Status.PAUSED)

    call_command("projects")

    out = capsys.readouterr().out
    assert "paused until 2026-12-01" in out
    assert "paused until -" in out


@pytest.mark.django_db
def test_shipped_and_dropped_show_labelled_end_date(capsys):
    from portfolio.services.lifecycle import apply_transition

    shipped = Project.objects.create(repo="me/shipped", status=Project.Status.ACTIVE)
    apply_transition(shipped, Project.Status.SHIPPED, reason="")
    shipped.refresh_from_db()

    call_command("projects")

    out = capsys.readouterr().out
    ended_line = [line for line in out.splitlines() if "me/shipped" in line][0]
    assert "ended" in ended_line
    assert shipped.status_changed_at.date().isoformat() in ended_line


@pytest.mark.django_db
def test_status_filter_prints_only_that_group(capsys):
    Project.objects.create(repo="me/active-one", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/shipped-one", status=Project.Status.SHIPPED)

    call_command("projects", "--status", "active")

    out = capsys.readouterr().out
    assert "me/active-one" in out
    assert "me/shipped-one" not in out
    assert "Shipped" not in out


@pytest.mark.django_db
def test_invalid_status_raises_command_error():
    with pytest.raises(CommandError, match="active, paused, shipped, dropped"):
        call_command("projects", "--status", "bogus")


@pytest.mark.django_db
def test_empty_goal_shows_placeholder(capsys):
    Project.objects.create(repo="me/no-goal", status=Project.Status.ACTIVE, goal="")

    call_command("projects")

    out = capsys.readouterr().out
    assert "(no goal set)" in out


@pytest.mark.django_db
def test_zero_projects_shows_empty_state_not_crash(capsys):
    call_command("projects")

    out = capsys.readouterr().out
    assert "/admin/" in out


@pytest.mark.django_db
def test_zero_projects_in_filtered_group_shows_empty_state(capsys):
    Project.objects.create(repo="me/active-one", status=Project.Status.ACTIVE)

    call_command("projects", "--status", "dropped")

    out = capsys.readouterr().out
    assert "/admin/" in out
    assert "me/active-one" not in out


@pytest.mark.django_db
def test_goal_with_brackets_is_escaped_not_interpreted_as_markup(capsys):
    Project.objects.create(
        repo="me/bracket-goal", status=Project.Status.ACTIVE, goal="Ship [beta] by Friday"
    )

    call_command("projects")

    out = capsys.readouterr().out
    assert "Ship [beta] by Friday" in out


def test_projects_source_does_not_import_github():
    import inspect

    import portfolio.management.commands.projects as projects_module

    source = inspect.getsource(projects_module)
    assert "portfolio.services.github" not in source
    assert "GITHUB_TOKEN" not in source
    assert "GITHUB_USER" not in source
