"""Grouping/shaping for the tracked-project list (#43, decision D12).

No Django import here, per AGENTS.md's layering rule - rules, not delivery. Functions
below take plain rows (a `Project` instance or a dict with the same field names both
work, same duck-typing `render.abandoned_count` already relies on) and shape them for
display. `portfolio/views.py`'s `projects` view is thin wiring over this module. When
#34 (the `projects` terminal command) lands, it becomes this module's second caller
instead of inventing its own grouping logic - the same pattern #36/#23 set for
`abandoned_count` (D4).
"""

from __future__ import annotations

STATUS_ORDER = ["active", "paused", "shipped", "dropped"]

STATUS_LABELS = {
    "active": "Active",
    "paused": "Paused on purpose",
    "shipped": "Shipped",
    "dropped": "Dropped",
}


def group_projects(projects) -> dict:
    """Group project rows by status into the four fixed sections.

    Returns ``{"groups": {status: [rows, ...]}, "counts": {status: int}, "total": int}``.
    All four status keys are always present in `groups`/`counts`, even when empty, so a
    template can iterate `STATUS_ORDER` without guarding for a missing key. `total` is
    the sum of the four counts, which is always `len(projects)` for well-formed rows -
    a row whose `status` is none of the four known values is dropped from every group
    and does not count toward `total`, since `Project.status` is a `TextChoices` field
    and should never hold anything else.
    """
    groups: dict[str, list] = {status: [] for status in STATUS_ORDER}
    for project in projects:
        bucket = groups.get(project.status)
        if bucket is not None:
            bucket.append(project)
    counts = {status: len(rows) for status, rows in groups.items()}
    return {"groups": groups, "counts": counts, "total": sum(counts.values())}


def triage_history(runs) -> list[dict]:
    """Shape triage runs for the public page (decision D13).

    `runs` is an iterable of objects/dicts carrying `ran_at` and `hidden_count` (the
    count of that run's decisions that made a repo private) - the caller (the view)
    computes `hidden_count` from `TriageDecision` so this module never has to import
    the Django ORM to aggregate it. Deliberately does **not** touch repo names or
    `TriageDecision.reason` - D13 keeps both admin-only. Order is preserved as given;
    the view relies on `TriageRun.Meta.ordering = ["-ran_at"]` for newest-first.
    """
    history = []
    for run in runs:
        ran_at = run["ran_at"] if isinstance(run, dict) else run.ran_at
        hidden_count = run["hidden_count"] if isinstance(run, dict) else run.hidden_count
        history.append({"ran_at": ran_at, "hidden_count": hidden_count})
    return history
