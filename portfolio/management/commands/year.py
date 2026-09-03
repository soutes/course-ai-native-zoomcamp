"""`manage.py year <year>` - the yearly retrospective (#31).

Thin wiring over `portfolio.services.year.year_summary` (D30 point 1) - reads
only stored `Project`/`RepoWeek` rows, no GitHub call, no LLM call. The web
view (`portfolio/views.py`'s `year`) calls the exact same function so the two
surfaces cannot drift apart.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from rich.console import Console
from rich.table import Table

from portfolio.services.year import parse_year, year_summary

console = Console()


class Command(BaseCommand):
    help = "Print the yearly retrospective: shipped, dropped, and silent projects."

    def add_arguments(self, parser) -> None:
        parser.add_argument("year", help="4-digit ISO week-year, e.g. 2026.")

    def handle(self, *args, **options) -> None:
        try:
            year = parse_year(options["year"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        tz = ZoneInfo(settings.TIME_ZONE)
        summary = year_summary(year, tz)

        if summary.is_empty:
            console.print(
                f"[dim]Nothing recorded for {year}: no stored weekly history and no project "
                "ended in this ISO week-year.[/dim]"
            )
            return

        console.print(f"[bold]{year}[/bold]")
        self._print_ended_group("Shipped", summary.shipped)
        self._print_ended_group("Dropped", summary.dropped)
        self._print_silent_group(summary.silent)

    def _print_ended_group(self, label: str, rows) -> None:
        table = Table(title=f"{label} ({len(rows)})")
        table.add_column("Repo")
        table.add_column("Ended")
        for row in rows:
            table.add_row(row.repo, row.end_date.date().isoformat())
        console.print(table)

    def _print_silent_group(self, rows) -> None:
        table = Table(title=f"Silent ({len(rows)})")
        table.add_column("Repo")
        table.add_column("Weeks silent")
        for row in rows:
            weeks = "no commit history" if row.weeks_silent is None else str(row.weeks_silent)
            table.add_row(row.repo, weeks)
        console.print(table)
