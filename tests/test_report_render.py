"""`render.render_report_markdown` / `build_report_snapshot` (#16) - pure rendering,
tested from fixtures. No Rich console, no Django, no network, no LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime

from portfolio.services.health import HealthSignals
from portfolio.services.render import (
    RepoReportData,
    WeeklyReportData,
    abandoned_count,
    build_report_snapshot,
    render_report_markdown,
)
from portfolio.services.types import NewRepo, OpenPullRequest, UnmergedBranch

NOW = datetime.now(UTC)


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


# --- section order and headings ---------------------------------------------------


def test_four_sections_render_in_order():
    data = WeeklyReportData(week="2026-W35", repos=[make_repo()])

    md = render_report_markdown(data)

    order = [
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
    ]
    positions = [md.index(h) for h in order]
    assert positions == sorted(positions)


def test_week_label_appears_in_the_heading():
    data = WeeklyReportData(week="2026-W35", repos=[make_repo()])
    assert "2026-W35" in render_report_markdown(data)


# --- every claim carries a repo name and a number ----------------------------------


def test_went_well_line_carries_repo_name_and_numbers():
    repo = make_repo(
        repo="me/busy",
        commits=12,
        active_days=4,
        lines_added=300,
        lines_removed=50,
        files_touched=9,
    )
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    assert "me/busy" in md
    assert "12 commit" in md
    assert "300" in md and "50" in md and "9" in md


def test_went_wrong_line_carries_repo_name_and_weeks_number():
    repo = make_repo(repo="me/quiet", commits=0, weeks_since_last_commit=6, stalled=True)
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    assert "me/quiet" in md
    assert "6 week" in md


# --- "What went wrong" is never empty ------------------------------------------------


def test_what_went_wrong_lists_silent_repos():
    silent = make_repo(repo="me/silent", commits=0, weeks_since_last_commit=2, stalled=False)
    busy = make_repo(repo="me/busy", commits=3)
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[silent, busy]))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "me/silent" in wrong_section
    assert "me/busy" not in wrong_section


def test_what_went_wrong_is_never_empty_when_every_project_moved():
    """The spread-failure fallback: nothing is literally silent, but the section
    still says something, with a repo name and a number, not nothing."""
    repos = [
        make_repo(repo="me/alpha", commits=20),
        make_repo(repo="me/beta", commits=1),
    ]
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=repos))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0].strip()
    assert wrong_section != ""
    assert "tracked projects" not in wrong_section  # not the "nothing tracked" fallback
    assert "me/beta" in wrong_section  # the weakest of the two, spread thin
    assert any(ch.isdigit() for ch in wrong_section)


def test_what_went_wrong_never_empty_even_with_a_single_moving_repo():
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[make_repo(commits=1)]))
    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0].strip()
    assert wrong_section != ""


# --- exactly one focus item ---------------------------------------------------------


def test_focus_section_has_exactly_one_bullet_for_many_repos():
    repos = [
        make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True),
        make_repo(repo="me/beta", commits=0, weeks_since_last_commit=2, stalled=False),
        make_repo(repo="me/gamma", commits=5),
    ]
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=repos))

    focus_section = md.split("## This week's focus")[1].strip()
    bullet_lines = [line for line in focus_section.splitlines() if line.strip()]
    assert len(bullet_lines) == 1


def test_focus_picks_the_most_stalled_silent_repo():
    repos = [
        make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True),
        make_repo(repo="me/beta", commits=0, weeks_since_last_commit=2, stalled=False),
        make_repo(repo="me/gamma", commits=5),
    ]
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=repos))
    focus_section = md.split("## This week's focus")[1]

    assert "me/alpha" in focus_section
    assert "me/beta" not in focus_section
    assert "8 week" in focus_section


def test_focus_falls_back_to_mid_flight_work_when_nothing_is_silent():
    old_branch = UnmergedBranch(name="feature-x", ahead_by=3, last_commit_at=NOW)
    repo = make_repo(repo="me/alpha", commits=5, unmerged_branches=[old_branch])
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))
    focus_section = md.split("## This week's focus")[1]

    assert "feature-x" in focus_section
    assert "me/alpha" in focus_section


def test_focus_falls_back_to_weakest_repo_when_everything_is_fine():
    repos = [make_repo(repo="me/alpha", commits=20), make_repo(repo="me/beta", commits=2)]
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=repos))
    focus_section = md.split("## This week's focus")[1]

    bullet_lines = [line for line in focus_section.strip().splitlines() if line.strip()]
    assert len(bullet_lines) == 1
    assert "me/beta" in focus_section  # the weakest of the two


def test_focus_handles_never_committed_repo():
    """Even the never-committed branch of the focus item is a "claim" (#16's
    own AC) - it must carry a repo name AND a number, not just prose."""
    repo = make_repo(repo="me/ghost", commits=0, weeks_since_last_commit=None, stalled=True)
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))
    focus_section = md.split("## This week's focus")[1]

    assert "me/ghost" in focus_section
    assert any(ch.isdigit() for ch in focus_section)
    assert "0 commit" in focus_section


# --- a week where nothing at all happened still renders all four sections ----------


def test_empty_portfolio_still_renders_all_four_sections():
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[]))

    for heading in (
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
    ):
        assert heading in md

    focus_section = md.split("## This week's focus")[1].strip()
    bullet_lines = [line for line in focus_section.splitlines() if line.strip()]
    assert len(bullet_lines) == 1


def test_all_repos_silent_week_still_renders_plainly():
    repos = [
        make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=1, stalled=False),
        make_repo(repo="me/beta", commits=0, weeks_since_last_commit=1, stalled=False),
    ]
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=repos))

    well_section = md.split("## What went well")[1].split("## What went wrong")[0]
    assert "No repo moved" in well_section
    assert "0 of 2" in well_section


# --- brackets in dynamic text render literally (no Rich markup swallowing) --------


def test_pr_title_with_brackets_survives_in_the_markdown():
    pr = OpenPullRequest(number=7, title="[WIP] add feature", created_at=NOW, draft=False)
    repo = make_repo(repo="me/alpha", commits=5, open_pull_requests=[pr])
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    assert "[WIP] add feature" in md


def test_repo_description_with_brackets_renders_literally_in_went_well():
    repo = make_repo(
        repo="me/alpha", commits=5, description="a repo with [brackets] in its description"
    )
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    well_section = md.split("## What went well")[1].split("## What went wrong")[0]
    assert "a repo with [brackets] in its description" in well_section


def test_repo_description_with_brackets_renders_literally_in_went_wrong():
    repo = make_repo(
        repo="me/quiet",
        commits=0,
        weeks_since_last_commit=3,
        description="tracks [issue-42] work",
    )
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "tracks [issue-42] work" in wrong_section


def test_commit_subject_with_brackets_renders_literally_and_is_the_latest_one():
    repo = make_repo(
        repo="me/alpha",
        commits=2,
        commit_subjects=["first pass", "[urgent] fix bracket bug"],
    )
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    well_section = md.split("## What went well")[1].split("## What went wrong")[0]
    assert "[urgent] fix bracket bug" in well_section


# --- new repos appear under "What I'm doing" ---------------------------------------


def test_new_repo_callout_appears_in_doing_section():
    new_repo = NewRepo(name="fresh-start", created_at=NOW, commits=2)
    data = WeeklyReportData(week="2026-W35", repos=[make_repo()], new_repos=[new_repo])
    md = render_report_markdown(data)

    doing_section = md.split("## What I'm doing")[1].split("## This week's focus")[0]
    assert "fresh-start" in doing_section
    assert "2 commit" in doing_section


def test_doing_section_never_empty_when_nothing_mid_flight():
    data = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/quiet-worker")])
    md = render_report_markdown(data)

    doing_section = md.split("## What I'm doing")[1].split("## This week's focus")[0].strip()
    assert doing_section != ""
    assert "me/quiet-worker" in doing_section


# --- coaching = None always works ---------------------------------------------------


def test_renders_fully_with_coaching_none():
    data = WeeklyReportData(week="2026-W35", repos=[make_repo()], coaching=None)
    md = render_report_markdown(data)
    assert "## This week's focus" in md


# --- snapshot for persistence (D5) --------------------------------------------------


def test_snapshot_carries_mid_flight_new_repos_and_focus_but_not_momentum_numbers():
    branch = UnmergedBranch(name="feature-x", ahead_by=2, last_commit_at=NOW)
    pr = OpenPullRequest(number=3, title="Fix thing", created_at=NOW, draft=False)
    repo = make_repo(
        repo="me/alpha",
        commits=0,
        weeks_since_last_commit=5,
        stalled=True,
        unmerged_branches=[branch],
        open_pull_requests=[pr],
    )
    new_repo = NewRepo(name="fresh", created_at=NOW, commits=1)
    data = WeeklyReportData(week="2026-W35", repos=[repo], new_repos=[new_repo])

    snapshot = build_report_snapshot(data)

    assert snapshot["week"] == "2026-W35"
    row = snapshot["repos"][0]
    assert row["repo"] == "me/alpha"
    assert row["weeks_since_last_commit"] == 5
    assert row["stalled"] is True
    assert row["unmerged_branches"][0]["name"] == "feature-x"
    assert row["open_pull_requests"][0]["number"] == 3
    assert "commits" not in row  # momentum numbers live in RepoWeek, not here
    assert "lines_added" not in row
    assert snapshot["new_repos"][0]["name"] == "fresh"
    assert "me/alpha" in snapshot["focus"]


def test_snapshot_is_json_serializable():
    import json

    repo = make_repo(commits=0, weeks_since_last_commit=None, stalled=True)
    data = WeeklyReportData(week="2026-W35", repos=[repo])

    json.dumps(build_report_snapshot(data))  # must not raise


# --- abandoned_count (D4, #36) -----------------------------------------------------


def test_abandoned_count_counts_stalled_repo_report_data():
    repos = [
        make_repo(repo="me/fine", stalled=False),
        make_repo(repo="me/stalled-one", stalled=True),
        make_repo(repo="me/stalled-two", stalled=True),
    ]
    assert abandoned_count(repos) == 2


def test_abandoned_count_zero_when_nothing_stalled():
    repos = [make_repo(stalled=False), make_repo(repo="me/other", stalled=False)]
    assert abandoned_count(repos) == 0


def test_abandoned_count_empty_portfolio():
    assert abandoned_count([]) == 0


def test_abandoned_count_reads_dicts_from_the_stored_weeklyreport_snapshot():
    """D5: #36 reads `WeeklyReport.data["repos"]`, plain dicts, not `RepoReportData`
    instances - the shared helper must accept either shape without conversion."""
    repos = [
        {"repo": "me/fine", "stalled": False},
        {"repo": "me/stalled", "stalled": True},
    ]
    assert abandoned_count(repos) == 1


def test_abandoned_count_matches_build_report_snapshot_output():
    """The helper stays consistent whether fed the live dataclasses (#16's own path)
    or the JSON snapshot those dataclasses were persisted as (#36's path) - the two
    must never drift (D4's whole point)."""
    repos = [
        make_repo(repo="me/alpha", stalled=True),
        make_repo(repo="me/beta", stalled=False),
    ]
    data = WeeklyReportData(week="2026-W35", repos=repos)
    snapshot = build_report_snapshot(data)

    assert abandoned_count(repos) == abandoned_count(snapshot["repos"]) == 1


# --- health signals feed "What went wrong" (#18) ------------------------------------


def unhealthy(**overrides) -> HealthSignals:
    defaults = dict(
        missing_readme=True,
        missing_tests=True,
        missing_ci=True,
        missing_license=True,
        missing_description=True,
    )
    defaults.update(overrides)
    return HealthSignals(**defaults)


def healthy() -> HealthSignals:
    return HealthSignals(
        missing_readme=False,
        missing_tests=False,
        missing_ci=False,
        missing_license=False,
        missing_description=False,
    )


def test_healthy_repo_produces_no_health_noise_in_went_wrong():
    repo = make_repo(repo="me/tidy", commits=3, health=healthy())
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "missing" not in wrong_section


def test_repo_with_no_health_computed_produces_no_health_noise():
    repo = make_repo(repo="me/unknown-health", commits=3, health=None)
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "missing" not in wrong_section


def test_unhealthy_repo_lists_its_missing_signals_in_went_wrong():
    repo = make_repo(
        repo="me/scruffy",
        commits=3,
        health=unhealthy(missing_readme=True, missing_ci=True, missing_tests=False),
    )
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "me/scruffy" in wrong_section
    assert "README" in wrong_section
    assert "CI" in wrong_section
    assert "license" in wrong_section
    assert "description" in wrong_section
    assert "tests" not in wrong_section.split("me/scruffy")[1].split("\n")[0]


def test_unhealthy_repo_flagged_even_when_every_project_moved():
    """The "nothing stalled, spread thin" fallback line must not swallow health
    noise for a different, otherwise-fine repo."""
    repos = [
        make_repo(repo="me/alpha", commits=20, health=healthy()),
        make_repo(repo="me/beta", commits=1, health=unhealthy()),
    ]
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=repos))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "me/beta" in wrong_section
    assert "missing" in wrong_section


def test_unhealthy_silent_repo_gets_both_silence_and_health_lines():
    repo = make_repo(
        repo="me/quiet", commits=0, weeks_since_last_commit=6, stalled=True, health=unhealthy()
    )
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "6 week" in wrong_section  # the existing silence line, untouched
    assert "missing" in wrong_section  # plus the health line


def test_truncated_tree_health_produces_no_noise_when_license_and_description_are_fine():
    """Unknown (truncated-tree) signals are never rendered as missing noise -
    see `health.judge_health`."""
    repo = make_repo(
        repo="me/big-repo",
        commits=3,
        health=HealthSignals(
            missing_readme=None,
            missing_tests=None,
            missing_ci=None,
            missing_license=False,
            missing_description=False,
            tree_truncated=True,
        ),
    )
    md = render_report_markdown(WeeklyReportData(week="2026-W35", repos=[repo]))

    wrong_section = md.split("## What went wrong")[1].split("## What I'm doing")[0]
    assert "missing" not in wrong_section
