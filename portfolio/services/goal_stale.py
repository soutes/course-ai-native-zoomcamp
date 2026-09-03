"""Stale goal detection (#30): a goal that has not changed in 8+ weeks, on a
repo that shipped nothing in that window, is flagged as fiction (D29).

Pure stdlib + dataclasses, no Django import, no LLM, no network - same split
as `stalled.py` (#14): the arithmetic and lifecycle rules live here, testable
from plain fixtures, while reading `Project.goal_set_at` (#10) and summing
stored `RepoWeek` history (#13) for the window is a separate, Django-aware
step in `portfolio/services/goal_stale_lookup.py`.

Week arithmetic reuses `week.py`'s `week_window` (#11) rather than
reimplementing ISO calendar maths here - same as `stalled.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from datetime import tzinfo as TzInfo

from .week import week_window

STALE_GOAL_THRESHOLD_WEEKS = 8  # D29: issue #30's own "8+ weeks", named per stalled.py's precedent

# Mirrors `portfolio.models.Project.Status` values. Kept as plain strings
# rather than importing the Django model, so this module stays Django-free.
_SHIPPED = "shipped"
_DROPPED = "dropped"
_PAUSED = "paused"


@dataclass
class StaleGoalStatus:
    """What the report shows for one repo's goal: the number, and the flag."""

    weeks_since_goal_set: int
    stale: bool


def weeks_since_goal_set(goal_set_at: datetime, reported_week: str, tz: TzInfo) -> int:
    """Whole weeks between `goal_set_at` and the reported week's Monday.

    `goal_set_at` is `Project.goal_set_at` (#10) - the clock resets whenever the
    goal text is edited, so this is deliberately not a commit date or
    `created_at`. It is converted to `tz` before taking its date (Django
    stores it timezone-aware when `USE_TZ=True`, as this project's settings
    do), then compared against the reported week's own Monday - the same
    "measured against the reported week, not today" rule `weeks_since_last_commit`
    (`stalled.py`) follows, so re-running an old `reported_week` gives the
    same answer it would have given at the time.
    """
    reported_monday, _ = week_window(reported_week, tz=tz)
    goal_date = goal_set_at.astimezone(tz).date() if goal_set_at.tzinfo else goal_set_at.date()
    delta_days = (reported_monday.date() - goal_date).days
    return delta_days // 7


def is_goal_stale(
    *,
    goal: str,
    weeks_since_goal_set: int,
    commits_in_window: int,
    status: str,
    paused_until: date | None,
    reference_date: date,
    threshold: int = STALE_GOAL_THRESHOLD_WEEKS,
) -> bool:
    """Combine the goal-age number with the commit-window sum and a project's
    lifecycle status.

    No goal set (`goal == ""`) is never flagged - there is no fiction to
    detect. `shipped`/`dropped` projects are never flagged - they already
    left the report loop before this check ever sees them
    (`Project.in_weekly_report`), but the short-circuit is kept here too so
    the rule holds even if a caller passes one in directly. A `paused`
    project is not flagged while its pause is in force (`paused_until` unset,
    or `reference_date` at or before it) - matching `stalled_status`'s own
    paused rule, measured against `reference_date` (the reported week's end),
    not today. Below the threshold, no flag regardless of the commit count.
    At or above the threshold, the flag is exactly `commits_in_window == 0` -
    a single commit anywhere in the window, however old the goal text, clears
    it.
    """
    if not goal:
        return False

    if status in (_SHIPPED, _DROPPED):
        return False

    if status == _PAUSED:
        pause_in_force = paused_until is None or reference_date <= paused_until
        if pause_in_force:
            return False

    if weeks_since_goal_set < threshold:
        return False

    return commits_in_window == 0


def stale_goal_status(
    *,
    goal: str,
    goal_set_at: datetime | None,
    reported_week: str,
    commits_in_window: int,
    status: str,
    paused_until: date | None,
    reference_date: date,
    tz: TzInfo,
    threshold: int = STALE_GOAL_THRESHOLD_WEEKS,
) -> StaleGoalStatus:
    """Combine `weeks_since_goal_set` and `is_goal_stale` into one result.

    `goal_set_at` is `None` (unset, though the model defaults it) - reports
    0 weeks and never flagged, same "nothing to measure" treatment as a
    missing goal.
    """
    if goal_set_at is None:
        return StaleGoalStatus(0, False)

    weeks = weeks_since_goal_set(goal_set_at, reported_week, tz)
    stale = is_goal_stale(
        goal=goal,
        weeks_since_goal_set=weeks,
        commits_in_window=commits_in_window,
        status=status,
        paused_until=paused_until,
        reference_date=reference_date,
        threshold=threshold,
    )
    return StaleGoalStatus(weeks, stale)
