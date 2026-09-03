"""`manage.py projects` (#34) - list tracked projects grouped by status.

Thin wiring only: query `Project.objects.all()` (optionally filtered by `--status`),
hand the rows to `portfolio.services.projects.group_projects()` for the grouping and
counts (#43, decision D12), and print. Read-only - no `.save()`/`.update()`, no
GitHub call, no LLM call. This is the CLI's second caller of `group_projects()`,
matching `/projects/` (`portfolio/views.py`) rather than re-deriving the grouping.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from rich.console import Console
from rich.markup import escape

from portfolio.models import Project
from portfolio.services.projects import STATUS_LABELS, STATUS_ORDER, group_projects

console = Console()

PLACEHOLDER = "-"
NO_GOAL = "(no goal set)"


class Command(BaseCommand):
    help = "List tracked projects grouped by status (Active / Paused / Shipped / Dropped)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--status",
            default=None,
            help="Limit to one status group: active, paused, shipped, or dropped.",
        )

    def handle(self, *args, **options) -> None:
        status = options["status"]
        if status is not None and status not in STATUS_ORDER:
            raise CommandError(f"--status must be one of {', '.join(STATUS_ORDER)}, got {status!r}")

        shaped = group_projects(Project.objects.all())

        if status is not None:
            statuses = [status]
        else:
            statuses = STATUS_ORDER

        total_shown = sum(shaped["counts"][s] for s in statuses)
        if total_shown == 0:
            console.print(
                "[dim]No tracked projects"
                + (f" with status {escape(status)}" if status else "")
                + ". `manage.py projects` only lists what's already tracked - "
                "add projects at /admin/ (#10).[/dim]"
            )
            return

        for s in statuses:
            rows = shaped["groups"][s]
            count = shaped["counts"][s]
            console.print(f"\n[bold]{escape(STATUS_LABELS[s])}[/bold] ({count})")
            if not rows:
                console.print("  [dim](none)[/dim]")
                continue
            for project in rows:
                repo = escape(project.repo)
                goal = escape(project.goal) if project.goal else NO_GOAL
                changed = (
                    project.status_changed_at.date().isoformat()
                    if project.status_changed_at
                    else PLACEHOLDER
                )
                if s == "paused":
                    paused_until = (
                        project.paused_until.isoformat() if project.paused_until else PLACEHOLDER
                    )
                    console.print(
                        f"  {repo} - {goal} - changed {changed} - paused until {paused_until}"
                    )
                elif s in ("shipped", "dropped"):
                    console.print(f"  {repo} - {goal} - ended {changed}")
                else:
                    console.print(f"  {repo} - {goal} - changed {changed}")
