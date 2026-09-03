"""Django-aware companion to `goal_stale.py` (#30).

Sums stored `RepoWeek` history (#13) for the window from `Project.goal_set_at`
(#10) through the reported week, instead of re-fetching GitHub - the same
constraint `stalled_lookup.py` (#14) already follows, since #13 already
covers the window. Kept out of `goal_stale.py` so the staleness maths stays a
pure function, testable from plain fixtures without a database - the same
split `stalled.py`/`stalled_lookup.py` established.
"""

from __future__ import annotations

from datetime import datetime
from datetime import tzinfo as TzInfo

from django.db.models import Sum

from portfolio.models import Project, RepoWeek

from .goal_stale import STALE_GOAL_THRESHOLD_WEEKS, StaleGoalStatus, stale_goal_status
from .week import week_window


def commits_since_goal_set(repo: str, goal_set_at: datetime, reported_week: str, tz: TzInfo) -> int:
    """Sum of `RepoWeek.commits` for `repo`, from `goal_set_at`'s own ISO week
    through `reported_week`, inclusive.

    ISO week labels sort lexicographically in chronological order (`week.py`'s
    zero-padded `"YYYY-Www"` format), same as `stalled_lookup.py`'s
    `most_recent_commit_week` - so a plain string range filter is exact, no
    date parsing needed on the stored rows. `goal_set_at` is converted to
    `tz` before its ISO week is read off, matching `weeks_since_goal_set`'s
    own conversion.
    """
    goal_local = goal_set_at.astimezone(tz) if goal_set_at.tzinfo else goal_set_at
    iso_year, iso_week, _iso_weekday = goal_local.date().isocalendar()
    goal_week = f"{iso_year}-W{iso_week:02d}"

    total = RepoWeek.objects.filter(
        repo=repo, week__gte=goal_week, week__lte=reported_week
    ).aggregate(total=Sum("commits"))["total"]
    return total or 0


def stale_goal_status_for_project(
    project: Project,
    reported_week: str,
    tz: TzInfo,
    threshold: int = STALE_GOAL_THRESHOLD_WEEKS,
) -> StaleGoalStatus:
    """`stale_goal_status` (#30) for `project`, sourcing the commit-window sum
    from `RepoWeek`.

    `reference_date` for the pause check is the reported week's own Sunday
    (its window end), not today - matching `stalled_status_for_project`'s own
    rule, so re-running an old week's report gives the same answer it would
    have given then. Skips the `RepoWeek` query entirely when there is no
    goal to measure - `is_goal_stale` would return `False` either way, but
    there is nothing to sum for.
    """
    if not project.goal or project.goal_set_at is None:
        return StaleGoalStatus(0, False)

    commits = commits_since_goal_set(project.repo, project.goal_set_at, reported_week, tz)
    _window_start, window_end = week_window(reported_week, tz=tz)

    return stale_goal_status(
        goal=project.goal,
        goal_set_at=project.goal_set_at,
        reported_week=reported_week,
        commits_in_window=commits,
        status=project.status,
        paused_until=project.paused_until,
        reference_date=window_end.date(),
        tz=tz,
        threshold=threshold,
    )
