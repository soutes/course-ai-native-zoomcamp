"""`render_report_markdown`'s "Stale goals" section (#30, docs/decisions.md D29).

No Django, no LLM, no network - `goal_stale`/`weeks_since_goal_set` are passed
in already computed, the same precomputed-field pattern
`tests/test_report_render.py` already uses for `weeks_since_last_commit`/`stalled`.
"""

from __future__ import annotations

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


def test_absent_when_nothing_flagged():
    repos = [make_repo(repo="me/alpha", goal="Ship v1.", goal_stale=False)]
    data = WeeklyReportData(week="2026-W36", repos=repos, coaching=None)

    md = render_report_markdown(data)

    assert "## Stale goals" not in md


def test_absent_with_no_tracked_repos():
    data = WeeklyReportData(week="2026-W36", repos=[], coaching=None)

    md = render_report_markdown(data)

    assert "## Stale goals" not in md


# --- present cases ------------------------------------------------------------------


def test_present_and_independent_of_coaching_being_none():
    repos = [
        make_repo(
            repo="me/ghost",
            goal="Ship v1.",
            goal_set_at=None,
            weeks_since_goal_set=8,
            goal_stale=True,
        )
    ]
    data = WeeklyReportData(week="2026-W36", repos=repos, coaching=None)

    md = render_report_markdown(data)

    assert "## Stale goals" in md
    section = md.split("## Stale goals")[1]
    assert "me/ghost" in section
    assert "Ship v1." in section
    assert "8 week" in section
    assert "nothing shipped" in section.lower()


def test_present_with_coaching_too():
    from portfolio.coach import CoachingResult

    repos = [
        make_repo(
            repo="me/ghost",
            goal="Ship v1.",
            weeks_since_goal_set=8,
            goal_stale=True,
        )
    ]
    coaching = CoachingResult(advice={}, unavailable=[], drift={})
    data = WeeklyReportData(week="2026-W36", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    assert "## Stale goals" in md


def test_only_flagged_repos_get_a_line():
    repos = [
        make_repo(repo="me/ghost", goal="Ship v1.", weeks_since_goal_set=8, goal_stale=True),
        make_repo(repo="me/fine", goal="Ship v2.", weeks_since_goal_set=8, goal_stale=False),
    ]
    data = WeeklyReportData(week="2026-W36", repos=repos, coaching=None)

    md = render_report_markdown(data)

    section = md.split("## Stale goals")[1]
    assert "me/ghost" in section
    assert "me/fine" not in section


def test_stale_goals_is_separate_from_goal_check():
    from portfolio.coach import CoachingResult

    repos = [
        make_repo(
            repo="me/ghost",
            goal="Ship v1.",
            commits=0,
            weeks_since_goal_set=8,
            goal_stale=True,
        )
    ]
    coaching = CoachingResult(advice={}, unavailable=[], drift={"me/ghost": "Drifted."})
    data = WeeklyReportData(week="2026-W36", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    # "Goal check" skips 0-commit repos (its own rule) - only "Stale goals" fires here.
    assert "## Goal check" not in md
    assert "## Stale goals" in md


def test_stale_goals_is_the_last_section():
    from portfolio.coach import CoachingResult

    repos = [
        make_repo(
            repo="me/ghost",
            goal="Ship v1.",
            commits=5,
            weeks_since_goal_set=8,
            goal_stale=True,
        )
    ]
    coaching = CoachingResult(advice={}, unavailable=[], drift={"me/ghost": "On track."})
    data = WeeklyReportData(week="2026-W36", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    headings = [
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
        "## Goal check",
        "## Stale goals",
    ]
    positions = [md.index(h) for h in headings]
    assert positions == sorted(positions)
