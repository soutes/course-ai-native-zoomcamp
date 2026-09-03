"""Persistence.

These replace the hand-edited config and the `state.toml` the CLI used to write:
`Project` is intent I state once, `TriageRun`/`TriageDecision` is history the tool
records. Keeping them apart means the tool never rewrites my own words.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class Project(models.Model):
    """A repo I have declared a goal for and want judged every week."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused on purpose"
        SHIPPED = "shipped", "Shipped"
        DROPPED = "dropped", "Dropped"

    repo = models.CharField(max_length=140, unique=True, help_text="owner/name on GitHub")
    goal = models.TextField(
        blank=True, help_text="One sentence. What finishing this project looks like."
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    status_reason = models.CharField(max_length=280, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    paused_until = models.DateField(
        null=True, blank=True, help_text="After this date a paused project starts nagging again."
    )
    goal_set_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["repo"]

    def __str__(self) -> str:
        return self.repo

    @property
    def in_weekly_report(self) -> bool:
        """Shipped and dropped work leaves the report. Paused work is only silenced."""
        if self.status in {self.Status.SHIPPED, self.Status.DROPPED}:
            return False
        if self.status == self.Status.PAUSED and self.paused_until:
            return timezone.now().date() > self.paused_until
        return self.status != self.Status.PAUSED


class RepoWeek(models.Model):
    """One tracked repo's momentum for one ISO week (#13).

    The six numbers the retro argues from, computed deterministically by
    `portfolio/services/momentum.py` and written here so later weeks can
    compare against a stored row instead of recomputing history. Unique on
    (repo, week) - re-running the same week updates this row, never a
    duplicate.
    """

    repo = models.CharField(max_length=140, help_text="owner/name on GitHub")
    week = models.CharField(max_length=8, help_text='ISO week label, e.g. "2026-W36"')
    window_start = models.DateTimeField(help_text="Monday 00:00:00, local time")
    window_end = models.DateTimeField(help_text="Sunday 23:59:59.999999, local time")

    commits = models.PositiveIntegerField(default=0)
    active_days = models.PositiveSmallIntegerField(default=0)
    lines_added = models.PositiveIntegerField(default=0)
    lines_removed = models.PositiveIntegerField(default=0)
    files_touched = models.PositiveIntegerField(default=0)
    partial = models.BooleanField(
        default=False,
        help_text="Diffstat cap (D2) exceeded - lines/files columns are an undercount.",
    )

    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["repo", "week"], name="unique_repo_week"),
        ]
        ordering = ["repo", "week"]

    def __str__(self) -> str:
        return f"{self.repo} {self.week}"


class TriageRun(models.Model):
    """One applied `triage --apply`. History, never overwritten."""

    ran_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ran_at"]

    def __str__(self) -> str:
        return f"triage {self.ran_at:%Y-%m-%d %H:%M} ({self.decisions.count()} repos)"


class TriageDecision(models.Model):
    """What was done to one repo, and why."""

    class Action(models.TextChoices):
        HIDE = "hide", "Made private"

    run = models.ForeignKey(TriageRun, on_delete=models.CASCADE, related_name="decisions")
    repo = models.CharField(max_length=140)
    action = models.CharField(max_length=10, choices=Action.choices)
    reason = models.CharField(max_length=280, blank=True)

    class Meta:
        ordering = ["repo"]

    def __str__(self) -> str:
        return f"{self.repo}: {self.get_action_display()}"
