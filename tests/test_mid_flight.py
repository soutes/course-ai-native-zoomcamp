"""`GitHub.unmerged_branches` and `GitHub.open_pull_requests` (#15), tested against a
fake transport - no network. Same style as `test_github.py`: a real `GitHub` client
with its socket swapped for an `httpx.MockTransport`, so pagination/caching/`_get`
plumbing runs exactly as it would in production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from portfolio.services.cache import Cache
from portfolio.services.github import API, BRANCH_COMPARE_CAP, GitHub

NOW = datetime.now(UTC)


def make_gh(handler, *, cache=None):
    gh = GitHub(token="fake-token", cache=cache or Cache("test-mid-flight", enabled=False))
    gh.client = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return gh


def raw_branch(name, sha=None):
    sha = sha or f"sha-{name}"
    return {"name": name, "commit": {"sha": sha, "url": f"https://api.github.com/x/{sha}"}}


def raw_pull(number, *, login="me", draft=False, title="Add widget", created_at=None):
    return {
        "number": number,
        "title": title,
        "draft": draft,
        "user": {"login": login},
        "created_at": created_at or "2026-08-30T00:00:00Z",
    }


def route_handler(*, branches, commit_dates, compares, pulls, calls=None):
    """Dispatches a fake transport by URL path/params, covering every endpoint
    `unmerged_branches`/`open_pull_requests` touches: the branch list, each
    branch's `/commits/{sha}` date lookup, `/compare/{base}...{head}`, and
    `/pulls?state=open`. `calls`, if given, collects every request path seen -
    used to assert the D3 compare-call bound.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append(path)

        if path.endswith("/branches"):
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=branches if page == 1 else [])

        if "/commits/" in path:
            sha = path.rsplit("/", 1)[-1]
            date = commit_dates.get(sha, "2020-01-01T00:00:00Z")
            return httpx.Response(200, json={"sha": sha, "commit": {"author": {"date": date}}})

        if "/compare/" in path:
            head = path.rsplit("...", 1)[-1]
            return httpx.Response(200, json=compares.get(head, {"ahead_by": 0, "behind_by": 0}))

        if path.endswith("/pulls"):
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=pulls if page == 1 else [])

        return httpx.Response(404, json={"message": f"unhandled path {path}"})

    return handler


# --- unmerged_branches ---------------------------------------------------------


def test_default_branch_is_never_listed_as_unmerged():
    branches = [raw_branch("main"), raw_branch("feature-x")]
    calls: list[str] = []
    handler = route_handler(
        branches=branches,
        commit_dates={"sha-feature-x": "2026-08-30T00:00:00Z"},
        compares={"feature-x": {"ahead_by": 2, "behind_by": 0}},
        pulls=[],
        calls=calls,
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    assert [b.name for b in result] == ["feature-x"]
    assert not any("compare/main...main" in c for c in calls)


def test_branch_ahead_and_not_behind_is_included_with_ahead_count_and_age():
    branches = [raw_branch("main"), raw_branch("feature-x")]
    last_commit = NOW - timedelta(days=3)
    handler = route_handler(
        branches=branches,
        commit_dates={"sha-feature-x": last_commit.strftime("%Y-%m-%dT%H:%M:%SZ")},
        compares={"feature-x": {"ahead_by": 4, "behind_by": 0}},
        pulls=[],
    )
    gh = make_gh(handler)

    (branch,) = gh.unmerged_branches("me/demo", default_branch="main")

    assert branch.name == "feature-x"
    assert branch.ahead_by == 4
    assert branch.age_days == 3


def test_diverged_branch_ahead_and_behind_is_still_included():
    branches = [raw_branch("main"), raw_branch("diverged")]
    handler = route_handler(
        branches=branches,
        commit_dates={"sha-diverged": "2026-08-20T00:00:00Z"},
        compares={"diverged": {"ahead_by": 2, "behind_by": 5}},
        pulls=[],
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    assert [b.name for b in result] == ["diverged"]


def test_branch_behind_but_not_ahead_is_excluded():
    branches = [raw_branch("main"), raw_branch("stale")]
    handler = route_handler(
        branches=branches,
        commit_dates={"sha-stale": "2020-01-01T00:00:00Z"},
        compares={"stale": {"ahead_by": 0, "behind_by": 5}},
        pulls=[],
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    assert result == []


def test_branch_identical_to_default_is_excluded():
    branches = [raw_branch("main"), raw_branch("same")]
    handler = route_handler(
        branches=branches,
        commit_dates={"sha-same": "2026-08-20T00:00:00Z"},
        compares={"same": {"ahead_by": 0, "behind_by": 0}},
        pulls=[],
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    assert result == []


def test_at_most_20_most_recently_pushed_branches_are_compared():
    """D3: 25 non-default branches exist; only the 20 most-recently-committed
    are ever compared, and the 5 oldest-committed never see a compare call."""
    branches = [raw_branch("main")]
    commit_dates = {}
    compares = {}
    for i in range(25):
        name = f"b{i:02d}"
        sha = f"sha-{name}"
        branches.append(raw_branch(name, sha=sha))
        commit_dates[sha] = (NOW - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        compares[name] = {"ahead_by": 1, "behind_by": 0}

    calls: list[str] = []
    handler = route_handler(
        branches=branches, commit_dates=commit_dates, compares=compares, pulls=[], calls=calls
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    compare_calls = [c for c in calls if "/compare/" in c]
    assert len(compare_calls) == BRANCH_COMPARE_CAP == 20
    assert len(result) == 20
    # the 5 oldest (largest i, oldest date) never got compared
    compared_names = {b.name for b in result}
    for i in range(20, 25):
        assert f"b{i:02d}" not in compared_names


# --- open_pull_requests ----------------------------------------------------------


def test_draft_prs_are_included_and_marked():
    pulls = [raw_pull(5, login="me", draft=True, title="WIP thing")]
    handler = route_handler(
        branches=[raw_branch("main")], commit_dates={}, compares={}, pulls=pulls
    )
    gh = make_gh(handler)

    (pr,) = gh.open_pull_requests("me/demo", github_user="me")

    assert pr.number == 5
    assert pr.draft is True


def test_prs_opened_by_someone_else_are_excluded():
    pulls = [raw_pull(1, login="me"), raw_pull(2, login="someone-else")]
    handler = route_handler(
        branches=[raw_branch("main")], commit_dates={}, compares={}, pulls=pulls
    )
    gh = make_gh(handler)

    result = gh.open_pull_requests("me/demo", github_user="me")

    assert [p.number for p in result] == [1]


def test_pr_author_match_is_case_insensitive():
    pulls = [raw_pull(1, login="ME")]
    handler = route_handler(
        branches=[raw_branch("main")], commit_dates={}, compares={}, pulls=pulls
    )
    gh = make_gh(handler)

    result = gh.open_pull_requests("me/demo", github_user="me")

    assert [p.number for p in result] == [1]


def test_pr_carries_title_and_age_in_days():
    created = NOW - timedelta(days=10)
    pulls = [
        raw_pull(
            9, login="me", title="Fix the thing", created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    ]
    handler = route_handler(
        branches=[raw_branch("main")], commit_dates={}, compares={}, pulls=pulls
    )
    gh = make_gh(handler)

    (pr,) = gh.open_pull_requests("me/demo", github_user="me")

    assert pr.title == "Fix the thing"
    assert pr.age_days == 10


# --- empty case ------------------------------------------------------------------


def test_repo_with_no_branches_beyond_default_and_no_open_prs_returns_two_empty_lists():
    handler = route_handler(branches=[raw_branch("main")], commit_dates={}, compares={}, pulls=[])
    gh = make_gh(handler)

    assert gh.unmerged_branches("me/demo", default_branch="main") == []
    assert gh.open_pull_requests("me/demo", github_user="me") == []


# --- caching: a re-run costs zero requests (#5) -----------------------------------


@pytest.mark.django_db
def test_unmerged_branches_and_open_prs_are_cached_a_rerun_costs_zero_requests(settings, tmp_path):
    settings.WEEKLY_CACHE_DIR = tmp_path
    calls: list[str] = []

    branches = [raw_branch("main"), raw_branch("feature-x")]
    handler = route_handler(
        branches=branches,
        commit_dates={"sha-feature-x": "2026-08-20T00:00:00Z"},
        compares={"feature-x": {"ahead_by": 1, "behind_by": 0}},
        pulls=[raw_pull(1, login="me")],
        calls=calls,
    )

    cache = Cache("week-2026-W36", enabled=True)
    gh = make_gh(handler, cache=cache)
    first_branches = gh.unmerged_branches("me/demo", default_branch="main")
    first_prs = gh.open_pull_requests("me/demo", github_user="me")

    calls.clear()
    gh2 = make_gh(handler, cache=cache)
    second_branches = gh2.unmerged_branches("me/demo", default_branch="main")
    second_prs = gh2.open_pull_requests("me/demo", github_user="me")

    assert [b.name for b in first_branches] == [b.name for b in second_branches]
    assert [p.number for p in first_prs] == [p.number for p in second_prs]
    assert calls == []
