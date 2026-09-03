"""Classification rules, tested from fixtures. No network involved."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from portfolio.services.triage import build_plan, classify
from portfolio.services.types import Verdict

NOW = datetime.now(UTC)


def make_repo(**overrides):
    from portfolio.services.types import Repo

    defaults = dict(
        name="demo",
        full_name="me/demo",
        html_url="https://github.com/me/demo",
        private=False,
        fork=False,
        archived=False,
        description="a repo",
        topics=["python"],
        license="MIT",
        default_branch="main",
        created_at=NOW - timedelta(days=400),
        pushed_at=NOW - timedelta(days=10),
        stars=0,
        forks=0,
        commits=50,
        has_readme=True,
        has_release=False,
    )
    defaults.update(overrides)
    return Repo(**defaults)


def test_finished_course_repo_is_showcase_even_when_old():
    repo = make_repo(pushed_at=NOW - timedelta(days=420), commits=62)
    assert classify(repo, min_commits=10).verdict is Verdict.SHOWCASE


def test_too_few_commits_is_hidden():
    decision = classify(make_repo(commits=3), min_commits=10)
    assert decision.verdict is Verdict.HIDE
    assert "only 3 commits" in decision.reasons


def test_no_readme_is_hidden_regardless_of_commits():
    decision = classify(make_repo(has_readme=False, commits=200), min_commits=10)
    assert decision.verdict is Verdict.HIDE
    assert "no README" in decision.reasons


def test_untouched_fork_is_delete_suggestion():
    decision = classify(make_repo(fork=True, commits=0), min_commits=10)
    assert decision.verdict is Verdict.DELETE


def test_private_repo_is_skipped():
    assert classify(make_repo(private=True, commits=1), min_commits=10).verdict is Verdict.SKIP


def test_polish_hints_flag_gaps_on_kept_repos():
    decision = classify(make_repo(description=None, topics=[], license=None), min_commits=10)
    assert decision.verdict is Verdict.SHOWCASE
    assert decision.polish == ["no description", "no topics", "no license"]


def test_only_public_hide_repos_count_as_changes():
    plan = build_plan(
        [
            make_repo(name="keep", commits=50),
            make_repo(name="hide-me", commits=2),
            make_repo(name="already-private", private=True, commits=2),
        ],
        min_commits=10,
    )
    assert [d.repo.name for d in plan.changes] == ["hide-me"]


def test_age_label_reads_naturally():
    assert make_repo(pushed_at=NOW - timedelta(days=3)).age_label == "3d"
    assert make_repo(pushed_at=NOW - timedelta(days=150)).age_label == "5mo"
    assert make_repo(pushed_at=NOW - timedelta(days=430)).age_label == "1y2m"


# --- render: stars/forks in the pre-apply changes list ------------------------


def test_render_changes_shows_stars_and_forks():
    from portfolio.services import render
    from portfolio.services.types import Decision

    changes = [
        Decision(
            make_repo(name="lonely-repo", stars=42, forks=7), Verdict.HIDE, ["only 2 commits"]
        ),
    ]
    with render.console.capture() as capture:
        render.render_changes(changes)
    output = capture.get()
    assert "lonely-repo" in output
    assert "42" in output
    assert "7" in output


# --- Command._apply / handle(): failure counting and exit code ----------------


class FakeGitHub:
    """Stands in for `portfolio.services.github.GitHub`. No network, ever."""

    def __init__(self, repos, fail: set[str] = frozenset()):
        self._repos = repos
        self._fail = fail
        self.made_private: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def my_repos(self):
        return iter(self._repos)

    def commit_count(self, full_name, author=None):
        return next(r.commits for r in self._repos if r.full_name == full_name)

    def has_readme(self, full_name):
        return next(r.has_readme for r in self._repos if r.full_name == full_name)

    def has_release(self, full_name):
        return next(r.has_release for r in self._repos if r.full_name == full_name)

    def make_private(self, full_name):
        from portfolio.services.github import GitHubError

        if full_name in self._fail:
            raise GitHubError(f"Could not make {full_name} private: 403 forbidden")
        self.made_private.append(full_name)


@pytest.fixture
def apply_repos():
    return [
        make_repo(name="hide-ok", full_name="me/hide-ok", commits=2, stars=3, forks=1),
        make_repo(name="hide-fails", full_name="me/hide-fails", commits=1, stars=0, forks=0),
    ]


def _run_triage_apply(monkeypatch, settings, fake_gh, extra_args=()):
    from django.core.management import call_command

    from portfolio.management.commands import triage as triage_cmd

    settings.GITHUB_USER = "me"
    settings.GITHUB_TOKEN = "fake-token"
    monkeypatch.setattr(triage_cmd, "GitHub", lambda token, cache: fake_gh)
    call_command("triage", "--apply", "--yes", "--min-commits", "10", *extra_args)


@pytest.mark.django_db
def test_apply_summary_states_both_counts_on_partial_failure(
    monkeypatch, settings, capsys, apply_repos
):
    fake_gh = FakeGitHub(apply_repos, fail={"me/hide-fails"})

    with pytest.raises(SystemExit):
        _run_triage_apply(monkeypatch, settings, fake_gh)

    output = capsys.readouterr().out
    assert "1 repos made private, 1 failed." in output
    assert fake_gh.made_private == ["me/hide-ok"]


@pytest.mark.django_db
def test_apply_exits_non_zero_when_a_repo_fails(monkeypatch, settings, apply_repos):
    fake_gh = FakeGitHub(apply_repos, fail={"me/hide-fails"})

    with pytest.raises(SystemExit) as excinfo:
        _run_triage_apply(monkeypatch, settings, fake_gh)

    assert excinfo.value.code != 0


@pytest.mark.django_db
def test_apply_exits_zero_and_states_zero_failed_when_everything_succeeds(
    monkeypatch, settings, capsys, apply_repos
):
    fake_gh = FakeGitHub(apply_repos, fail=set())

    _run_triage_apply(monkeypatch, settings, fake_gh)  # must not raise SystemExit

    output = capsys.readouterr().out
    assert "2 repos made private, 0 failed." in output
    assert set(fake_gh.made_private) == {"me/hide-ok", "me/hide-fails"}


@pytest.mark.django_db
def test_apply_prints_stars_and_forks_before_the_prompt(monkeypatch, settings, capsys, apply_repos):
    fake_gh = FakeGitHub(apply_repos, fail=set())

    _run_triage_apply(monkeypatch, settings, fake_gh)

    output = capsys.readouterr().out
    assert "hide-ok" in output
    assert "3" in output  # stars
    assert "1" in output  # forks


# --- confirmation abort path, and the DELETE pile under the full command path -


@pytest.mark.django_db
def test_confirm_abort_leaves_github_untouched_and_exits_cleanly(
    monkeypatch, settings, capsys, apply_repos
):
    """A bare Enter (or anything but y/yes) aborts: no write, no SystemExit."""
    from django.core.management import call_command

    from portfolio.management.commands import triage as triage_cmd

    settings.GITHUB_USER = "me"
    settings.GITHUB_TOKEN = "fake-token"
    fake_gh = FakeGitHub(apply_repos, fail=set())
    monkeypatch.setattr(triage_cmd, "GitHub", lambda token, cache: fake_gh)
    monkeypatch.setattr("builtins.input", lambda *_args: "")

    # No --yes: the prompt is reached, and answering with a bare Enter aborts.
    # A clean abort must not raise SystemExit - the process exits 0 by falling
    # off the end of handle().
    call_command("triage", "--apply", "--min-commits", "10")

    output = capsys.readouterr().out
    assert "Aborted" in output
    assert fake_gh.made_private == []


@pytest.mark.django_db
def test_delete_pile_never_reaches_apply_under_full_command(monkeypatch, settings, capsys):
    """A DELETE-verdict repo (an untouched fork) must never be patched, end to end."""
    from django.core.management import call_command

    from portfolio.management.commands import triage as triage_cmd

    settings.GITHUB_USER = "me"
    settings.GITHUB_TOKEN = "fake-token"
    repos = [
        make_repo(name="hide-me", full_name="me/hide-me", commits=2, stars=0, forks=0),
        make_repo(
            name="abandoned-fork",
            full_name="me/abandoned-fork",
            fork=True,
            commits=0,
            has_readme=False,
        ),
    ]
    fake_gh = FakeGitHub(repos, fail=set())
    monkeypatch.setattr(triage_cmd, "GitHub", lambda token, cache: fake_gh)

    call_command("triage", "--apply", "--yes", "--min-commits", "10")

    assert fake_gh.made_private == ["me/hide-me"]

    output = capsys.readouterr().out
    assert "delete it yourself in the GitHub UI" in output
