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
from portfolio.services.types import (
    Commit,
    CommitStat,
    OpenPullRequest,
    Repo,
    TreeListing,
    UnmergedBranch,
)
from portfolio.services.week import week_label, week_window

UTC_TZ = UTC
WEEK = "2026-W35"  # Mon 2026-08-24 .. Sun 2026-08-30
WINDOW = week_window(WEEK, tz=UTC_TZ)


def make_gh_repo(full_name, *, created_at=None, default_branch="main", description=None) -> Repo:
    name = full_name.split("/", 1)[1]
    return Repo(
        name=name,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        private=False,
        fork=False,
        archived=False,
        description=description,
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
        trees: dict[str, TreeListing] | None = None,
        releases: dict[str, bool] | None = None,
        tags: dict[str, list[str]] | None = None,
        readmes: dict[str, str | None] | None = None,
    ):
        self._repos = repos
        self._commits = commits or {}
        self._diffstats = diffstats or {}
        self._branches = branches or {}
        self._prs = prs or {}
        self._trees = trees or {}
        self._releases = releases or {}
        self._tags = tags or {}
        self._readmes = readmes or {}
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

    def tree(self, full_name, default_branch):
        return self._trees.get(full_name, TreeListing(paths=[], truncated=False))

    def has_release(self, full_name):
        self.calls.append(f"has_release {full_name}")
        return self._releases.get(full_name, False)

    def tags(self, full_name):
        self.calls.append(f"tags {full_name}")
        return list(self._tags.get(full_name, []))

    def readme_text(self, full_name):
        self.calls.append(f"readme_text {full_name}")
        return self._readmes.get(full_name)


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

    out_file = tmp_path / "one-repo.md"
    call_command("report", "--week", WEEK, "--repo", "me/demo-one", "--out", str(out_file))

    content = out_file.read_text(encoding="utf-8")
    assert "me/demo-one" in content
    assert "me/demo-two" not in content
    assert "commits_in_window me/demo-two" not in fake_gh.calls


@pytest.mark.django_db
def test_repo_flag_does_not_persist_a_weekly_report(monkeypatch, settings, tmp_path):
    """A --repo run is a narrowed view, not the week's full picture (D5) -
    #17/#36 trust WeeklyReport to hold every tracked repo. It must not create
    a partial row for a week that has none yet."""
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo-one", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/demo-two", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/demo-one"), make_gh_repo("me/demo-two")])
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK, "--repo", "me/demo-one")

    assert not WeeklyReport.objects.filter(week=WEEK).exists()


@pytest.mark.django_db
def test_repo_flag_does_not_overwrite_an_existing_full_portfolio_report(
    monkeypatch, settings, tmp_path
):
    """A prior full-portfolio run's WeeklyReport row for the week must survive
    a later --repo-scoped run untouched - it must not be clobbered with a
    single-repo snapshot."""
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo-one", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/demo-two", status=Project.Status.ACTIVE)

    full_gh = FakeGitHub(
        repos=[make_gh_repo("me/demo-one"), make_gh_repo("me/demo-two")],
        commits={
            "me/demo-one": [make_commit("s1", day=1)],
            "me/demo-two": [make_commit("s2", day=1)],
        },
    )
    _install_fake_gh(monkeypatch, full_gh)
    call_command("report", "--week", WEEK)

    original = WeeklyReport.objects.get(week=WEEK)
    original_markdown = original.markdown
    original_data = original.data
    original_generated_at = original.generated_at

    narrowed_gh = FakeGitHub(
        repos=[make_gh_repo("me/demo-one"), make_gh_repo("me/demo-two")],
        commits={"me/demo-one": [make_commit("s1", day=1), make_commit("s3", day=3)]},
    )
    _install_fake_gh(monkeypatch, narrowed_gh)
    call_command("report", "--week", WEEK, "--repo", "me/demo-one")

    unchanged = WeeklyReport.objects.get(week=WEEK)
    assert unchanged.markdown == original_markdown
    assert unchanged.data == original_data
    assert unchanged.generated_at == original_generated_at
    assert "me/demo-two" in unchanged.markdown  # still the full picture, not narrowed


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
def test_acked_project_is_absent_from_the_next_report_end_to_end(monkeypatch, settings, tmp_path):
    """#19 end-to-end: `ack --shipped` on a live Project, then the very next
    `report` run, with no direct call to `Project.in_weekly_report` in this test.
    """
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/active", status=Project.Status.ACTIVE)
    Project.objects.create(repo="me/finished", status=Project.Status.ACTIVE)

    call_command("ack", "me/finished", "--shipped")

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/active")])
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/active" in row.markdown
    assert "me/finished" not in row.markdown
    assert "commits_in_window me/finished" not in fake_gh.calls


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


@pytest.mark.django_db
def test_repo_description_and_commit_subject_with_brackets_are_rendered_and_not_swallowed(
    monkeypatch, settings, tmp_path
):
    """The AC names two specific sources - a repo description and a commit
    subject - not just PR titles. Both must actually appear in the rendered
    report (fetched from the fake GitHub client, wired through
    RepoReportData.description/commit_subjects), and a literal `[` in either
    must survive Rich's Markdown-based terminal render and the persisted
    markdown, end to end through the real command."""
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    fake_gh = FakeGitHub(
        repos=[
            make_gh_repo("me/demo", description="a repo with [brackets] in it"),
        ],
        commits={"me/demo": [make_commit("s1", day=1, subject="[urgent] fix bracket bug")]},
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)  # must not raise

    row = WeeklyReport.objects.get(week=WEEK)
    assert "a repo with [brackets] in it" in row.markdown
    assert "[urgent] fix bracket bug" in row.markdown


# --- shipped auto-detection (#20) -----------------------------------------------------


@pytest.mark.django_db
def test_a_released_repo_is_auto_shipped_and_absent_from_the_same_run(
    monkeypatch, settings, tmp_path
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/finished", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/finished")], releases={"me/finished": True})
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/finished" not in row.markdown

    project = Project.objects.get(repo="me/finished")
    assert project.status == Project.Status.SHIPPED
    assert project.status_reason == "Auto-detected: released"


@pytest.mark.django_db
def test_a_semver_tag_ships_the_repo_when_no_release(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/tagged", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/tagged")], tags={"me/tagged": ["v1.2.0"]})
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/tagged")
    assert project.status == Project.Status.SHIPPED
    assert project.status_reason == "Auto-detected: tag v1.2.0"


@pytest.mark.django_db
def test_a_prerelease_tag_does_not_ship_the_repo(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/rc", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/rc")], tags={"me/rc": ["v1.0.0-rc1"]})
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/rc")
    assert project.status == Project.Status.ACTIVE
    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/rc" in row.markdown


@pytest.mark.django_db
def test_readme_status_complete_ships_the_repo_when_no_release_or_tag(
    monkeypatch, settings, tmp_path
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/done", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/done")], readmes={"me/done": "# Done\n\nStatus: Complete\n"}
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/done")
    assert project.status == Project.Status.SHIPPED
    assert project.status_reason == "Auto-detected: README says Status: Complete"


@pytest.mark.django_db
def test_readme_in_progress_does_not_ship_the_repo(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/wip", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/wip")], readmes={"me/wip": "Status: WIP"})
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/wip")
    assert project.status == Project.Status.ACTIVE


@pytest.mark.django_db
def test_multi_signal_priority_release_over_tag_and_readme(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/all-three", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/all-three")],
        releases={"me/all-three": True},
        tags={"me/all-three": ["v1.0"]},
        readmes={"me/all-three": "Status: Complete"},
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/all-three")
    assert project.status_reason == "Auto-detected: released"


@pytest.mark.django_db
def test_multi_signal_priority_tag_over_readme(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/tag-and-readme", status=Project.Status.ACTIVE)

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/tag-and-readme")],
        tags={"me/tag-and-readme": ["v3.0"]},
        readmes={"me/tag-and-readme": "Status: Complete"},
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/tag-and-readme")
    assert project.status_reason == "Auto-detected: tag v3.0"


@pytest.mark.django_db
def test_explicit_ack_status_reason_is_never_overridden_by_a_shipped_signal(
    monkeypatch, settings, tmp_path
):
    """A project a human paused (with a non-Auto-detected reason) that is back in
    the report population (paused_until has passed) must never be auto-shipped,
    even when a shipped signal fires for it - explicit human state wins, always."""
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    project = Project.objects.create(
        repo="me/human-paused",
        status=Project.Status.PAUSED,
        status_reason="taking a break",
        paused_until=WINDOW[0].date() - timedelta(days=1),
    )
    assert project.in_weekly_report is True

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/human-paused")], releases={"me/human-paused": True}
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project.refresh_from_db()
    assert project.status == Project.Status.PAUSED
    assert project.status_reason == "taking a break"
    row = WeeklyReport.objects.get(week=WEEK)
    assert "me/human-paused" in row.markdown


@pytest.mark.django_db
def test_auto_shipped_project_reactivates_when_commits_resume_in_a_later_week(
    monkeypatch, settings, tmp_path
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(
        repo="me/reawakened",
        status=Project.Status.SHIPPED,
        status_reason="Auto-detected: released",
    )
    # not in `projects` population (status=SHIPPED), so no Project row is needed
    # to also be active - the reactivation pass queries SHIPPED projects directly.

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/reawakened")],
        commits={"me/reawakened": [make_commit("s1", day=1)]},
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/reawakened")
    assert project.status == Project.Status.ACTIVE
    assert project.status_reason == "Auto-detected: commits resumed"


@pytest.mark.django_db
def test_manually_shipped_project_is_never_auto_reactivated(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(
        repo="me/manually-shipped",
        status=Project.Status.SHIPPED,
        status_reason="shipped it myself",
    )

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/manually-shipped")],
        commits={"me/manually-shipped": [make_commit("s1", day=1)]},
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/manually-shipped")
    assert project.status == Project.Status.SHIPPED
    assert project.status_reason == "shipped it myself"


@pytest.mark.django_db
def test_auto_shipped_project_with_no_commits_this_week_stays_shipped(
    monkeypatch, settings, tmp_path
):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(
        repo="me/still-quiet",
        status=Project.Status.SHIPPED,
        status_reason="Auto-detected: released",
    )

    fake_gh = FakeGitHub(repos=[make_gh_repo("me/still-quiet")])
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK)

    project = Project.objects.get(repo="me/still-quiet")
    assert project.status == Project.Status.SHIPPED
    assert project.status_reason == "Auto-detected: released"


@pytest.mark.django_db
def test_repo_scoped_run_does_not_run_the_reactivation_pass(monkeypatch, settings, tmp_path):
    """A `--repo` run is a narrowed view of one project (D5-style reasoning) - it
    must not flip the state of an unrelated, previously auto-shipped project."""
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/active", status=Project.Status.ACTIVE)
    Project.objects.create(
        repo="me/other-shipped",
        status=Project.Status.SHIPPED,
        status_reason="Auto-detected: released",
    )

    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/active")],
        commits={"me/other-shipped": [make_commit("s1", day=1)]},
    )
    _install_fake_gh(monkeypatch, fake_gh)

    call_command("report", "--week", WEEK, "--repo", "me/active")

    project = Project.objects.get(repo="me/other-shipped")
    assert project.status == Project.Status.SHIPPED


# --- --last (#35, D22) ------------------------------------------------------------


@pytest.mark.django_db
def test_last_flag_requires_no_github_configuration(settings):
    """#35/D22: GITHUB_USER/TOKEN/EMAILS must never be read or required on the
    --last path - it must succeed with all three unset."""
    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    call_command("report", "--last")  # must not raise


@pytest.mark.django_db
def test_last_flag_with_no_reports_prints_a_message_and_exits_clean(settings, capsys):
    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    call_command("report", "--last")  # must not raise / must not attempt to generate

    captured = capsys.readouterr()
    assert "no weekly report has been generated yet" in captured.out.lower()
    assert not WeeklyReport.objects.exists()


@pytest.mark.django_db
def test_last_flag_reprints_the_most_recently_generated_report_not_the_highest_week(
    monkeypatch, settings, tmp_path, capsys
):
    """D22: 'most recent' means greatest generated_at, not greatest week label.
    Generate 2026-W36 first, then 2026-W20 second (out of chronological order) -
    --last must reprint 2026-W20, the one generated *second*."""
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)

    later_week = "2026-W36"
    earlier_week = "2026-W20"

    fake_gh_1 = FakeGitHub(
        repos=[make_gh_repo("me/demo")],
        commits={"me/demo": [make_commit("s1", day=1)]},
    )
    _install_fake_gh(monkeypatch, fake_gh_1)
    call_command("report", "--week", later_week)

    fake_gh_2 = FakeGitHub(
        repos=[make_gh_repo("me/demo")],
        commits={"me/demo": [make_commit("s2", day=1)]},
    )
    _install_fake_gh(monkeypatch, fake_gh_2)
    call_command("report", "--week", earlier_week)

    assert WeeklyReport.objects.count() == 2
    expected = WeeklyReport.objects.get(week=earlier_week)

    capsys.readouterr()  # discard output from the two generation runs above
    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    call_command("report", "--last")

    captured = capsys.readouterr()
    assert earlier_week in captured.out
    assert expected.markdown in captured.out
    # the row generated second wins even though its week label (2026-W20) sorts
    # lower than the row generated first (2026-W36).
    assert later_week not in captured.out


@pytest.mark.django_db
def test_last_flag_prints_stored_markdown_byte_identical(monkeypatch, settings, tmp_path, capsys):
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

    capsys.readouterr()  # discard output from the generation run above
    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    call_command("report", "--last")

    captured = capsys.readouterr()
    assert row.markdown in captured.out
    # the markdown block itself, isolated from the info line above it, is
    # character-for-character identical to what was stored.
    tail = captured.out[captured.out.index(row.markdown) :]
    assert tail.rstrip("\n") == row.markdown.rstrip("\n")


@pytest.mark.django_db
def test_last_flag_makes_zero_github_requests(monkeypatch, settings, tmp_path):
    """No GitHub/cache object is constructed at all on the --last path."""
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    fake_gh = FakeGitHub(repos=[make_gh_repo("me/demo")])
    _install_fake_gh(monkeypatch, fake_gh)
    call_command("report", "--week", WEEK)

    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    def _boom(*args, **kwargs):
        raise AssertionError("GitHub must never be constructed on the --last path")

    monkeypatch.setattr(report_cmd, "GitHub", _boom)
    monkeypatch.setattr(report_cmd, "Cache", _boom)

    call_command("report", "--last")  # must not raise


@pytest.mark.django_db
def test_last_flag_never_writes_to_the_database(monkeypatch, settings, tmp_path):
    _configure(settings)
    settings.WEEKLY_CACHE_DIR = tmp_path
    Project.objects.create(repo="me/demo", status=Project.Status.ACTIVE)
    fake_gh = FakeGitHub(
        repos=[make_gh_repo("me/demo")],
        commits={"me/demo": [make_commit("s1", day=1)]},
    )
    _install_fake_gh(monkeypatch, fake_gh)
    call_command("report", "--week", WEEK)

    row_before = WeeklyReport.objects.get(week=WEEK)
    markdown_before = row_before.markdown
    generated_at_before = row_before.generated_at
    repoweek_count_before = RepoWeek.objects.count()
    project_before = Project.objects.get(repo="me/demo")
    status_before = project_before.status
    status_reason_before = project_before.status_reason

    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    call_command("report", "--last")

    assert WeeklyReport.objects.count() == 1
    row_after = WeeklyReport.objects.get(week=WEEK)
    assert row_after.markdown == markdown_before
    assert row_after.generated_at == generated_at_before
    assert RepoWeek.objects.count() == repoweek_count_before
    project_after = Project.objects.get(repo="me/demo")
    assert project_after.status == status_before
    assert project_after.status_reason == status_reason_before


@pytest.mark.django_db
def test_last_flag_with_week_flag_raises_command_error(settings):
    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("report", "--last", "--week", WEEK)


@pytest.mark.django_db
def test_last_flag_with_repo_flag_raises_command_error(settings):
    settings.GITHUB_USER = ""
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_EMAILS = ""

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("report", "--last", "--repo", "me/demo")
