"""Lifecycle transitions for a tracked `Project` (#19).

One function, reused by both the `ack` management command and the Django admin
actions, so the two surfaces cannot drift on what "shipped"/"paused"/"dropped"
means to the model. No GitHub, no LLM - it only ever sets fields on the
`Project` row already in the database (D17: re-acking overwrites, it never
keeps a transition history).
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from portfolio.models import Project


def apply_transition(
    project: Project,
    status: str,
    *,
    reason: str = "",
    paused_until: date | None = None,
) -> None:
    """Set `status`, `status_reason`, `status_changed_at` (server time) on `project`.

    `paused_until` is only written when given (the `--pause`/mark-paused transition
    supplies it); shipped and dropped transitions leave whatever `paused_until` is
    already on the row alone - `in_weekly_report` checks `status` first, so a stale
    `paused_until` on a shipped or dropped project has no effect.
    """
    project.status = status
    project.status_reason = reason
    project.status_changed_at = timezone.now()
    if paused_until is not None:
        project.paused_until = paused_until
    project.save(update_fields=["status", "status_reason", "status_changed_at", "paused_until"])
