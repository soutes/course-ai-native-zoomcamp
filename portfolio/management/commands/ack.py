"""`manage.py ack` (#19) - record a lifecycle transition for a tracked project.

Thin wiring only: parse exactly one of --shipped/--pause/--drop plus an optional
--reason, look the project up, hand the fields to
`portfolio.services.lifecycle.apply_transition`, and print. The "is this project
in this week's report?" rule already lives on `Project.in_weekly_report` - this
command never touches it, and never makes a GitHub call.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from rich.console import Console
from rich.markup import escape

from portfolio.models import Project
from portfolio.services.lifecycle import apply_transition

console = Console()


class Command(BaseCommand):
    help = "Record a lifecycle transition (shipped / paused / dropped) for a tracked project."

    def add_arguments(self, parser) -> None:
        parser.add_argument("repo", help="owner/name, matching an existing Project.repo.")
        parser.add_argument("--shipped", action="store_true", help="Mark the project shipped.")
        parser.add_argument(
            "--pause",
            metavar="YYYY-MM-DD",
            default=None,
            help="Pause the project until this ISO date.",
        )
        parser.add_argument("--drop", action="store_true", help="Drop the project for good.")
        parser.add_argument(
            "--reason", default="", help="Optional free text, stored verbatim on the project."
        )

    def handle(self, *args, **options) -> None:
        repo = options["repo"]
        reason = options["reason"] or ""

        chosen = [
            name
            for name, present in (
                ("--shipped", options["shipped"]),
                ("--pause", options["pause"] is not None),
                ("--drop", options["drop"]),
            )
            if present
        ]
        if not chosen:
            raise CommandError("exactly one of --shipped, --pause, --drop is required, got none")
        if len(chosen) > 1:
            raise CommandError(
                f"exactly one of --shipped, --pause, --drop is required, got: {', '.join(chosen)}"
            )

        paused_until = None
        if options["pause"] is not None:
            try:
                paused_until = date.fromisoformat(options["pause"])
            except ValueError:
                raise CommandError(
                    f"--pause expects an ISO date (YYYY-MM-DD), got {options['pause']!r}"
                ) from None

        try:
            project = Project.objects.get(repo=repo)
        except Project.DoesNotExist:
            raise CommandError(f"no such project: {repo}") from None

        if options["shipped"]:
            status = Project.Status.SHIPPED
        elif options["drop"]:
            status = Project.Status.DROPPED
        else:
            status = Project.Status.PAUSED

        apply_transition(project, status, reason=reason, paused_until=paused_until)

        suffix = f" ({escape(reason)})" if reason else ""
        console.print(f"[green]{escape(repo)}[/green] -> {escape(status)}{suffix}")
