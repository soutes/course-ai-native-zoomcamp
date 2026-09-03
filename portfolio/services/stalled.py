"""Stalled detection (#14): weeks since the last commit, per repo.

The headline number of the whole tool - the one that says out loud which
projects were quietly abandoned. Pure stdlib + dataclasses, no Django import,
no LLM, no network - see the services layering and determinism rules in
AGENTS.md. Reading stored `RepoWeek` history to find the last commit week is
a separate, Django-aware step in `portfolio/services/stalled_lookup.py`, so
the arithmetic here stays testable from plain fixtures without a database -
same split as `momentum.py` (compute) / `repoweek.py` (persist).

Week arithmetic reuses `week.py`'s `week_window` (#11) rather than
reimplementing ISO calendar maths here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import tzinfo as TzInfo

from .week import week_window

STALLED_THRESHOLD_WEEKS = 4  # SPEC.md's own example: "no commit for 4+ weeks"

# Mirrors `portfolio.models.Project.Status` values. Kept as plain strings
# rather than importing the Django model, so this module stays Django-free.
_SHIPPED = "shipped"
_DROPPED = "dropped"
_PAUSED = "paused"


@dataclass
class StalledStatus:
    """What the report shows for one repo: the number, and the flag."""

    weeks_since_last_commit: int | None
    stalled: bool


def weeks_since_last_commit(
    last_commit_week: str | None, reported_week: str, tz: TzInfo
) -> int | None:
    """Whole ISO weeks between `last_commit_week` and `reported_week`, or `None`.

    `last_commit_week` is the most recent ISO week label (`"2026-W36"`) with at
    least one commit, or `None` for a repo never committed to - which reports
    `None` here too, not `0` and not another int (see the issue's own AC).

    A commit in the reported week itself (`last_commit_week == reported_week`)
    is `0`. Both labels are resolved to their Monday via `week_window` (#11)
    and compared against **that Monday**, not "today" - re-running an old
    `reported_week` gives the same answer it would have given at the time.
    """
    if last_commit_week is None:
        return None
    last_monday, _ = week_window(last_commit_week, tz=tz)
    reported_monday, _ = week_window(reported_week, tz=tz)
    delta_days = (reported_monday.date() - last_monday.date()).days
    return delta_days // 7


def is_stalled(weeks: int | None, threshold: int = STALLED_THRESHOLD_WEEKS) -> bool:
    """`weeks` is `None` (never committed) or at or beyond `threshold`."""
    return weeks is None or weeks >= threshold


def stalled_status(
    *,
    last_commit_week: str | None,
    reported_week: str,
    status: str,
    paused_until: date | None,
    reference_date: date,
    tz: TzInfo,
    threshold: int = STALLED_THRESHOLD_WEEKS,
) -> StalledStatus:
    """Combine the weeks-since-last-commit number with a project's lifecycle status.

    `status` and `paused_until` mirror the corresponding `Project` fields
    (#10) - passed as plain values, not the model, to keep this function
    Django-free. `reference_date` is the date the pause is checked against;
    the caller passes the **end of the reported week**, not today (same
    determinism rule as the weeks-since number above), so
    `Project.paused_until` reads the same whether the report runs now or is
    re-run later for an old week.

    `shipped` and `dropped` projects are never flagged - they left the report
    on purpose. A `paused` project is not flagged while its pause is in force
    (`paused_until` unset, or `reference_date` at or before it) and is
    flagged again once `reference_date` passes `paused_until` - matching
    `Project.in_weekly_report`'s own rule, just measured against
    `reference_date` instead of "today".
    """
    weeks = weeks_since_last_commit(last_commit_week, reported_week, tz)

    if status in (_SHIPPED, _DROPPED):
        return StalledStatus(weeks, False)

    if status == _PAUSED:
        pause_in_force = paused_until is None or reference_date <= paused_until
        if pause_in_force:
            return StalledStatus(weeks, False)

    return StalledStatus(weeks, is_stalled(weeks, threshold))
