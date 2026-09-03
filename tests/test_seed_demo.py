"""`manage.py seed_demo` populates a reviewable, offline demo portfolio."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from portfolio.models import Project, TriageDecision, TriageRun


@pytest.mark.django_db
def test_seed_demo_creates_at_least_six_projects_covering_every_status():
    call_command("seed_demo")

    assert Project.objects.count() >= 6
    statuses = set(Project.objects.values_list("status", flat=True))
    assert statuses == {
        Project.Status.ACTIVE,
        Project.Status.PAUSED,
        Project.Status.SHIPPED,
        Project.Status.DROPPED,
    }
    for project in Project.objects.all():
        assert "/" in project.repo
        assert project.goal.strip()


@pytest.mark.django_db
def test_seed_demo_active_projects_read_as_a_mix_of_stalled_and_fresh():
    call_command("seed_demo")

    four_weeks_ago = timezone.now() - timedelta(weeks=4)
    active = Project.objects.filter(status=Project.Status.ACTIVE)
    stalled = [
        p for p in active if p.status_changed_at < four_weeks_ago and p.goal_set_at < four_weeks_ago
    ]
    fresh = [
        p
        for p in active
        if p.status_changed_at >= four_weeks_ago and p.goal_set_at >= four_weeks_ago
    ]
    assert len(stalled) >= 2
    assert len(fresh) >= 1


@pytest.mark.django_db
def test_seed_demo_paused_projects_exercise_both_in_weekly_report_branches():
    call_command("seed_demo")

    paused = Project.objects.filter(status=Project.Status.PAUSED)
    future_or_unset = [p for p in paused if not p.in_weekly_report]
    past_or_none = [p for p in paused if p.in_weekly_report]
    # future paused_until -> silenced (not in_weekly_report)
    assert any(p.paused_until and p.paused_until > timezone.now().date() for p in future_or_unset)
    # unset or past paused_until -> visible again (in_weekly_report)
    assert any(p.paused_until is None for p in paused)
    assert any(p.paused_until and p.paused_until < timezone.now().date() for p in past_or_none)


@pytest.mark.django_db
def test_seed_demo_creates_triage_history():
    call_command("seed_demo")

    assert TriageRun.objects.count() >= 1
    assert TriageDecision.objects.filter(run__in=TriageRun.objects.all()).count() >= 1


@pytest.mark.django_db
def test_seed_demo_is_idempotent():
    call_command("seed_demo")
    first_count = Project.objects.count()
    first_run_count = TriageRun.objects.count()

    call_command("seed_demo")  # must not raise on Project.repo's unique constraint

    assert Project.objects.count() == first_count
    assert TriageRun.objects.count() == first_run_count


@pytest.mark.django_db
def test_seed_demo_populates_the_dashboard():
    from django.test import Client
    from django.urls import reverse

    call_command("seed_demo")
    response = Client().get(reverse("portfolio:dashboard"))

    assert response.status_code == 200
    content = response.content
    assert b"Nothing tracked yet" not in content
    assert b"No triage applied yet" not in content
