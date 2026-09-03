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


def raw_compare(ahead_by, behind_by=0, last_commit_date=None):
    """A `compare` response shape - only what `unmerged_branches` reads:
    `ahead_by`/`behind_by`, and `commits`, whose last entry supplies the
    branch's own most recent commit date."""
    commits = []
    if last_commit_date is not None:
        commits = [{"commit": {"author": {"date": last_commit_date}}}]
    return {"ahead_by": ahead_by, "behind_by": behind_by, "commits": commits}


def raw_pull(number, *, login="me", draft=False, title="Add widget", created_at=None):
    return {
        "number": number,
        "title": title,
        "draft": draft,
        "user": {"login": login},
        "created_at": created_at or "2026-08-30T00:00:00Z",
    }


def route_handler(*, branches, compares, pulls, calls=None):
    """Dispatches a fake transport by URL path/params, covering every endpoint
    `unmerged_branches`/`open_pull_requests` touches: the branch list,
    `/compare/{base}...{head}`, and `/pulls?state=open`. `calls`, if given,
    collects every request path seen - used to assert the D8 request bound.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append(path)

        if path.endswith("/branches"):
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=branches if page == 1 else [])

        if "/compare/" in path:
            head = path.rsplit("...", 1)[-1]
            return httpx.Response(200, json=compares.get(head, raw_compare(0, 0)))

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
        compares={"feature-x": raw_compare(2, last_commit_date="2026-08-30T00:00:00Z")},
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
        compares={
            "feature-x": raw_compare(4, last_commit_date=last_commit.strftime("%Y-%m-%dT%H:%M:%SZ"))
        },
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
        compares={"diverged": raw_compare(2, behind_by=5, last_commit_date="2026-08-20T00:00:00Z")},
        pulls=[],
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    assert [b.name for b in result] == ["diverged"]


def test_branch_behind_but_not_ahead_is_excluded():
    branches = [raw_branch("main"), raw_branch("stale")]
    handler = route_handler(
        branches=branches,
        compares={"stale": raw_compare(0, behind_by=5, last_commit_date="2020-01-01T00:00:00Z")},
        pulls=[],
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    assert result == []


def test_branch_identical_to_default_is_excluded():
    branches = [raw_branch("main"), raw_branch("same")]
    handler = route_handler(
        branches=branches,
        compares={"same": raw_compare(0, behind_by=0)},
        pulls=[],
    )
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    assert result == []


def test_at_most_20_branches_are_compared_and_total_requests_stay_bounded():
    """D8 (amending D3): a 40-branch repo must cost at most ~2 list-pagination
    requests plus 20 `compare` calls - not one request per branch to sort by
    recency first. Only the first 20 non-default branches, in the order the
    branches API returns them, are ever compared; there is no recency sort."""
    branches = [raw_branch("main")]
    compares = {}
    for i in range(40):
        name = f"b{i:02d}"
        branches.append(raw_branch(name))
        compares[name] = raw_compare(1, last_commit_date="2026-08-01T00:00:00Z")

    calls: list[str] = []
    handler = route_handler(branches=branches, compares=compares, pulls=[], calls=calls)
    gh = make_gh(handler)

    result = gh.unmerged_branches("me/demo", default_branch="main")

    compare_calls = [c for c in calls if "/compare/" in c]
    assert len(compare_calls) == BRANCH_COMPARE_CAP == 20
    assert len(result) == 20
    # bounded total: at most 2 branch-list pages + 20 compares, well under 40
    assert len(calls) <= 22
    # the first 20 branches in API order are compared, not a recency subset
    assert {b.name for b in result} == {f"b{i:02d}" for i in range(20)}


# --- open_pull_requests ----------------------------------------------------------


def test_draft_prs_are_included_and_marked():
    pulls = [raw_pull(5, login="me", draft=True, title="WIP thing")]
    handler = route_handler(branches=[raw_branch("main")], compares={}, pulls=pulls)
    gh = make_gh(handler)

    (pr,) = gh.open_pull_requests("me/demo", github_user="me")

    assert pr.number == 5
    assert pr.draft is True


def test_prs_opened_by_someone_else_are_excluded():
    pulls = [raw_pull(1, login="me"), raw_pull(2, login="someone-else")]
    handler = route_handler(branches=[raw_branch("main")], compares={}, pulls=pulls)
    gh = make_gh(handler)

    result = gh.open_pull_requests("me/demo", github_user="me")

    assert [p.number for p in result] == [1]


def test_pr_author_match_is_case_insensitive():
    pulls = [raw_pull(1, login="ME")]
    handler = route_handler(branches=[raw_branch("main")], compares={}, pulls=pulls)
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
    handler = route_handler(branches=[raw_branch("main")], compares={}, pulls=pulls)
    gh = make_gh(handler)

    (pr,) = gh.open_pull_requests("me/demo", github_user="me")

    assert pr.title == "Fix the thing"
    assert pr.age_days == 10


# --- empty case ------------------------------------------------------------------


def test_repo_with_no_branches_beyond_default_and_no_open_prs_returns_two_empty_lists():
    handler = route_handler(branches=[raw_branch("main")], compares={}, pulls=[])
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
        compares={"feature-x": raw_compare(1, last_commit_date="2026-08-20T00:00:00Z")},
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
