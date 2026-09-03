"""Yearly retrospective (#31, D30 in docs/decisions.md).

Shipped, dropped, and silent, side by side, built entirely from stored `Project`
and `RepoWeek` (#13) rows - no GitHub call, no LLM call, no new model. This is
the one shared function `manage.py year` and `/year/<year>/` both call so the
command and the page cannot drift apart (D30 point 1).

Django-aware, like `stalled_lookup.py`/`goal_stale_lookup.py` - the ORM query
shape (`Project`/`RepoWeek` lookups) belongs here, not duplicated in the
command and the view. Silent detection reuses `stalled.py`'s
`weeks_since_last_commit`/`is_stalled` verbatim (D30 point 3) - no new
threshold is invented for this issue.

Year membership is ISO week-year (`date.isocalendar()[0]`), matching
`RepoWeek.week`'s own `"YYYY-Www"` labels and `week.py`'s date arithmetic -
not calendar `.year` (D30 point 6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import tzinfo as TzInfo

from portfolio.models import Project, RepoWeek

from .stalled import is_stalled, weeks_since_last_commit
from .stalled_lookup import most_recent_commit_week
from .week import week_window

_YEAR_RE = re.compile(r"^\d{4}$")


@dataclass
class EndedRow:
    """One shipped or dropped project ending inside the requested year."""

    repo: str
    end_date: datetime


@dataclass
class SilentRow:
    """One currently report-eligible project stalled at the year's reference point.

    `weeks_silent` is `None` for a repo with no `RepoWeek` commit history at
    all - rendered as "no commit history," never a number (the issue's own
    AC, and #32's existing convention for the same case).
    """

    repo: str
    weeks_silent: int | None


@dataclass
class YearSummary:
    """The whole page/command's data: three groups, always in this order."""

    year: int
    shipped: list[EndedRow] = field(default_factory=list)
    dropped: list[EndedRow] = field(default_factory=list)
    silent: list[SilentRow] = field(default_factory=list)
    is_empty: bool = False

    @property
    def shipped_count(self) -> int:
        return len(self.shipped)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    @property
    def silent_count(self) -> int:
        return len(self.silent)


def parse_year(value: str) -> int:
    """Parse a 4-digit ISO week-year from user/URL input.

    Raises `ValueError` (naming the offending input) for anything else - a
    non-numeric string, a wrong number of digits, or leading/trailing
    whitespace. Callers turn this into a `CommandError` or `Http404`.
    """
    if not isinstance(value, str) or not _YEAR_RE.match(value):
        raise ValueError(f"invalid year: {value!r} (expected a 4-digit year, e.g. 2026)")
    return int(value)


def _reference_week(year: int, tz: TzInfo, today: date | None) -> str:
    """The ISO week label silent detection is measured against for `year`.

    The last ISO week inside `year` when `year` is fully in the past, or the
    current ISO week when `year` is the current (or a future) year - never a
    future week that has no data yet (D30 point 3).
    """
    resolved_today = today if today is not None else datetime.now(tz).date()
    current_iso_year, current_iso_week, _weekday = resolved_today.isocalendar()

    if year < current_iso_year:
        last_week_of_year = date(year, 12, 28).isocalendar()[1]  # always in the last ISO week
        return f"{year}-W{last_week_of_year:02d}"
    return f"{current_iso_year}-W{current_iso_week:02d}"


def _is_report_eligible(status: str, paused_until: date | None, reference_date: date) -> bool:
    """Mirrors `Project.in_weekly_report`, but against `reference_date` instead of "today".

    Shipped and dropped projects are never eligible. A paused project is
    eligible again once `reference_date` passes `paused_until`; a paused
    project with no `paused_until` set never becomes eligible.
    """
    if status in (Project.Status.SHIPPED, Project.Status.DROPPED):
        return False
    if status == Project.Status.PAUSED and paused_until:
        return reference_date > paused_until
    return status != Project.Status.PAUSED


def _endings(status: str, year: int, tz: TzInfo) -> list[EndedRow]:
    rows = [
        EndedRow(repo=project.repo, end_date=project.status_changed_at)
        for project in Project.objects.filter(status=status, status_changed_at__isnull=False)
        if project.status_changed_at.astimezone(tz).date().isocalendar()[0] == year
    ]
    rows.sort(key=lambda row: row.repo)
    return rows


def _silent_rows(year: int, tz: TzInfo, today: date | None) -> tuple[list[SilentRow], str]:
    reference_week = _reference_week(year, tz, today)
    _window_start, window_end = week_window(reference_week, tz=tz)
    reference_date = window_end.date()

    rows = []
    for project in Project.objects.all():
        if not _is_report_eligible(project.status, project.paused_until, reference_date):
            continue
        last_commit_week = most_recent_commit_week(project.repo, reference_week)
        weeks = weeks_since_last_commit(last_commit_week, reference_week, tz)
        if is_stalled(weeks):
            rows.append(SilentRow(repo=project.repo, weeks_silent=weeks))

    rows.sort(key=lambda row: row.repo)
    return rows, reference_week


def year_summary(year: int, tz: TzInfo, *, today: date | None = None) -> YearSummary:
    """Build the whole yearly retrospective for `year` from stored data only.

    `today` overrides "now" for the reference-week calculation (D30 point 3)
    - tests pass an explicit date so the current/future-year branch is
    deterministic without depending on the real clock. Production callers
    (the command, the view) leave it unset.
    """
    shipped = _endings(Project.Status.SHIPPED, year, tz)
    dropped = _endings(Project.Status.DROPPED, year, tz)
    silent, _reference_week = _silent_rows(year, tz, today)

    week_prefix = f"{year}-W"
    has_repo_weeks = RepoWeek.objects.filter(week__startswith=week_prefix).exists()
    is_empty = not has_repo_weeks and not shipped and not dropped

    return YearSummary(
        year=year,
        shipped=shipped,
        dropped=dropped,
        silent=silent,
        is_empty=is_empty,
    )
