"""Terminal rendering. Knows nothing about GitHub or classification rules."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from .types import Decision, TriagePlan, Verdict

console = Console()

PILES: list[tuple[Verdict, str, str, str]] = [
    (Verdict.SHOWCASE, "SHOWCASE", "green", "stays public - this is the portfolio"),
    (Verdict.HIDE, "HIDE", "yellow", "make private - dead weight"),
    (Verdict.DELETE, "DELETE", "red", "suggested only, never automated"),
    (Verdict.SKIP, "SKIP", "dim", "already private, nothing to do"),
]


def render_plan(plan: TriagePlan, min_commits: int) -> None:
    total = len(plan.decisions)
    stale = sum(1 for d in plan.decisions if d.repo.days_since_push >= 90)
    console.print()
    console.print(
        f"[bold]{total} repos[/bold] · "
        f"{total - stale} pushed within 90 days · "
        f"[yellow]{stale} untouched for 90+ days[/yellow]"
    )
    console.print(f"[dim]portfolio threshold: {min_commits}+ commits and a README[/dim]")

    for verdict, label, color, blurb in PILES:
        rows = plan.by(verdict)
        if not rows:
            continue
        console.print()
        console.print(f"  [bold {color}]{label} ({len(rows)})[/bold {color}]  [dim]{blurb}[/dim]")
        console.print(_table(rows, color))

    console.print()
    changes = len(plan.changes)
    if changes:
        console.print(
            f"[bold]Nothing changed.[/bold] Review, then run: "
            f"[cyan]weekly triage --apply[/cyan]  "
            f"[dim]({changes} repos would become private)[/dim]"
        )
    else:
        console.print("[bold]Nothing to apply.[/bold] The portfolio is already clean.")
    console.print()


def _table(rows: list[Decision], color: str) -> Table:
    table = Table(show_header=False, box=None, padding=(0, 1, 0, 4))
    table.add_column("repo", style=color, no_wrap=True)
    table.add_column("age", justify="right", style="dim")
    table.add_column("why", style="dim")

    for d in rows:
        why = ", ".join(d.reasons)
        if d.polish:
            why += f"  [yellow]polish: {', '.join(d.polish)}[/yellow]"
        table.add_row(d.repo.name, d.repo.age_label, why)
    return table


def render_changes(changes: list[Decision]) -> None:
    """The exact repos --apply is about to make private, stars/forks included.

    Shown before the warnings and the confirmation prompt, so the counts about to be
    lost forever are visible right where the decision gets made.
    """
    console.print()
    console.print(f"[bold yellow]About to make {len(changes)} repos private:[/bold yellow]")
    table = Table(show_header=True, box=None, padding=(0, 1, 0, 4))
    table.add_column("repo", style="yellow", no_wrap=True)
    table.add_column("stars", justify="right", style="dim")
    table.add_column("forks", justify="right", style="dim")
    for d in changes:
        table.add_row(escape(d.repo.name), str(d.repo.stars), str(d.repo.forks))
    console.print(table)


def render_warnings(count: int) -> None:
    """Shown before --apply touches anything. These are not reversible in full."""
    console.print()
    console.print(Text("Before you apply, two things you cannot undo:", style="bold yellow"))
    console.print(
        "  1. Making a public repo private [bold]permanently loses its stars, "
        "forks and watchers.[/bold]"
    )
    console.print(
        "  2. Contributions from private repos only stay on your public graph if\n"
        "     [cyan]Settings -> Profile -> Include private contributions on my profile[/cyan]\n"
        "     is enabled. Turn it on first, or those green squares disappear."
    )
    console.print()
    console.print(f"[bold]{count} repos[/bold] would be made private. Nothing is deleted.")
    console.print()
