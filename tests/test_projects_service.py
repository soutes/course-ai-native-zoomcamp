"""portfolio.services.projects - pure grouping/shaping, no Django, no network (D12)."""

from dataclasses import dataclass

from portfolio.services.projects import STATUS_ORDER, group_projects, triage_history


@dataclass
class FakeProject:
    repo: str
    status: str


def test_group_projects_buckets_by_status_and_counts():
    rows = [
        FakeProject("a", "active"),
        FakeProject("b", "active"),
        FakeProject("c", "paused"),
        FakeProject("d", "shipped"),
        FakeProject("e", "dropped"),
    ]

    result = group_projects(rows)

    assert result["counts"] == {"active": 2, "paused": 1, "shipped": 1, "dropped": 1}
    assert result["total"] == 5
    assert [p.repo for p in result["groups"]["active"]] == ["a", "b"]
    assert set(result["groups"].keys()) == set(STATUS_ORDER)


def test_group_projects_empty_input_gives_all_zero_counts():
    result = group_projects([])

    assert result["total"] == 0
    assert all(count == 0 for count in result["counts"].values())
    assert all(rows == [] for rows in result["groups"].values())


def test_triage_history_shapes_run_and_hidden_count_only():
    runs = [{"ran_at": "2026-01-01", "hidden_count": 3}]

    history = triage_history(runs)

    assert history == [{"ran_at": "2026-01-01", "hidden_count": 3}]
