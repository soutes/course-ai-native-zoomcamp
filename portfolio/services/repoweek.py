"""Persist `RepoWeekStats` (#13's pure computation) into a `RepoWeek` row.

The only Django-aware piece of #13 - deliberately kept out of `momentum.py` so
the counting logic there stays importable and testable without a database.
This module does no counting of its own; it only writes what `compute_repo_week`
already decided.
"""

from __future__ import annotations

from datetime import datetime

from portfolio.models import RepoWeek

from .momentum import RepoWeekStats


def persist_repo_week(
    repo: str,
    week: str,
    window: tuple[datetime, datetime],
    stats: RepoWeekStats,
) -> RepoWeek:
    """Write `stats` to the `RepoWeek` row for (`repo`, `week`).

    Unique on (repo, week) - re-running the same week updates the existing row
    (matching `commits`/`active_days`/etc. get overwritten, `computed_at`
    advances) rather than creating a duplicate.
    """
    window_start, window_end = window
    row, _created = RepoWeek.objects.update_or_create(
        repo=repo,
        week=week,
        defaults={
            "window_start": window_start,
            "window_end": window_end,
            "commits": stats.commits,
            "active_days": stats.active_days,
            "lines_added": stats.lines_added,
            "lines_removed": stats.lines_removed,
            "files_touched": stats.files_touched,
            "partial": stats.partial,
        },
    )
    return row
