"""The public `/projects/` page (#43) - tracked projects grouped by status plus a
triage-history summary, no login, no GitHub call, no LLM call.
"""

import pytest
from django.test import Client
from django.urls import reverse

from portfolio.models import Project, TriageDecision, TriageRun


@pytest.mark.django_db
def test_projects_page_groups_by_status_with_correct_counts():
    Project.objects.create(repo="me/active-1", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/active-2", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/paused-1", status=Project.Status.PAUSED)
    Project.objects.create(repo="me/shipped-1", status=Project.Status.SHIPPED)
    Project.objects.create(repo="me/dropped-1", status=Project.Status.DROPPED)

    response = Client().get(reverse("portfolio:projects"))

    assert response.status_code == 200
    body = response.content.decode()
    for repo in ["me/active-1", "me/active-2", "me/paused-1", "me/shipped-1", "me/dropped-1"]:
        assert repo in body

    # Section counts.
    assert "(2)" in body  # active
    assert "(1)" in body  # paused / shipped / dropped each have 1

    # Group counts sum to the total.
    assert Project.objects.count() == 5
    assert "5 tracked project" in body


@pytest.mark.django_db
def test_projects_page_shows_goal_or_placeholder_and_status_changed_at():
    Project.objects.create(
        repo="me/with-goal",
        goal="Ship the thing",
        status=Project.Status.ACTIVE,
    )
    Project.objects.create(repo="me/no-goal", goal="", status=Project.Status.ACTIVE)

    response = Client().get(reverse("portfolio:projects"))

    body = response.content.decode()
    assert "Ship the thing" in body
    assert "no goal set" in body


@pytest.mark.django_db
def test_paused_project_shows_paused_until_when_set():
    Project.objects.create(
        repo="me/paused",
        status=Project.Status.PAUSED,
        paused_until="2026-12-31",
    )

    response = Client().get(reverse("portfolio:projects"))

    body = response.content.decode()
    assert "2026-12-31" in body


@pytest.mark.django_db
def test_zero_projects_empty_state_points_to_admin():
    response = Client().get(reverse("portfolio:projects"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "No projects tracked yet" in body
    assert "/admin/" in body


@pytest.mark.django_db
def test_zero_triage_runs_empty_state():
    response = Client().get(reverse("portfolio:projects"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "No triage applied yet" in body
    assert "manage.py triage" in body


@pytest.mark.django_db
def test_triage_history_shows_date_and_count_never_repo_or_reason():
    run = TriageRun.objects.create()
    TriageDecision.objects.create(
        run=run,
        repo="me/secret-repo",
        action=TriageDecision.Action.HIDE,
        reason="dead weight, embarrassing prototype",
    )
    TriageDecision.objects.create(
        run=run,
        repo="me/another-secret",
        action=TriageDecision.Action.HIDE,
        reason="another private reason",
    )

    response = Client().get(reverse("portfolio:projects"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "2 repo" in body  # aggregate count of decisions that hid a repo
    assert "me/secret-repo" not in body
    assert "me/another-secret" not in body
    assert "dead weight, embarrassing prototype" not in body
    assert "another private reason" not in body


@pytest.mark.django_db
def test_goal_and_status_reason_html_is_escaped_not_executed():
    Project.objects.create(
        repo="me/xss",
        goal="<script>alert('goal')</script> & <b>bold</b>",
        status=Project.Status.SHIPPED,
        status_reason="<img src=x onerror=alert(1)> & done",
        status_changed_at="2026-01-01T00:00:00Z",
    )

    response = Client().get(reverse("portfolio:projects"))

    body = response.content.decode()
    assert "<script>alert" not in body
    assert "<img src=x onerror" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body
    assert "&amp;" in body


@pytest.mark.django_db
def test_projects_page_makes_no_network_call(monkeypatch):
    """No GitHub/LLM call - the page reads only Project/TriageRun/TriageDecision."""
    import portfolio.services.github as github

    def boom(*args, **kwargs):
        raise AssertionError("projects view must not touch the network")

    monkeypatch.setattr(github, "list_repos", boom, raising=False)

    Project.objects.create(repo="me/offline", status=Project.Status.ACTIVE)
    response = Client().get(reverse("portfolio:projects"))
    assert response.status_code == 200
