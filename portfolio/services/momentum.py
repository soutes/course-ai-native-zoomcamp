"""Momentum stats: turn a week of commits into the six numbers `RepoWeek` stores.

Pure stdlib + dataclasses, no Django import, no LLM call, no network - see the
services layering and determinism rules in AGENTS.md. This module only counts;
persisting the result into `RepoWeek` is a separate, Django-aware step in
`portfolio/services/repoweek.py`, so the counting logic here stays testable
from plain fixtures without a database.

Diffstat fetching (network, cached) is injected as a callable rather than this
module calling `GitHub` itself - that keeps `compute_repo_week` a pure function
of its inputs, and lets tests fake the fetcher instead of the network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import tzinfo as TzInfo

from .types import Commit, CommitStat

DIFFSTAT_CAP = 80  # docs/decisions.md D2


@dataclass
class RepoWeekStats:
    """The six numbers a `RepoWeek` row stores, before persistence."""

    commits: int
    active_days: int
    lines_added: int
    lines_removed: int
    files_touched: int
    partial: bool


def compute_repo_week(
    commits: Iterable[Commit],
    diffstat: Callable[[Commit], CommitStat],
    tz: TzInfo,
    cap: int = DIFFSTAT_CAP,
) -> RepoWeekStats:
    """Reduce a week's commits (#12's `commits_in_window` output) to `RepoWeekStats`.

    ``commits`` may be empty - a tracked repo with no commits this week still
    produces a (zero-valued, non-partial) row; see the issue's "silent project"
    acceptance criterion.

    ``active_days`` counts distinct **local** calendar days with at least one
    commit - each commit's UTC-aware `authored_at` is converted to ``tz`` before
    taking its date, so ten commits on one local day is 1 active day, not 10.
    ``tz`` should be the same local zone the report's `week_window` used, so
    "local" means the same thing throughout a run.

    ``diffstat`` is called once per commit, in the order ``commits`` iterates,
    up to ``cap`` times (docs/decisions.md D2) - commits beyond the cap still
    count toward ``commits``/``active_days`` but contribute nothing to
    lines/files, and ``partial`` is set so the caller can flag the row as an
    undercount rather than silently wrong.
    """
    commits = list(commits)
    active_days = {c.authored_at.astimezone(tz).date() for c in commits}

    lines_added = 0
    lines_removed = 0
    files_touched = 0
    for commit in commits[:cap]:
        stat = diffstat(commit)
        lines_added += stat.additions
        lines_removed += stat.deletions
        files_touched += stat.files_changed

    return RepoWeekStats(
        commits=len(commits),
        active_days=len(active_days),
        lines_added=lines_added,
        lines_removed=lines_removed,
        files_touched=files_touched,
        partial=len(commits) > cap,
    )
