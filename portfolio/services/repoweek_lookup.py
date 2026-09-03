"""Django-aware companion to `momentum_delta.py` (#21, D19 in docs/decisions.md).

Reads the previous ISO week's stored `RepoWeek` row (#13) for a repo -
the only Django-touching piece of #21, kept out of `momentum_delta.py` so
the delta-text formatting stays a pure function testable from plain
fixtures without a database. Same split `stalled_lookup.py` already
established for #14.

Makes no GitHub request and never re-fetches to fill a gap: a missing
previous-week row is reported as `None` ("first week tracked"), not
recomputed.
"""

from __future__ import annotations

from portfolio.models import RepoWeek

from .momentum_delta import PreviousMomentum
from .week import previous_week_label


def previous_momentum_for_repo(repo: str, week: str) -> PreviousMomentum | None:
    """`PreviousMomentum` for `repo` at the calendar-previous ISO week before
    `week` (`previous_week_label`, correct across a year boundary), or
    `None` when no `RepoWeek` row is stored for that week - "first week
    tracked", per #21's own constraint against re-fetching from GitHub.

    A previous row with `partial=True` (#13/D2's diffstat cap) is returned
    the same as any other row - its lines-added/lines-removed/files-touched
    numbers are not suppressed or hidden (#21's AC); only the *current*
    week's own `partial` flag drives the existing "diffstat capped" caveat
    elsewhere in the report.
    """
    prior_week = previous_week_label(week)
    row = RepoWeek.objects.filter(repo=repo, week=prior_week).first()
    if row is None:
        return None
    return PreviousMomentum(
        commits=row.commits,
        active_days=row.active_days,
        lines_added=row.lines_added,
        lines_removed=row.lines_removed,
        files_touched=row.files_touched,
    )
