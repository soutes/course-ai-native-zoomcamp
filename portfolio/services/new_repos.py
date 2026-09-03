"""New-repos-this-week detection (#33): a repo created during the reported
week gets its own callout, so a portfolio that starts a lot and finishes
little sees the starts, not only the finishes.

Pure stdlib + dataclasses, no Django import, no LLM, no network - see the
services layering and determinism rules in AGENTS.md. Adds no GitHub request:
``created_at`` is already carried by the ``Repo`` dataclass (#3), and each
repo's commit count for the week is looked up from data the caller already
fetched (e.g. #12's ``commits_in_window``, sized per repo) rather than
refetched here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from .types import NewRepo, Repo


def new_repos_this_week(
    repos: Iterable[Repo],
    window: tuple[datetime, datetime],
    commit_counts: Mapping[str, int] | None = None,
) -> list[NewRepo]:
    """Repos whose ``created_at`` falls inside ``window``, compared in local time.

    ``window`` is the ``(start, end)`` pair `week.week_window` (#11) returns -
    Monday 00:00:00 to Sunday 23:59:59.999999, local time, both ends
    inclusive. ``created_at`` is UTC-aware (see `github._parse_dt`); comparing
    aware datetimes compares the actual instant regardless of which zone each
    side carries, so a repo created late Sunday local time is correctly kept
    in this week and never spills into the next one.

    ``commit_counts`` maps a repo's ``full_name`` to its commit count for the
    week - already computed by the caller, not fetched here. A repo missing
    from the mapping counts as ``0``, not an error: an untracked repo (#33's
    own AC - "a new repo that is not a tracked project is still counted") may
    have no commit data gathered for it at all, and that must not exclude it
    from this list.

    Every ``Repo`` passed in is considered, tracked or not - ``Repo`` alone
    carries no tracked/untracked distinction, and deciding what "tracked"
    means is a caller concern, not this function's.

    Results are ordered by creation date, earliest first. Returns an empty
    list, never ``None``, when no repo was created this week - rendering "no
    callout at all" for that case is the caller's job (#33's own AC), not
    this function's.
    """
    if commit_counts is None:
        commit_counts = {}

    start, end = window
    created_this_week = sorted(
        (repo for repo in repos if start <= repo.created_at <= end),
        key=lambda repo: repo.created_at,
    )

    return [
        NewRepo(
            name=repo.name,
            created_at=repo.created_at,
            commits=commit_counts.get(repo.full_name, 0),
        )
        for repo in created_this_week
    ]
