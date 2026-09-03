"""New-repos-this-week detection (#33), tested from fixtures. No network, no database.

`new_repos_this_week` is pure: a list of `Repo` plus a `(start, end)` window
(#11's `week_window`) go in, a list of `NewRepo` comes out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from portfolio.services.new_repos import new_repos_this_week
from portfolio.services.types import Repo
from portfolio.services.week import week_window

UTC_TZ = UTC
SAO_PAULO = ZoneInfo("America/Sao_Paulo")  # UTC-3, no DST since 2019


def make_repo(name, *, created_at, full_name=None, pushed_at=None):
    return Repo(
        name=name,
        full_name=full_name or f"me/{name}",
        html_url=f"https://github.com/me/{name}",
        private=False,
        fork=False,
        archived=False,
        description=None,
        topics=[],
        license=None,
        default_branch="main",
        created_at=created_at,
        pushed_at=pushed_at or created_at,
        stars=0,
        forks=0,
    )


# --- inside vs outside the window -------------------------------------------------


def test_repo_created_inside_window_is_included():
    window = week_window("2026-W36", tz=UTC_TZ)  # Mon 2026-08-31 .. Sun 2026-09-06
    repo = make_repo("brand-new", created_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC_TZ))

    result = new_repos_this_week([repo], window)

    assert [r.name for r in result] == ["brand-new"]
    assert result[0].created_at == repo.created_at


def test_repo_created_outside_window_is_excluded():
    window = week_window("2026-W36", tz=UTC_TZ)
    before = make_repo("too-early", created_at=datetime(2026, 8, 30, 23, 0, tzinfo=UTC_TZ))
    after = make_repo("too-late", created_at=datetime(2026, 9, 7, 0, 0, tzinfo=UTC_TZ))

    result = new_repos_this_week([before, after], window)

    assert result == []


# --- timezone boundary: late-Sunday creation stays in its own week ---------------


def test_creation_late_sunday_local_is_not_pushed_into_next_week():
    # Window for W36 in Sao Paulo local time: Sun 2026-09-06 23:59:59.999999 -03:00
    # is 2026-09-07T02:59:59.999999Z in UTC - past midnight UTC, but still this
    # week in local time.
    window = week_window("2026-W36", tz=SAO_PAULO)
    late_sunday = datetime(2026, 9, 7, 1, 0, tzinfo=UTC)  # 2026-09-06 22:00 in Sao Paulo
    repo = make_repo("late-starter", created_at=late_sunday)

    result = new_repos_this_week([repo], window)

    assert [r.name for r in result] == ["late-starter"]

    # And the very next week's window must NOT also claim it.
    next_window = week_window("2026-W37", tz=SAO_PAULO)
    assert new_repos_this_week([repo], next_window) == []


def test_creation_just_after_local_midnight_monday_belongs_to_new_week():
    window = week_window("2026-W37", tz=SAO_PAULO)
    # 2026-09-07T04:00:00Z is 2026-09-07T01:00:00-03:00 - just into Monday local.
    just_after_monday = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)
    repo = make_repo("monday-starter", created_at=just_after_monday)

    result = new_repos_this_week([repo], window)

    assert [r.name for r in result] == ["monday-starter"]

    prior_window = week_window("2026-W36", tz=SAO_PAULO)
    assert new_repos_this_week([repo], prior_window) == []


# --- untracked repos still counted ------------------------------------------------


def test_untracked_repo_with_no_commit_count_entry_is_still_included_at_zero():
    window = week_window("2026-W36", tz=UTC_TZ)
    repo = make_repo(
        "untracked-experiment",
        created_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC_TZ),
        full_name="me/untracked-experiment",
    )

    # No entry for this repo in commit_counts, and no commit_counts arg at all.
    result = new_repos_this_week([repo], window)

    assert len(result) == 1
    assert result[0].name == "untracked-experiment"
    assert result[0].commits == 0


def test_strong_first_week_is_still_counted_as_a_start_not_exempted():
    window = week_window("2026-W36", tz=UTC_TZ)
    repo = make_repo("hot-start", created_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC_TZ))

    result = new_repos_this_week([repo], window, commit_counts={"me/hot-start": 47})

    assert len(result) == 1
    assert result[0].commits == 47


# --- multiple new repos, all returned, with a count ------------------------------


def test_multiple_new_repos_all_returned_with_their_own_counts():
    window = week_window("2026-W36", tz=UTC_TZ)
    repo_a = make_repo("alpha", created_at=datetime(2026, 8, 31, 9, 0, tzinfo=UTC_TZ))
    repo_b = make_repo("beta", created_at=datetime(2026, 9, 3, 15, 0, tzinfo=UTC_TZ))
    repo_c = make_repo("gamma", created_at=datetime(2026, 9, 6, 20, 0, tzinfo=UTC_TZ))

    result = new_repos_this_week(
        [repo_c, repo_a, repo_b],
        window,
        commit_counts={"me/alpha": 3, "me/beta": 1, "me/gamma": 0},
    )

    assert len(result) == 3
    # Ordered by creation date, earliest first, regardless of input order.
    assert [r.name for r in result] == ["alpha", "beta", "gamma"]
    assert [r.commits for r in result] == [3, 1, 0]


# --- empty week ---------------------------------------------------------------


def test_empty_week_returns_empty_list_not_an_error():
    window = week_window("2026-W36", tz=UTC_TZ)
    old_repo = make_repo("ancient", created_at=datetime(2020, 1, 1, tzinfo=UTC_TZ))

    result = new_repos_this_week([old_repo], window)

    assert result == []


def test_no_repos_at_all_returns_empty_list():
    window = week_window("2026-W36", tz=UTC_TZ)

    assert new_repos_this_week([], window) == []
