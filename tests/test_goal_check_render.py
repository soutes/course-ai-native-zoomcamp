"""`render_report_markdown`'s "Goal check" section (#29, docs/decisions.md D28).

No Django, no LLM, no network - `CoachingResult` is built by hand in every test,
the same pattern `tests/test_focus_item_coaching.py` (#28) already uses.
"""

from __future__ import annotations

from portfolio.coach import CoachingResult
from portfolio.services.render import RepoReportData, WeeklyReportData, render_report_markdown


def make_repo(**overrides) -> RepoReportData:
    defaults = dict(
        repo="me/demo",
        commits=5,
        active_days=3,
        lines_added=40,
        lines_removed=10,
        files_touched=6,
        partial=False,
        weeks_since_last_commit=0,
        stalled=False,
        unmerged_branches=[],
        open_pull_requests=[],
    )
    defaults.update(overrides)
    return RepoReportData(**defaults)


# --- absent cases -----------------------------------------------------------------


def test_absent_when_coaching_is_none():
    repos = [make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)]
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=None)

    md = render_report_markdown(data)

    assert "## Goal check" not in md


def test_absent_when_no_repo_has_a_goal():
    repos = [make_repo(repo="me/alpha", goal="", commits=5)]
    coaching = CoachingResult(drift={}, drift_unavailable=[])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    assert "## Goal check" not in md


def test_absent_when_goal_bearing_repo_had_no_commits():
    repos = [make_repo(repo="me/alpha", goal="Ship a v1.", commits=0)]
    coaching = CoachingResult(drift={}, drift_unavailable=[])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    assert "## Goal check" not in md


def test_absent_when_goal_bearing_repo_has_no_drift_entry():
    repos = [make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)]
    coaching = CoachingResult(drift={}, drift_unavailable=["me/alpha"])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    assert "## Goal check" not in md


# --- present case -------------------------------------------------------------------


def test_present_when_a_repo_has_a_resolved_drift_verdict():
    repos = [
        make_repo(repo="me/alpha", goal="Ship a v1.", commits=5),
        make_repo(repo="me/beta", goal="", commits=3),
    ]
    coaching = CoachingResult(
        advice={}, unavailable=[], drift={"me/alpha": 'On track - see "fix bug".'}
    )
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    assert "## Goal check" in md
    section = md.split("## Goal check")[1]
    assert "me/alpha" in section
    assert "Ship a v1." in section
    assert "fix bug" in section
    assert "me/beta" not in section


def test_goal_check_is_the_last_section_after_focus():
    repos = [make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)]
    coaching = CoachingResult(advice={}, unavailable=[], drift={"me/alpha": "On track."})
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    headings = [
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
        "## Goal check",
    ]
    positions = [md.index(h) for h in headings]
    assert positions == sorted(positions)


def test_multiple_eligible_repos_each_get_a_line():
    repos = [
        make_repo(repo="me/alpha", goal="Ship a v1.", commits=5),
        make_repo(repo="me/beta", goal="Ship a v2.", commits=2),
    ]
    coaching = CoachingResult(
        advice={},
        unavailable=[],
        drift={"me/alpha": "On track.", "me/beta": "Drifted - see docs commit."},
    )
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    section = md.split("## Goal check")[1]
    assert "me/alpha" in section
    assert "me/beta" in section


# --- four existing sections untouched -------------------------------------------------


def test_existing_four_sections_and_focus_item_unaffected():
    repos = [
        make_repo(repo="me/alpha", goal="Ship a v1.", commits=0, weeks_since_last_commit=8),
        make_repo(repo="me/beta", goal="Ship a v2.", commits=5),
    ]
    coaching = CoachingResult(advice={}, unavailable=[], drift={})
    data_with = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)
    data_without = WeeklyReportData(week="2026-W35", repos=repos, coaching=None)

    md_with = render_report_markdown(data_with)
    md_without = render_report_markdown(data_without)

    for heading in (
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
    ):
        before_goal_with = (
            md_with.split("## Goal check")[0] if "## Goal check" in md_with else md_with
        )
        assert heading in before_goal_with
        assert heading in md_without
