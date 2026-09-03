"""`manage.py ack` (#19) - lifecycle transitions. No GitHub, ever: these tests
run with GITHUB_TOKEN/GITHUB_USER unset to prove it.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from portfolio.models import Project


@pytest.fixture(autouse=True)
def _no_github_env(settings):
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_USER = ""


@pytest.mark.django_db
def test_shipped_sets_status_and_timestamp():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    before = timezone.now()

    call_command("ack", "me/demo", "--shipped")

    project = Project.objects.get(repo="me/demo")
    assert project.status == Project.Status.SHIPPED
    assert project.status_changed_at >= before
    assert project.status_reason == ""


@pytest.mark.django_db
def test_pause_sets_status_and_paused_until():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    call_command("ack", "me/demo", "--pause", "2026-11-01")

    project = Project.objects.get(repo="me/demo")
    assert project.status == Project.Status.PAUSED
    assert project.paused_until == date(2026, 11, 1)


@pytest.mark.django_db
def test_drop_sets_status():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    call_command("ack", "me/demo", "--drop")

    project = Project.objects.get(repo="me/demo")
    assert project.status == Project.Status.DROPPED


@pytest.mark.django_db
def test_reason_is_stored_verbatim():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    call_command("ack", "me/demo", "--shipped", "--reason", "v1 shipped to prod")

    project = Project.objects.get(repo="me/demo")
    assert project.status_reason == "v1 shipped to prod"


@pytest.mark.django_db
def test_reason_defaults_to_blank():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    call_command("ack", "me/demo", "--drop")

    assert Project.objects.get(repo="me/demo").status_reason == ""


@pytest.mark.django_db
def test_bad_pause_date_raises_command_error_and_changes_nothing():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE, status_reason="old")

    with pytest.raises(CommandError, match="back in November"):
        call_command("ack", "me/demo", "--pause", "back in November")

    project = Project.objects.get(repo="me/demo")
    assert project.status == Project.Status.ACTIVE
    assert project.status_reason == "old"
    assert project.paused_until is None


@pytest.mark.django_db
def test_no_transition_flag_raises_command_error():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    with pytest.raises(CommandError, match="--shipped, --pause, --drop"):
        call_command("ack", "me/demo")


@pytest.mark.django_db
def test_two_transition_flags_raises_command_error_naming_both():
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    with pytest.raises(CommandError, match="--shipped") as excinfo:
        call_command("ack", "me/demo", "--shipped", "--drop")
    assert "--drop" in str(excinfo.value)


@pytest.mark.django_db
def test_unknown_repo_raises_clean_error_and_creates_no_row():
    with pytest.raises(CommandError, match="no such project: me/ghost"):
        call_command("ack", "me/ghost", "--shipped")

    assert not Project.objects.filter(repo="me/ghost").exists()


@pytest.mark.django_db
def test_reacking_overwrites_in_place_no_new_row(settings):
    project = Project.objects.create(
        repo="me/demo", status=Project.Status.SHIPPED, status_reason="shipped v1"
    )
    first_changed_at = project.status_changed_at

    call_command("ack", "me/demo", "--pause", "2026-12-01", "--reason", "reopened")

    assert Project.objects.filter(repo="me/demo").count() == 1
    project.refresh_from_db()
    assert project.status == Project.Status.PAUSED
    assert project.status_reason == "reopened"
    assert project.paused_until == date(2026, 12, 1)
    assert first_changed_at is None or project.status_changed_at >= first_changed_at


@pytest.mark.django_db
def test_reason_with_rich_markup_is_escaped_not_crashing(capsys):
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    call_command("ack", "me/demo", "--shipped", "--reason", "[bold]done[/bold]")

    out = capsys.readouterr().out
    assert "[bold]done[/bold]" in out


def test_ack_source_does_not_import_github():
    import inspect

    import portfolio.management.commands.ack as ack_module

    source = inspect.getsource(ack_module)
    assert "portfolio.services.github" not in source
    assert "GITHUB_TOKEN" not in source
    assert "GITHUB_USER" not in source
