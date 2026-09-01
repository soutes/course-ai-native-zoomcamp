"""Classification rules, tested from fixtures. No network involved."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
