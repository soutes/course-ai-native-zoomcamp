"""`manage.py triage` - one-time portfolio curation.

The decision rules live in `portfolio.services.triage` and know nothing about Django.
This command is only the terminal surface: read settings, fetch, render, and - with
--apply - perform the single write this project ever makes.
"""

from __future__ import annotations

import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn

from portfolio.services import render
from portfolio.services.cache import Cache
from portfolio.services.github import GitHub, GitHubError
from portfolio.services.triage import build_plan
from portfolio.services.types import Repo

console = Console()


class Command(BaseCommand):
    help = "One-time portfolio curation: showcase / hide / delete."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Make the HIDE pile private. Never deletes, never archives.",
        )
        parser.add_argument("--refresh", action="store_true", help="Ignore the cache and re-fetch.")
        parser.add_argument(
            "--min-commits",
            type=int,
            default=None,
            help="Override the portfolio threshold for this run.",
        )
        parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    def handle(self, *args, **options) -> None:
        user = settings.GITHUB_USER
        token = settings.GITHUB_TOKEN
        if not user:
            raise CommandError("GITHUB_USER is not set. Copy .env.example to .env and fill it in.")
        if not token:
            raise CommandError(
                "GITHUB_TOKEN is not set.\n"
                "Create a Personal Access Token with the `repo` scope at\n"
                "  https://github.com/settings/tokens\n"
                "then put it in .env as GITHUB_TOKEN=..."
            )

        threshold = options["min_commits"]
        if threshold is None:
            threshold = settings.TRIAGE_MIN_COMMITS

        cache = Cache("triage")
        if options["refresh"]:
            console.print(f"[dim]cache cleared ({cache.clear()} entries)[/dim]")

        try:
            with GitHub(token, cache) as gh:
                with console.status("[dim]listing repos...[/dim]"):
                    repos = list(gh.my_repos())
                if not repos:
                    console.print("[yellow]No repos found for this account.[/yellow]")
                    return

                self._enrich(gh, repos, user)
                plan = build_plan(repos, threshold)
                render.render_plan(plan, threshold)

                if not options["apply"]:
                    return

                changes = plan.changes
                if not changes:
                    console.print("[green]Nothing to apply.[/green]")
                    return

                render.render_changes(changes)
                render.render_warnings(len(changes))
                if not options["yes"] and not self._confirm():
                    console.print("[dim]Aborted. Nothing changed.[/dim]")
                    return

                _applied, failed = self._apply(gh, changes)
        except GitHubError as exc:
            raise CommandError(str(exc)) from exc

        if options["apply"] and failed:
            sys.exit(1)

    @staticmethod
    def _confirm() -> bool:
        answer = input("Make these repos private? [y/N] ").strip().lower()
        return answer in {"y", "yes"}

    @staticmethod
    def _enrich(gh: GitHub, repos: list[Repo], author: str) -> None:
        """Second pass: the three per-repo facts the classifier needs."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[dim]{task.description}[/dim]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("inspecting repos...", total=len(repos))
            for repo in repos:
                progress.update(task, description=f"inspecting {repo.name}")
                repo.commits = gh.commit_count(repo.full_name, author)
                repo.has_readme = gh.has_readme(repo.full_name)
                repo.has_release = gh.has_release(repo.full_name)
                progress.advance(task)

    def _apply(self, gh: GitHub, changes) -> tuple[int, int]:
        """Patch every repo in `changes`. Returns (applied, failed) - both counted,
        never folded into each other, so the caller can report and exit accordingly.
        """
        from portfolio.models import TriageDecision, TriageRun

        run = TriageRun.objects.create()
        applied = 0
        failed = 0
        for decision in changes:
            name = decision.repo.full_name
            try:
                gh.make_private(name)
            except GitHubError as exc:
                console.print(f"  [red]FAILED[/red] {name}: {escape(str(exc))}")
                failed += 1
                continue
            console.print(f"  [yellow]private[/yellow] {name}")
            TriageDecision.objects.create(
                run=run,
                repo=name,
                action=TriageDecision.Action.HIDE,
                reason=", ".join(decision.reasons),
            )
            applied += 1

        if not applied:
            run.delete()

        console.print(
            f"\n[bold]{applied} repos made private, {failed} failed.[/bold] Nothing was deleted."
        )
        return applied, failed
