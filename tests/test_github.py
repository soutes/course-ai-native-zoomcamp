"""`GitHub.commits_in_window` (#12), tested against a fake transport - no network.

Every test builds an `httpx.MockTransport` handler and swaps it onto a real
`GitHub` client, so the pagination/caching/`_get` plumbing in
`portfolio.services.github` runs exactly as it would in production; only the
socket is faked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from portfolio.services.cache import Cache
from portfolio.services.github import API, GitHub

ME = "me@example.com"
ME_WORK = "me@work.example.com"
OTHER = "someone-else@example.com"


def raw_commit(
    sha,
    *,
    email=ME,
    committer_email=None,
    date="2026-08-31T10:00:00Z",
    message="Fix the thing\n\nlonger body",
    parents=1,
):
    return {
        "sha": sha,
        "commit": {
            "author": {"name": "Me", "email": email, "date": date},
            "committer": {"name": "Committer", "email": committer_email or email, "date": date},
            "message": message,
        },
        "author": {"login": "me"},
        "committer": {"login": "someone"},
        "parents": [{"sha": f"parent-{sha}-{i}"} for i in range(parents)],
        "html_url": f"https://github.com/me/demo/commit/{sha}",
    }


def make_gh(handler, *, cache=None):
    gh = GitHub(token="fake-token", cache=cache or Cache("test-github", enabled=False))
    gh.client = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return gh


def json_handler(pages_by_number, status=200):
    """pages_by_number: {page_number: [raw_commit, ...]}. Missing pages -> []."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(status, json=pages_by_number.get(page, []))

    return handler


WINDOW_UTC = (
    datetime(2026, 8, 31, 0, 0, 0, tzinfo=UTC),
    datetime(2026, 9, 6, 23, 59, 59, 999999, tzinfo=UTC),
)


# --- pagination --------------------------------------------------------------


def test_pagination_follows_to_the_end_beyond_100_commits():
    page1 = [raw_commit(f"c{i}") for i in range(100)]
    page2 = [raw_commit(f"c{i}") for i in range(100, 150)]
    gh = make_gh(json_handler({1: page1, 2: page2}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert len(commits) == 150
    assert {c.sha for c in commits} == {f"c{i}" for i in range(150)}


def test_a_full_page_of_exactly_100_still_stops_when_the_next_page_is_empty():
    page1 = [raw_commit(f"c{i}") for i in range(100)]
    gh = make_gh(json_handler({1: page1, 2: []}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert len(commits) == 100


# --- merge-commit exclusion ---------------------------------------------------


def test_merge_commits_are_excluded():
    page1 = [
        raw_commit("normal", parents=1),
        raw_commit("merge", parents=2),
    ]
    gh = make_gh(json_handler({1: page1}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert [c.sha for c in commits] == ["normal"]


# --- dedup ---------------------------------------------------------------------


def test_same_sha_returned_twice_is_counted_once():
    page1 = [raw_commit("dup"), raw_commit("dup")]
    gh = make_gh(json_handler({1: page1}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert [c.sha for c in commits] == ["dup"]


def test_authored_by_me_but_committed_by_someone_else_counts_once():
    """Rebase/merge can leave `commit.committer` different from `commit.author` -
    still one commit, matched on the author email per D1, not the committer's."""
    page1 = [raw_commit("rebased", email=ME, committer_email=OTHER)]
    gh = make_gh(json_handler({1: page1}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert [c.sha for c in commits] == ["rebased"]


# --- authorship matching (D1) --------------------------------------------------


def test_commit_authored_by_someone_else_in_my_repo_is_excluded():
    page1 = [raw_commit("mine", email=ME), raw_commit("theirs", email=OTHER)]
    gh = make_gh(json_handler({1: page1}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert [c.sha for c in commits] == ["mine"]


def test_matches_against_any_email_in_the_configured_list():
    page1 = [raw_commit("from-work", email=ME_WORK), raw_commit("from-personal", email=ME)]
    gh = make_gh(json_handler({1: page1}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME, ME_WORK])

    assert {c.sha for c in commits} == {"from-work", "from-personal"}


def test_email_matching_is_case_insensitive():
    page1 = [raw_commit("shouty", email=ME.upper())]
    gh = make_gh(json_handler({1: page1}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert [c.sha for c in commits] == ["shouty"]


# --- empty / zero-commit weeks -------------------------------------------------


def test_empty_repo_409_returns_empty_list():
    gh = make_gh(json_handler({}, status=409))

    commits = gh.commits_in_window("me/empty-repo", WINDOW_UTC, [ME])

    assert commits == []


def test_zero_commits_in_week_returns_empty_list_not_error():
    gh = make_gh(json_handler({1: []}))

    commits = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert commits == []


# --- commit shape: sha, authored date, subject ---------------------------------


def test_each_commit_carries_sha_authored_date_and_subject():
    page1 = [
        raw_commit(
            "shaval",
            date="2026-09-01T08:30:00Z",
            message="Add the widget\n\nDetails that must not leak into subject.",
        )
    ]
    gh = make_gh(json_handler({1: page1}))

    (commit,) = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert commit.sha == "shaval"
    assert commit.authored_at == datetime(2026, 9, 1, 8, 30, 0, tzinfo=UTC)
    assert commit.subject == "Add the widget"


# --- since/until sent as UTC ISO-8601, converted from the local window ---------


def test_since_until_are_sent_as_utc_converted_from_local_window():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["since"] = request.url.params["since"]
        captured["until"] = request.url.params["until"]
        return httpx.Response(200, json=[])

    tz = ZoneInfo("America/Sao_Paulo")  # UTC-3, no DST since 2019
    local_window = (
        datetime(2026, 8, 31, 0, 0, 0, tzinfo=tz),
        datetime(2026, 9, 6, 23, 59, 59, 999999, tzinfo=tz),
    )
    gh = make_gh(handler)

    gh.commits_in_window("me/demo", local_window, [ME])

    assert captured["since"] == "2026-08-31T03:00:00Z"
    assert captured["until"] == "2026-09-07T02:59:59Z"


# --- caching: a re-run costs zero requests (#5) --------------------------------


# --- commit_diffstat (#13) ------------------------------------------------------


def raw_commit_detail(sha, *, additions=5, deletions=2, files=None):
    if files is None:
        files = [
            {
                "filename": "a.py",
                "additions": additions,
                "deletions": deletions,
                "status": "modified",
            }
        ]
    return {
        "sha": sha,
        "stats": {"additions": additions, "deletions": deletions, "total": additions + deletions},
        "files": files,
    }


def test_commit_diffstat_reads_additions_deletions_and_file_count():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/me/demo/commits/abc123"
        return httpx.Response(200, json=raw_commit_detail("abc123", additions=12, deletions=4))

    gh = make_gh(handler)

    stat = gh.commit_diffstat("me/demo", "abc123")

    assert stat.sha == "abc123"
    assert stat.additions == 12
    assert stat.deletions == 4
    assert stat.files_changed == 1


def test_commit_diffstat_handles_binary_or_renamed_files_with_no_textual_diff():
    """A binary file or pure rename comes back with 0/0 additions/deletions and no
    `patch` key at all - must not raise, and still counts as a touched file."""
    files = [
        {"filename": "image.png", "additions": 0, "deletions": 0, "status": "modified"},
        {"filename": "old.txt", "additions": 0, "deletions": 0, "status": "renamed"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        detail = raw_commit_detail("bin", additions=0, deletions=0, files=files)
        return httpx.Response(200, json=detail)

    gh = make_gh(handler)

    stat = gh.commit_diffstat("me/demo", "bin")

    assert stat.additions == 0
    assert stat.deletions == 0
    assert stat.files_changed == 2


def test_commit_diffstat_missing_stats_or_files_defaults_to_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sha": "bare"})

    gh = make_gh(handler)

    stat = gh.commit_diffstat("me/demo", "bare")

    assert stat.additions == 0
    assert stat.deletions == 0
    assert stat.files_changed == 0


@pytest.mark.django_db
def test_commit_diffstat_is_cached_a_rerun_costs_zero_requests(settings, tmp_path):
    settings.WEEKLY_CACHE_DIR = tmp_path
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=raw_commit_detail("cached-sha"))

    cache = Cache("week-2026-W36", enabled=True)
    gh = make_gh(handler, cache=cache)
    first = gh.commit_diffstat("me/demo", "cached-sha")
    gh2 = make_gh(handler, cache=cache)
    second = gh2.commit_diffstat("me/demo", "cached-sha")

    assert first == second
    assert calls["n"] == 1


@pytest.mark.django_db
def test_rerun_hits_the_cache_not_the_network(settings, tmp_path):
    settings.WEEKLY_CACHE_DIR = tmp_path
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[raw_commit("cached-one")])

    cache = Cache("week-2026-W36", enabled=True)
    gh = make_gh(handler, cache=cache)

    first = gh.commits_in_window("me/demo", WINDOW_UTC, [ME])
    # Fresh GitHub instance, same cache namespace - simulates a second `manage.py`
    # invocation reading the same on-disk cache.
    gh2 = make_gh(handler, cache=cache)
    second = gh2.commits_in_window("me/demo", WINDOW_UTC, [ME])

    assert [c.sha for c in first] == [c.sha for c in second] == ["cached-one"]
    assert calls["n"] == 1


# --- GitHub.tree (#18) ---------------------------------------------------------


def tree_handler(entries, truncated=False, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"tree": [{"path": p, "type": "blob"} for p in entries], "truncated": truncated},
        )

    return handler


def test_tree_returns_every_path_from_the_recursive_response():
    gh = make_gh(tree_handler(["README.md", "src/main.py", "tests/test_main.py"]))

    result = gh.tree("me/demo", "main")

    assert result.paths == ["README.md", "src/main.py", "tests/test_main.py"]
    assert result.truncated is False


def test_tree_passes_through_the_truncated_flag():
    gh = make_gh(tree_handler(["a.py"], truncated=True))

    result = gh.tree("me/demo", "main")

    assert result.truncated is True


def test_tree_on_empty_default_branch_is_an_empty_non_truncated_listing_not_a_raise():
    """GitHub 404s `git/trees/{default}` for a repo with no commits yet - #18's
    AC: this must not raise, and must not look truncated."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    gh = make_gh(handler)

    result = gh.tree("me/empty", "main")

    assert result.paths == []
    assert result.truncated is False


@pytest.mark.django_db
def test_tree_is_cached_a_rerun_costs_zero_requests(settings, tmp_path):
    settings.WEEKLY_CACHE_DIR = tmp_path
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"tree": [{"path": "README.md", "type": "blob"}]})

    cache = Cache("week-2026-W36", enabled=True)
    gh = make_gh(handler, cache=cache)
    first = gh.tree("me/demo", "main")
    gh2 = make_gh(handler, cache=cache)
    second = gh2.tree("me/demo", "main")

    assert first.paths == second.paths == ["README.md"]
    assert calls["n"] == 1
