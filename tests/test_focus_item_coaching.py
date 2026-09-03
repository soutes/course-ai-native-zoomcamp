"""`_focus_item_text`'s coaching wording (#28, D27).

Selection of which repo the focus targets stays #16's existing deterministic
algorithm - these tests only exercise D27's added wording split: usable
`coaching.advice` for the selected repo replaces the sentence's wording;
`coaching is None`, or the selected repo missing from `advice`/in
`unavailable`, falls back to today's unchanged deterministic sentence. No
Django, no LLM, no network - `CoachingResult` is built by hand in every test.
"""

from __future__ import annotations

from portfolio.coach import CoachingResult
from portfolio.services.render import (
    RepoReportData,
    WeeklyReportData,
    build_report_snapshot,
    render_report_markdown,
)


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


def _focus_section(md: str) -> str:
    return md.split("## This week's focus")[1]


def _bullet_lines(section: str) -> list[str]:
    return [line for line in section.strip().splitlines() if line.strip()]


# --- coaching=None: fallback --------------------------------------------------------


def test_coaching_none_renders_unchanged_deterministic_sentence():
    repos = [
        make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True),
        make_repo(repo="me/beta", commits=5),
        make_repo(repo="me/gamma", commits=3),
    ]
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=None)

    md = render_report_markdown(data)
    section = _focus_section(md)

    assert "me/alpha" in section
    assert "8 week" in section
    assert "This week:" not in section  # not the coaching template
    assert len(_bullet_lines(section)) == 1


# --- selected repo has usable advice: coaching line used ----------------------------


def test_selected_repo_with_usable_advice_uses_coaching_template():
    repos = [
        make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True),
        make_repo(repo="me/beta", commits=5),
    ]
    coaching = CoachingResult(
        advice={"me/alpha": "open the first issue and land one commit"}, unavailable=[]
    )
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)
    section = _focus_section(md)

    assert "This week: **me/alpha** - open the first issue and land one commit" in section
    assert len(_bullet_lines(section)) == 1


def test_coaching_never_changes_which_repo_is_selected():
    """Advice present for a *non-selected* repo must not steal the focus (D27 point 1)."""
    repos = [
        make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True),
        make_repo(repo="me/beta", commits=5),
    ]
    coaching = CoachingResult(advice={"me/beta": "keep shipping"}, unavailable=[])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)
    section = _focus_section(md)

    # me/alpha is still #16's deterministic pick (worst silent repo) - the
    # deterministic sentence renders, unaffected by me/beta's advice.
    assert "me/alpha" in section
    assert "This week:" not in section


# --- selected repo in unavailable/missing: fallback ----------------------------------


def test_selected_repo_in_unavailable_falls_back_to_deterministic_sentence():
    repos = [make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True)]
    coaching = CoachingResult(advice={}, unavailable=["me/alpha"])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)
    section = _focus_section(md)

    assert "me/alpha" in section
    assert "8 week" in section
    assert "This week:" not in section
    assert len(_bullet_lines(section)) == 1


def test_selected_repo_missing_from_advice_falls_back_to_deterministic_sentence():
    repos = [make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True)]
    coaching = CoachingResult(advice={"me/other": "irrelevant"}, unavailable=[])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)
    section = _focus_section(md)

    assert "me/alpha" in section
    assert "This week:" not in section


# --- exactly one, always last --------------------------------------------------------


def test_focus_item_is_exactly_one_line_and_last_in_output_with_coaching():
    repos = [
        make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True),
        make_repo(repo="me/beta", commits=5),
        make_repo(repo="me/gamma", commits=1),
        make_repo(repo="me/delta", commits=0, weeks_since_last_commit=2),
    ]
    coaching = CoachingResult(advice={"me/alpha": "land one commit"}, unavailable=[])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    md = render_report_markdown(data)

    section = _focus_section(md)
    assert section.strip() == "This week: **me/alpha** - land one commit"
    assert len(_bullet_lines(section)) == 1

    headings = [
        "## What went well",
        "## What went wrong",
        "## What I'm doing",
        "## This week's focus",
    ]
    positions = [md.index(h) for h in headings]
    assert positions == sorted(positions)
    assert positions[-1] == max(positions)


def test_snapshot_focus_also_uses_coaching_wording():
    repos = [make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True)]
    coaching = CoachingResult(advice={"me/alpha": "land one commit"}, unavailable=[])
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=coaching)

    snapshot = build_report_snapshot(data)

    assert snapshot["focus"] == "This week: **me/alpha** - land one commit"


def test_snapshot_focus_falls_back_when_coaching_is_none():
    repos = [make_repo(repo="me/alpha", commits=0, weeks_since_last_commit=8, stalled=True)]
    data = WeeklyReportData(week="2026-W35", repos=repos, coaching=None)

    snapshot = build_report_snapshot(data)

    assert "This week:" not in snapshot["focus"]
    assert "me/alpha" in snapshot["focus"]
