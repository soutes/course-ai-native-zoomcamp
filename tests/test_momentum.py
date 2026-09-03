"""Momentum stats (#13), tested from fixtures. No network, no database.

`compute_repo_week` is pure: commits go in, a `RepoWeekStats` comes out. The
diffstat fetcher is a plain callable here, never `GitHub` itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from portfolio.services.momentum import compute_repo_week
from portfolio.services.types import Commit, CommitStat

UTC_TZ = UTC
SAO_PAULO = ZoneInfo("America/Sao_Paulo")  # UTC-3, no DST since 2019


def make_commit(sha, *, authored_at, subject="Fix the thing"):
    return Commit(sha=sha, authored_at=authored_at, subject=subject)


def stat_for(commit: Commit, *, additions=1, deletions=1, files_changed=1) -> CommitStat:
    return CommitStat(
        sha=commit.sha, additions=additions, deletions=deletions, files_changed=files_changed
    )


def fetcher(stats_by_sha):
    """Build a `diffstat` callable from a {sha: CommitStat} map, recording calls."""
    calls = []

    def fetch(commit: Commit) -> CommitStat:
        calls.append(commit.sha)
        return stats_by_sha[commit.sha]

    fetch.calls = calls
    return fetch


# --- the six numbers, per repo per week -----------------------------------------


def test_six_numbers_from_a_normal_week():
    commits = [
        make_commit("c1", authored_at=datetime(2026, 8, 31, 10, 0, tzinfo=UTC_TZ)),
        make_commit("c2", authored_at=datetime(2026, 9, 2, 14, 0, tzinfo=UTC_TZ)),
    ]
    stats = {
        "c1": CommitStat(sha="c1", additions=10, deletions=2, files_changed=3),
        "c2": CommitStat(sha="c2", additions=5, deletions=7, files_changed=2),
    }
    result = compute_repo_week(commits, fetcher(stats), tz=UTC_TZ)

    assert result.commits == 2
    assert result.active_days == 2
    assert result.lines_added == 15
    assert result.lines_removed == 9
    assert result.files_touched == 5
    assert result.partial is False


# --- active days: distinct local calendar days, not raw commit count ------------


def test_one_day_burst_is_one_active_day_not_twelve():
    commits = [
        make_commit(f"c{i}", authored_at=datetime(2026, 9, 1, i % 23, 0, tzinfo=UTC_TZ))
        for i in range(12)
    ]
    stats = {c.sha: stat_for(c) for c in commits}

    result = compute_repo_week(commits, fetcher(stats), tz=UTC_TZ)

    assert result.commits == 12
    assert result.active_days == 1


def test_active_days_use_the_given_local_timezone_not_utc():
    # 2026-09-02T01:30 UTC is still 2026-09-01 local in Sao Paulo (UTC-3).
    commits = [
        make_commit("late-utc", authored_at=datetime(2026, 9, 2, 1, 30, tzinfo=UTC_TZ)),
        make_commit("same-local-day", authored_at=datetime(2026, 9, 1, 20, 0, tzinfo=UTC_TZ)),
    ]
    stats = {c.sha: stat_for(c) for c in commits}

    utc_result = compute_repo_week(commits, fetcher(stats), tz=UTC_TZ)
    local_result = compute_repo_week(commits, fetcher(stats), tz=SAO_PAULO)

    assert utc_result.active_days == 2  # Sep 1 and Sep 2 in UTC
    assert local_result.active_days == 1  # both land on Sep 1 in Sao Paulo


# --- zero-commit repos still produce a row ---------------------------------------


def test_zero_commits_still_produces_a_zero_valued_non_partial_row():
    result = compute_repo_week([], fetcher({}), tz=UTC_TZ)

    assert result.commits == 0
    assert result.active_days == 0
    assert result.lines_added == 0
    assert result.lines_removed == 0
    assert result.files_touched == 0
    assert result.partial is False


# --- lines added/removed stay separate, never netted -----------------------------


def test_lines_added_and_removed_are_never_netted():
    commits = [make_commit("c1", authored_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC_TZ))]
    stats = {"c1": CommitStat(sha="c1", additions=100, deletions=1, files_changed=1)}

    result = compute_repo_week(commits, fetcher(stats), tz=UTC_TZ)

    assert result.lines_added == 100
    assert result.lines_removed == 1


# --- a commit with no textual diff (binary/rename) does not break totals ---------


def test_binary_or_rename_commit_with_zero_stats_does_not_break_totals():
    commits = [
        make_commit("textual", authored_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC_TZ)),
        make_commit("binary-rename", authored_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC_TZ)),
    ]
    stats = {
        "textual": CommitStat(sha="textual", additions=4, deletions=1, files_changed=1),
        # A binary file and a pure rename: GitHub reports 0/0 additions/deletions
        # but the file still counts as touched.
        "binary-rename": CommitStat(sha="binary-rename", additions=0, deletions=0, files_changed=2),
    }

    result = compute_repo_week(commits, fetcher(stats), tz=UTC_TZ)

    assert result.commits == 2
    assert result.lines_added == 4
    assert result.lines_removed == 1
    assert result.files_touched == 3
    assert result.partial is False


# --- the diffstat cap (D2 = 80) --------------------------------------------------


def test_diffstat_cap_marks_partial_and_stops_fetching_beyond_the_cap():
    base = datetime(2026, 9, 1, 0, 0, tzinfo=UTC_TZ)
    commits = [make_commit(f"c{i}", authored_at=base + timedelta(minutes=i)) for i in range(85)]
    stats = {
        c.sha: CommitStat(sha=c.sha, additions=1, deletions=1, files_changed=1) for c in commits
    }
    fetch = fetcher(stats)

    result = compute_repo_week(commits, fetch, tz=UTC_TZ, cap=80)

    # commits and active days still count every commit...
    assert result.commits == 85
    # ...but diffstat was only fetched, and only counted, for the first 80.
    assert len(fetch.calls) == 80
    assert result.lines_added == 80
    assert result.lines_removed == 80
    assert result.files_touched == 80
    assert result.partial is True


def test_exactly_at_the_cap_is_not_partial():
    base = datetime(2026, 9, 1, 0, 0, tzinfo=UTC_TZ)
    commits = [make_commit(f"c{i}", authored_at=base + timedelta(minutes=i)) for i in range(80)]
    stats = {c.sha: stat_for(c) for c in commits}

    result = compute_repo_week(commits, fetcher(stats), tz=UTC_TZ, cap=80)

    assert result.commits == 80
    assert result.partial is False


def test_default_cap_is_eighty_per_d2():
    from portfolio.services.momentum import DIFFSTAT_CAP

    assert DIFFSTAT_CAP == 80
