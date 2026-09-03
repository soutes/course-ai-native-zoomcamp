"""`manage.py report` (#16) - command wiring, tested against a fake GitHub client.
No network, ever. The rendering rules themselves are covered, database- and
network-free, in `tests/test_report_render.py`.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from portfolio.management.commands import report as report_cmd
from portfolio.models import Project, RepoWeek, WeeklyReport
from portfolio.services.types import Commit, CommitStat, OpenPullRequest, Repo, UnmergedBranch
from portfolio.services.week import week_label, week_window

UTC_TZ = UTC
WEEK = "2026-W35"  # Mon 2026-08-24 .. Sun 2026-08-30
WINDOW = week_window(WEEK, tz=UTC_TZ)


def make_gh_repo(full_name, *, created_at=None, default_branch="main") -> Repo:
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
        default_branch=default_branch,
        created_at=created_at or (WINDOW[0] - timedelta(days=400)),
        pushed_at=WINDOW[0] - timedelta(days=1),
        stars=0,
        forks=0,
    )


class FakeGitHub:
    """Stands in for `portfolio.services.github.GitHub`. No network, ever."""

    def __init__(
        self,
        repos: list[Repo],
        commits: dict[str, list[Commit]] | None = None,
        diffstats: dict[str, CommitStat] | None = None,
        branches: dict[str, list[UnmergedBranch]] | None = None,
        prs: dict[str, list[OpenPullRequest]] | None = None,
    ):
        self._repos = repos
        self._commits = commits or {}
        self._diffstats = diffstats or {}
        self._branches = branches or {}
        self._prs = prs or {}
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def my_repos(self):
        self.calls.append("my_repos")
        return iter(self._repos)

    def commits_in_window(self, full_name, window, emails):
        self.calls.append(f"commits_in_window {full_name}")
        return list(self._commits.get(full_name, []))

    def commit_diffstat(self, full_name, sha):
        default = CommitStat(sha=sha, additions=0, deletions=0, files_changed=0)
        return self._diffstats.get(sha, default)

    def unmerged_branches(self, full_name, default_branch):
        return list(self._branches.get(full_name, []))

    def open_pull_requests(self, full_name, github_user):
        return list(self._prs.get(full_name, []))


def make_commit(sha, *, day, subject="work") -> Commit:
    return Commit(sha=sha, authored_at=WINDOW[0] + timedelta(days=day), subject=subject)


def _install_fake_gh(monkeypatch, fake_gh) -> None:
    monkeypatch.setattr(report_cmd, "GitHub", lambda token, cache: fake_gh)


def _configure(settings):
    settings.GITHUB_USER = "me"
    settings.GITHUB_TOKEN = "fake-token"
    settings.GITHUB_EMAILS = "me@example.com"
    settings.TIME_ZONE = "UTC"


# --- WeeklyReport persistence -------------------------------------------------------


@pytest.mark.django_db
def test_report_persists_a_weekly_report_row(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/demo")],
        commits={"me/demo": [make_commit("s1", day=1)]},
        diffstats={"s1": CommitStat(sha="s1", additions=10, deletions=2, files_changed=3)},
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/demo" in row.markdown
    assert "## This week's focus" in row.markdown
    assert row.data["week"] == WEEK


@pytest.mark.django_db
def test_rerunning_the_same_week_updates_not_duplicates(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    fake_gh_1 = FakeGitHub(
        repos=[make_gh_repo("me/demo")],
        commits={"me/demo": [make_commit("s1", day=1)]},
    )
    _install_fake_gh(monkeypatch, fake_gh_1)
    call_command("report", "--week", WEEK)
    assert WeeklyReport.objects.filter(week=WEEK).count() == 1
    first_markdown = WeeklyReport.objects.get(week=WEEK).markdown

    fake_gh_2 = FakeGitHub(
        repos=[make_gh_repo("me/demo")],
        commits={"me/demo": [make_commit("s1", day=1), make_commit("s2", day=2)]},
    )
    _install_fake_gh(monkeypatch, fake_gh_2)
    call_command("report", "--week", WEEK, "--refresh")

    assert WeeklyReport.objects.filter(week=WEEK).count() == 1
    second_markdown = WeeklyReport.objects.get(week=WEEK).markdown
    assert "2 commit" in second_markdown
    assert second_markdown != first_markdown

    # RepoWeek is updated in place too, same rule.
    assert RepoWeek.objects.filter(repo="me/demo", week=WEEK).count() == 1
    assert RepoWeek.objects.get(repo="me/demo", week=WEEK).commits == 2


# --- --week / --repo / --out ---------------------------------------------------------


@pytest.mark.django_db
def test_no_week_flag_uses_the_current_iso_week(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    fake_gh = FakeGitHub(repos=[make_gh_repo("me/demo")])
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report")

    current_week = week_label(week_window(tz=ZoneInfo(settings.TIME_ZONE)))
    assert WeeklyReport.objects.filter(week=current_week).exists()


@pytest.mark.django_db
def test_repo_flag_limits_the_report_to_one_repo(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo-one", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/demo-two", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/demo-one"), make_gh_repo("me/demo-two")],
        commits={
            "me/demo-one": [make_commit("s1", day=1)],
            "me/demo-two": [make_commit("s2", day=1)],
        },
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK, "--repo", "me/demo-one")

    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/demo-one" in row.markdown
    assert "me/demo-two" not in row.markdown
    assert "commits_in_window me/demo-two" not in fake_gh.calls


@pytest.mark.django_db
def test_repo_flag_for_an_untracked_repo_raises_command_error(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    fake_gh = FakeGitHub(repos=[])
    _install_fake_gh(monkeypatch, fake_gh)

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("report", "--week", WEEK, "--repo", "me/nope")


@pytest.mark.django_db
def test_shipped_and_dropped_projects_are_absent(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/active", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/shipped", status=Project.Status.SHIPPED)
    Project.objects.create(repo="me/dropped", status=Project.Status.DROPPED)

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/active")])
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/active" in row.markdown
    assert "me/shipped" not in row.markdown
    assert "me/dropped" not in row.markdown
    assert "commits_in_window me/shipped" not in fake_gh.calls
    assert "commits_in_window me/dropped" not in fake_gh.calls


@pytest.mark.django_db
def test_paused_project_is_silenced(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/active", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/paused", status=Project.Status.PAUSED, paused_until=None)

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/active")])
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/paused" not in row.markdown


@pytest.mark.django_db
def test_out_flag_writes_plain_markdown_to_file(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    fake_gh = FakeGitHub(repos=[make_gh_repo("me/demo")])
    _install_fake_gh(monkeypatch, fake_gh)

    out_file = tmp_path / "retro.md"
    call_command("report", "--week", WEEK, "--out", str(out_file))

    content = out_file.read_text(encoding="utf-8")
    assert "# Weekly Retro - 2026-W35" in content
    assert "me/demo" in content
    # Plain markdown - no Rich console-markup artifacts.
    assert "[bold" not in content


# --- a week where nothing at all happened still exits 0 ----------------------------


@pytest.mark.django_db
def test_empty_week_still_exits_zero_and_renders_all_sections(
    monkeypatch, settings, tmp_path, capsys
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    fake_gh = FakeGitHub(repos=[])
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)  # must not raise / must not sys.exit

    row = WeeklyReport.objects.get(week=WEEK)
    for heading in (
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
    ):
        assert heading in row.markdown


# --- missing configuration --------------------------------------------------------


@pytest.mark.django_db
def test_missing_github_user_raises_command_error(settings):
    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = "x"
    settings.GITHUB_EMAILS = "a@b.com"

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("report")


@pytest.mark.django_db
def test_missing_github_emails_raises_command_error(settings):
    settings.GITHUB_USER = "me"
    settings.GITHUB_TOKEN = "x"
    settings.GITHUB_EMAILS = ""

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("report")


# --- bracket-containing dynamic text does not crash the Rich terminal render -------


@pytest.mark.django_db
def test_pr_title_with_brackets_does_not_crash_or_get_swallowed(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/demo")],
        commits={"me/demo": [make_commit("s1", day=1)]},
        prs={
            "me/demo": [
                OpenPullRequest(
                    number=9, title="[urgent] fix it", created_at=WINDOW[0], draft=False
                )
            ]
        },
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)  # must not raise

    row = WeeklyReport.objects.get(week=WEEK)
    assert "[urgent] fix it" in row.markdown
