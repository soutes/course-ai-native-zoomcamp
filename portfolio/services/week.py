"""ISO week window helper.

Turns an ISO week label (or "now") into the ``[start, end]`` datetime window the
report queries GitHub with: Monday 00:00:00 to Sunday 23:59:59.999999, local time.

Pure stdlib (``datetime``/``zoneinfo`` only), no Django import - see the services
layering rule in AGENTS.md. The default timezone is the system's local zone
(``datetime.now().astimezone().tzinfo``); the management command instead passes
``zoneinfo.ZoneInfo(settings.TIME_ZONE)`` explicitly so this module stays
Django-free while still honouring local time (see docs/decisions.md).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from datetime import tzinfo as TzInfo

_LABEL_RE = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})$")

# Distinguishes "no argument given" (use today's week) from an explicit `None`
# passed as the label, which is a malformed input and must raise ValueError.
_UNSET = object()


def _local_tz() -> TzInfo:
    return datetime.now().astimezone().tzinfo


def _monday_from_label(week: str) -> date:
    if not isinstance(week, str) or not week:
        raise ValueError(f"invalid ISO week label: {week!r}")
    match = _LABEL_RE.match(week)
    if not match:
        raise ValueError(f"invalid ISO week label: {week!r}")
    year, week_num = int(match["year"]), int(match["week"])
    try:
        return date.fromisocalendar(year, week_num, 1)
    except ValueError as exc:
        raise ValueError(f"invalid ISO week label: {week!r} ({exc})") from exc


def week_window(week: str | None = _UNSET, tz: TzInfo | None = None) -> tuple[datetime, datetime]:
    """Return the ``(start, end)`` local-time window for an ISO week label.

    ``week`` looks like ``"2026-W36"``. Omit it (or leave the default) to get the
    window for today's ISO week. ``tz`` defaults to the system's local zone.

    ``start`` is Monday 00:00:00; ``end`` is Sunday 23:59:59.999999 - the GitHub
    ``until=`` parameter is inclusive, so the window's last instant matters.

    Raises ``ValueError`` naming the offending input for a malformed label
    (wrong shape, empty string, explicit ``None``) or a week number that does
    not exist in that ISO year (e.g. ``"2025-W53"`` - 2025 only has 52 weeks).
    """
    resolved_tz = tz if tz is not None else _local_tz()

    if week is _UNSET:
        today = datetime.now(resolved_tz).date()
        iso_year, iso_week, _iso_weekday = today.isocalendar()
        monday = date.fromisocalendar(iso_year, iso_week, 1)
    elif week is None:
        raise ValueError(f"invalid ISO week label: {week!r}")
    else:
        monday = _monday_from_label(week)

    sunday = monday + timedelta(days=6)
    start = datetime(monday.year, monday.month, monday.day, 0, 0, 0, 0, tzinfo=resolved_tz)
    end = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, 999999, tzinfo=resolved_tz)
    return start, end


def week_label(window: tuple[datetime, datetime]) -> str:
    """Render a ``(start, end)`` window back to its ISO week label, e.g. ``"2026-W36"``.

    Companion to `week_window`: ``week_label(week_window("2026-W36")) == "2026-W36"``.
    """
    start, _end = window
    iso_year, iso_week, _iso_weekday = start.date().isocalendar()
    return f"{iso_year}-W{iso_week:02d}"
