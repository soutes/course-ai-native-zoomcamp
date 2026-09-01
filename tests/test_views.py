"""The dashboard renders, empty and populated."""

import pytest
from django.urls import reverse

from portfolio.models import Project


@pytest.mark.django_db
def test_dashboard_renders_empty_state():
    from django.test import Client

    response = Client().get(reverse("portfolio:dashboard"))
    assert response.status_code == 200
    assert b"Nothing tracked yet" in response.content


@pytest.mark.django_db
def test_dashboard_lists_active_projects_and_their_goals():
    from django.test import Client

    Project.objects.create(repo="me/weekly", goal="Ship the triage command")
    response = Client().get(reverse("portfolio:dashboard"))
    assert b"me/weekly" in response.content
    assert b"Ship the triage command" in response.content


@pytest.mark.django_db
def test_shipped_project_leaves_the_weekly_report():
    shipped = Project.objects.create(repo="me/done", status=Project.Status.SHIPPED)
    active = Project.objects.create(repo="me/live")
    assert not shipped.in_weekly_report
    assert active.in_weekly_report
