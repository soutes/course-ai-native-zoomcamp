"""`manage.py seed_demo` - fictional portfolio data for offline review.

Populates `Project`, `TriageRun` and `TriageDecision` with a realistic but
entirely made-up portfolio, so `/` and the Django admin can be reviewed by
hand with no `GITHUB_TOKEN` and no network call. See D7 in
`docs/decisions.md`: only these three models exist today, so that is all
this command seeds - no `RepoWeek`, no `WeeklyReport` (follow-up: #40).

The `TriageRun`/`TriageDecision` rows this command creates are fabricated
demo history for the dashboard's "Triage history" section - they are not a
record of any real write to a hosting account. No network call is made, ever.

Idempotent: re-running against the same database updates the same rows
(matched on `Project.repo`, the unique field) instead of raising, and
clears + recreates its own demo `TriageRun`/`TriageDecision` rows rather
than piling up duplicates.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from portfolio.models import Project, TriageDecision, TriageRun

# Fictional projects only - no real people, no real (public or private) repo
# names, no secrets. `owner` is a made-up demo account.
_OWNER = "demo-owner"

_NOW = timezone.now
_TODAY = lambda: timezone.now().date()  # noqa: E731


def _weeks_ago(weeks: int):
    return _NOW() - timedelta(weeks=weeks)


def _days(delta: int):
    return _TODAY() + timedelta(days=delta)


def _projects() -> list[dict]:
    return [
        # Active, reads as fresh - started this week.
        {
            "repo": f"{_OWNER}/spectra-notes",
            "goal": "Ship a markdown notes app with full-text search.",
            "status": Project.Status.ACTIVE,
            "status_reason": "",
            "status_changed_at": _weeks_ago(0),
            "paused_until": None,
            "goal_set_at": _weeks_ago(0),
        },
        # Active, reads as stalled - no meaningful movement in 6 weeks.
        {
            "repo": f"{_OWNER}/lumen-api-gateway",
            "goal": "Front the internal services with one rate-limited gateway.",
            "status": Project.Status.ACTIVE,
            "status_reason": "",
            "status_changed_at": _weeks_ago(6),
            "paused_until": None,
            "goal_set_at": _weeks_ago(9),
        },
        # Active, reads as stalled - even older.
        {
            "repo": f"{_OWNER}/tidepool-metrics",
            "goal": "Dashboard for tide-station sensor uptime.",
            "status": Project.Status.ACTIVE,
            "status_reason": "",
            "status_changed_at": _weeks_ago(8),
            "paused_until": None,
            "goal_set_at": _weeks_ago(12),
        },
        # Paused, resumes in the future.
        {
            "repo": f"{_OWNER}/orchard-budget-tracker",
            "goal": "Envelope-budgeting CLI for a household of four.",
            "status": Project.Status.PAUSED,
            "status_reason": "Waiting on a bank export format decision.",
            "status_changed_at": _weeks_ago(2),
            "paused_until": _days(21),
            "goal_set_at": _weeks_ago(10),
        },
        # Paused, no resume date set - exercises the "unset" branch.
        {
            "repo": f"{_OWNER}/paperlantern-blog",
            "goal": "Static-site blog generator with themeable templates.",
            "status": Project.Status.PAUSED,
            "status_reason": "Deprioritized after the day job got busy.",
            "status_changed_at": _weeks_ago(5),
            "paused_until": None,
            "goal_set_at": _weeks_ago(20),
        },
        # Paused, resume date already in the past - exercises the "past" branch.
        {
            "repo": f"{_OWNER}/glasshouse-inventory",
            "goal": "Barcode-driven inventory tracker for a small greenhouse.",
            "status": Project.Status.PAUSED,
            "status_reason": "Meant to resume in spring; still on hold.",
            "status_changed_at": _weeks_ago(15),
            "paused_until": _days(-30),
            "goal_set_at": _weeks_ago(30),
        },
        # Shipped.
        {
            "repo": f"{_OWNER}/harborlight-timesheet",
            "goal": "Weekly timesheet exporter for freelance invoicing.",
            "status": Project.Status.SHIPPED,
            "status_reason": "v1 shipped and in daily use, no more feature work planned.",
            "status_changed_at": _weeks_ago(4),
            "paused_until": None,
            "goal_set_at": _weeks_ago(16),
        },
        # Dropped.
        {
            "repo": f"{_OWNER}/copperline-chat-bot",
            "goal": "Slack bot that summarizes standup threads.",
            "status": Project.Status.DROPPED,
            "status_reason": "Slack's own AI summaries made this redundant.",
            "status_changed_at": _weeks_ago(7),
            "paused_until": None,
            "goal_set_at": _weeks_ago(18),
        },
    ]


class Command(BaseCommand):
    help = (
        "Populate a fresh database with a fictional demo portfolio "
        "(Project, TriageRun, TriageDecision) - no network, no GITHUB_TOKEN needed."
    )

    def handle(self, *args, **options) -> None:
        created_count = 0
        updated_count = 0
        for data in _projects():
            repo = data.pop("repo")
            _project, created = Project.objects.update_or_create(repo=repo, defaults=data)
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            f"Projects: {created_count} created, {updated_count} updated "
            f"({created_count + updated_count} fictional demo projects total)."
        )

        # Demo triage history is entirely fabricated - not a record of any
        # real write to a hosting account. Clear any previously-seeded demo
        # runs first so re-running this command doesn't pile up duplicate history.
        stale_runs = TriageRun.objects.filter(decisions__reason__startswith="[demo] ").distinct()
        deleted_run_count = stale_runs.count()
        if deleted_run_count:
            stale_runs.delete()
            self.stdout.write(
                f"Cleared {deleted_run_count} previously-seeded demo TriageRun row(s)."
            )

        run = TriageRun.objects.create()
        TriageDecision.objects.create(
            run=run,
            repo=f"{_OWNER}/copperline-chat-bot",
            action=TriageDecision.Action.HIDE,
            reason="[demo] fabricated history: dropped project, made private for tidiness.",
        )
        TriageDecision.objects.create(
            run=run,
            repo=f"{_OWNER}/harborlight-timesheet",
            action=TriageDecision.Action.HIDE,
            reason="[demo] fabricated history: shipped project, archived from the public list.",
        )
        self.stdout.write(
            f"Triage history: created 1 fabricated TriageRun with "
            f"{run.decisions.count()} TriageDecision rows (demo data, not a real write out there)."
        )
