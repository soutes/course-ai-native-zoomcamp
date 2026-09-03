"""Custom 403/404/500 error templates (#41), placed flat under `portfolio/templates/`
per D11 so Django's default error views (which look up bare `404.html`/`403.html`/
`500.html`, not namespaced ones) actually find them.

Django's default error views only render custom templates when `DEBUG=False`, so
every test here runs under `override_settings(DEBUG=False)` - without it, a broken
or missing template would pass silently.
"""

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.views.defaults import permission_denied, server_error

from portfolio.models import WeeklyReport


@override_settings(DEBUG=False)
def test_unmatched_url_returns_404_with_custom_template():
    response = Client().get("/does-not-exist/")

    assert response.status_code == 404
    assert b"404 - not found" in response.content


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_retro_detail_404_renders_custom_template():
    """`retro_detail`'s existing Http404 (malformed week, or no stored report) is the
    same Django error path as any other 404 - not new detection logic."""
    assert WeeklyReport.objects.count() == 0

    response = Client().get(reverse("portfolio:retro_detail", args=["not-a-week"]))

    assert response.status_code == 404
    assert b"404 - not found" in response.content


@override_settings(DEBUG=False)
def test_server_error_view_renders_custom_500_template():
    """No view in this app raises unhandled exceptions on purpose, so this exercises
    Django's `handler500` (`django.views.defaults.server_error`) directly, the way
    Django itself calls it when a view raises."""
    request = RequestFactory().get("/whatever/")

    response = server_error(request)

    assert response.status_code == 500
    assert b"500 - server error" in response.content


@override_settings(DEBUG=False)
def test_permission_denied_view_renders_custom_403_template():
    """No view in this app raises `PermissionDenied` today, so this exercises Django's
    `handler403` (`django.views.defaults.permission_denied`) directly, the way Django
    itself calls it when a view raises `PermissionDenied`."""
    request = RequestFactory().get("/whatever/")

    response = permission_denied(request, PermissionDenied("forbidden"))

    assert response.status_code == 403
    assert b"403 - forbidden" in response.content
