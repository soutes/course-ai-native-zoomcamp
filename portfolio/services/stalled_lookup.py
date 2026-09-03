"""Django-aware companion to `stalled.py` (#14).

Reads stored `RepoWeek` history (#13) for the most recent week with a commit,
instead of re-fetching GitHub - the issue's own constraint, since #13 already
covers the window. Kept out of `stalled.py` so the stalled-detection maths
stays a pure function, testable from plain fixtures without a database - the
same split `repoweek.py` keeps between persisting and `momentum.py`'s
counting.
"""

from __future__ import annotations

from datetime import tzinfo as TzInfo

from portfolio.models import Project, RepoWeek

from .stalled import STALLED_THRESHOLD_WEEKS, StalledStatus, stalled_status
from .week import week_window


def most_recent_commit_week(repo: str, upto_week: str) -> str | None:
    """The most recent ISO week label with `commits > 0` for `repo`, at or before `upto_week`.

    ISO week labels sort lexicographically in chronological order (`week.py`'s
    zero-padded `"YYYY-Www"` format), so a plain string filter/order is exact
    - no date parsing needed here. `upto_week` is inclusive, so a commit
    stored for the reported week itself counts.

    Returns `None` when `repo` has no stored `RepoWeek` row with commits in
    that range - the caller treats that as "never committed to".
    """
    row = (
        RepoWeek.objects.filter(repo=repo, week__lte=upto_week, commits__gt=0)
        .order_by("-week")
        .first()
    )
    return row.week if row else None


def stalled_status_for_project(
    project: Project,
    reported_week: str,
    tz: TzInfo,
    threshold: int = STALLED_THRESHOLD_WEEKS,
) -> StalledStatus:
    """`stalled_status` (#14) for `project`, sourcing the last commit week from `RepoWeek`.

    `reference_date` for the pause check is the reported week's own Sunday
    (its window end), not today - so re-running an old week's report gives
    the same answer it would have given then.
    """
    last_commit_week = most_recent_commit_week(project.repo, reported_week)
    _window_start, window_end = week_window(reported_week, tz=tz)

    return stalled_status(
        last_commit_week=last_commit_week,
        reported_week=reported_week,
        status=project.status,
        paused_until=project.paused_until,
        reference_date=window_end.date(),
        tz=tz,
        threshold=threshold,
    )
