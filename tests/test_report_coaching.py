"""`manage.py report`'s coaching wiring (#27, D26).

No real network call is ever made in this file. Every scenario either never
imports `portfolio.coach` at all (`--no-llm`) or has `portfolio.coach.build_client`
/`portfolio.coach.get_coaching` monkeypatched with a fake - `httpx.Client.post` is
spied on in every test to prove that too.
"""

from __future__ import annotations

import sys
from datetime import UTC, timedelta

import httpx
import pytest
from django.core.management import call_command

from portfolio.management.commands import report as report_cmd
from portfolio.models import Project, WeeklyReport
from portfolio.services.types import Repo
from portfolio.services.week import week_window

UTC_TZ = UTC
WEEK = "2026-W35"  # Mon 2026-08-24 .. Sun 2026-08-30
WINDOW = week_window(WEEK, tz=UTC_TZ)


def make_gh_repo(full_name) -> Repo:
    name = full_name.split("/", 1)[1]
    return Repo(
        name=name,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        private=False,
        fork=False,
        archived=False,
        description=None,
        topics=[],
        license=None,
        default_branch="main",
        created_at=WINDOW[0] - timedelta(days=400),
        pushed_at=WINDOW[0] - timedelta(days=1),
        stars=0,
        forks=0,
    )


class FakeGitHub:
    """Stands in for `portfolio.services.github.GitHub`. No network, ever."""

    def __init__(self, repos):
        self._repos = repos

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def my_repos(self):
        return iter(self._repos)

    def commits_in_window(self, full_name, window, emails):
        return []

    def commit_diffstat(self, full_name, sha):
        from portfolio.services.types import CommitStat

        return CommitStat(sha=sha, additions=0, deletions=0, files_changed=0)

    def unmerged_branches(self, full_name, default_branch):
        return []

    def open_pull_requests(self, full_name, github_user):
        return []

    def tree(self, full_name, default_branch):
        from portfolio.services.types import TreeListing

        return TreeListing(paths=[], truncated=False)

    def has_release(self, full_name):
        return False

    def tags(self, full_name):
        return []

    def readme_text(self, full_name):
        return None


def _install_fake_gh(monkeypatch, fake_gh) -> None:
    monkeypatch.setattr(report_cmd, "GitHub", lambda token, cache: fake_gh)


def _configure(settings):
    settings.GITHUB_USER = "me"
    settings.GITHUB_TOKEN = "fake-token"
    settings.GITHUB_EMAILS = "me@example.com"
    settings.TIME_ZONE = "UTC"


def _forbid_llm_requests(monkeypatch) -> list[str]:
    """Spy on `httpx.Client.post` so any real LLM request fails the test loudly."""
    calls: list[str] = []

    def _boom(self, url, *args, **kwargs):
        calls.append(url)
        raise AssertionError(f"httpx.Client.post must never be called (got {url!r})")

    monkeypatch.setattr(httpx.Client, "post", _boom)
    return calls


@pytest.mark.django_db
def test_no_llm_flag_never_imports_portfolio_coach(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    settings.LLM_API_KEY = ""
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    _install_fake_gh(monkeypatch, FakeGitHub(repos=[make_gh_repo("me/demo")]))
    _forbid_llm_requests(monkeypatch)

    sys.modules.pop("portfolio.coach", None)

    call_command("report", "--week", WEEK, "--no-llm")

    assert "portfolio.coach" not in sys.modules

    row = WeeklyReport.objects.get(week=WEEK)
    for heading in (
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
    ):
        assert heading in row.markdown


@pytest.mark.django_db
def test_no_llm_flag_renders_with_key_totally_unset(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    settings.LLM_API_KEY = ""
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    _install_fake_gh(monkeypatch, FakeGitHub(repos=[make_gh_repo("me/demo")]))
    _forbid_llm_requests(monkeypatch)

    call_command("report", "--week", WEEK, "--no-llm")  # must not raise, exit 0

    assert WeeklyReport.objects.filter(week=WEEK).exists()


@pytest.mark.django_db
def test_no_flag_no_key_renders_with_one_warning_and_exits_zero(
    monkeypatch, settings, tmp_path, capsys
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    settings.LLM_API_KEY = ""
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    _install_fake_gh(monkeypatch, FakeGitHub(repos=[make_gh_repo("me/demo")]))
    _forbid_llm_requests(monkeypatch)

    call_command("report", "--week", WEEK)  # no --no-llm

    captured = capsys.readouterr()
    assert captured.out.count("Skipping coaching") == 1
    assert "LLM_API_KEY is not set" in captured.out

    row = WeeklyReport.objects.get(week=WEEK)
    assert row.data["week"] == WEEK


@pytest.mark.django_db
def test_no_flag_key_set_and_get_coaching_returns_none_warns_once(
    monkeypatch, settings, tmp_path, capsys
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    settings.LLM_API_KEY = "fake-key"
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    _install_fake_gh(monkeypatch, FakeGitHub(repos=[make_gh_repo("me/demo")]))
    _forbid_llm_requests(monkeypatch)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    import portfolio.coach as coach

    monkeypatch.setattr(coach, "build_client", lambda: FakeClient())
    monkeypatch.setattr(coach, "get_coaching", lambda report, client: None)

    call_command("report", "--week", WEEK)

    captured = capsys.readouterr()
    assert captured.out.count("Skipping coaching") == 1
    assert "did not return usable advice" in captured.out

    row = WeeklyReport.objects.get(week=WEEK)
    assert row.data["week"] == WEEK


@pytest.mark.django_db
def test_no_flag_key_set_and_success_threads_coaching_result_with_no_warning(
    monkeypatch, settings, tmp_path, capsys
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    settings.LLM_API_KEY = "fake-key"
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    _install_fake_gh(monkeypatch, FakeGitHub(repos=[make_gh_repo("me/demo")]))
    _forbid_llm_requests(monkeypatch)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    import portfolio.coach as coach
    from portfolio.services import render as render_module

    sentinel = coach.CoachingResult(advice={"me/demo": "steady progress"}, unavailable=[])

    def fake_get_coaching(report, client):
        return sentinel

    monkeypatch.setattr(coach, "build_client", lambda: FakeClient())
    monkeypatch.setattr(coach, "get_coaching", fake_get_coaching)

    captured_data = {}
    real_render_report = render_module.render_report

    def spy_render_report(data):
        captured_data["data"] = data
        return real_render_report(data)

    monkeypatch.setattr(report_cmd.render, "render_report", spy_render_report)

    call_command("report", "--week", WEEK)

    captured = capsys.readouterr()
    assert "Skipping coaching" not in captured.out

    # The real CoachingResult made it onto WeeklyReportData.coaching.
    assert captured_data["data"].coaching is sentinel

    row = WeeklyReport.objects.get(week=WEEK)
    assert row.data["week"] == WEEK
