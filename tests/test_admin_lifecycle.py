"""Django admin lifecycle actions (#19) - the same three transitions as
`manage.py ack`, exposed as bulk actions on the `Project` list view.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from portfolio.models import Project


@pytest.fixture
def admin_client(db):
    User = get_user_model()
    User.objects.create_superuser(username="admin", email="admin@example.com", password="pw")
    client = Client()
    client.login(username="admin", password="pw")
    return client


@pytest.mark.django_db
def test_mark_shipped_action_transitions_selected_projects(admin_client):
    p1 = Project.objects.create(repo="me/one", status=Project.Status.ACTIVE)
    p2 = Project.objects.create(repo="me/two", status=Project.Status.ACTIVE)

    url = reverse("admin:portfolio_project_changelist")
    response = admin_client.post(
        url,
        {
            "action": "mark_shipped",
            "_selected_action": [str(p1.pk), str(p2.pk)],
        },
        follow=True,
    )
    assert response.status_code == 200

    p1.refresh_from_db()
    p2.refresh_from_db()
    assert p1.status == Project.Status.SHIPPED
    assert p2.status == Project.Status.SHIPPED
    assert p1.status_changed_at is not None


@pytest.mark.django_db
def test_mark_dropped_action(admin_client):
    p1 = Project.objects.create(repo="me/one", status=Project.Status.ACTIVE)

    url = reverse("admin:portfolio_project_changelist")
    admin_client.post(
        url,
        {"action": "mark_dropped", "_selected_action": [str(p1.pk)]},
        follow=True,
    )

    p1.refresh_from_db()
    assert p1.status == Project.Status.DROPPED


@pytest.mark.django_db
def test_mark_paused_action_redirects_to_a_date_form(admin_client):
    p1 = Project.objects.create(repo="me/one", status=Project.Status.ACTIVE)

    url = reverse("admin:portfolio_project_changelist")
    response = admin_client.post(
        url,
        {"action": "mark_paused", "_selected_action": [str(p1.pk)]},
    )

    # A redirect to the intermediate form, not an immediate open-ended pause.
    assert response.status_code == 302
    assert response.url == reverse("admin:portfolio_project_pause")

    p1.refresh_from_db()
    assert p1.status == Project.Status.ACTIVE  # unchanged until the date is submitted


@pytest.mark.django_db
def test_pause_form_requires_a_date_and_then_applies_it(admin_client):
    p1 = Project.objects.create(repo="me/one", status=Project.Status.ACTIVE)

    changelist_url = reverse("admin:portfolio_project_changelist")
    admin_client.post(
        changelist_url,
        {"action": "mark_paused", "_selected_action": [str(p1.pk)]},
    )

    pause_url = reverse("admin:portfolio_project_pause")

    # No date submitted: the form re-renders, nothing changes.
    response = admin_client.post(pause_url, {"paused_until": "", "reason": ""})
    assert response.status_code == 200
    p1.refresh_from_db()
    assert p1.status == Project.Status.ACTIVE

    # A real date: the transition applies.
    response = admin_client.post(
        pause_url, {"paused_until": "2026-11-01", "reason": "waiting on X"}
    )
    assert response.status_code == 302
    p1.refresh_from_db()
    assert p1.status == Project.Status.PAUSED
    assert p1.paused_until == date(2026, 11, 1)
    assert p1.status_reason == "waiting on X"
