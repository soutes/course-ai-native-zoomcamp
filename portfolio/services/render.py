"""Terminal rendering. Knows nothing about GitHub or classification rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from .types import Decision, NewRepo, OpenPullRequest, TriagePlan, UnmergedBranch, Verdict

console = Console()

PILES: list[tuple[Verdict, str, str, str]] = [
    (Verdict.SHOWCASE, "SHOWCASE", "green", "stays public - this is the portfolio"),
    (Verdict.HIDE, "HIDE", "yellow", "make private - dead weight"),
    (
        Verdict.DELETE,
        "DELETE",
        "red",
        "suggested only - delete it yourself in the GitHub UI, never automated",
    ),
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


# --- weekly report (#16) ------------------------------------------------------------
#
# Everything below renders `manage.py report`'s four-section retro. `render_report_markdown`
# is pure - plain data in, a markdown string out, no Rich, no Django, no LLM - so the
# section/never-empty/exactly-one-focus-item rules are testable from fixtures with no
# console involved. `render_report` is the only impure piece: it wraps that string in
# `rich.markdown.Markdown` and prints it, which is what keeps a `[` in a commit subject or
# repo description literal (Markdown parses CommonMark, not Rich's own `[style]` console
# markup, so brackets never get mistaken for a markup tag and swallowed).


@dataclass
class RepoReportData:
    """One tracked repo's row of data for a weekly report - plain values, not
    the `RepoWeek`/`Project` models, so this module stays Django-free.

    ``commits``/``active_days``/``lines_added``/``lines_removed``/``files_touched``/``partial``
    mirror `momentum.RepoWeekStats` for this repo and week. ``weeks_since_last_commit``/
    ``stalled`` mirror `stalled.StalledStatus` (#14).
    """

    repo: str
    commits: int
    active_days: int
    lines_added: int
    lines_removed: int
    files_touched: int
    partial: bool
    weeks_since_last_commit: int | None
    stalled: bool
    unmerged_branches: list[UnmergedBranch] = field(default_factory=list)
    open_pull_requests: list[OpenPullRequest] = field(default_factory=list)


@dataclass
class WeeklyReportData:
    """Everything one week's retro needs to render.

    ``coaching`` is a placeholder for the LLM advice #24-#28 add later
    (post-mvp, out of scope here) - it is always `None` today.
    `render_report_markdown` must produce a complete, four-section report
    with it unset; see AGENTS.md's determinism rule ("`render` must work
    with `coaching = None`. Always.").
    """

    week: str
    repos: list[RepoReportData] = field(default_factory=list)
    new_repos: list[NewRepo] = field(default_factory=list)
    coaching: str | None = None


def _s(n: int) -> str:
    """Pluralizes: `_s(1)` -> "", `_s(2)` -> "s"."""
    return "" if n == 1 else "s"


def _went_well_lines(repos: list[RepoReportData]) -> list[str]:
    moved = [r for r in repos if r.commits > 0]
    if not moved:
        return [f"No repo moved this week (0 of {len(repos)} tracked)."]
    lines = []
    for r in moved:
        undercount = " (diffstat capped at 80/week - lines/files undercounted)" if r.partial else ""
        lines.append(
            f"**{r.repo}** - {r.commits} commit{_s(r.commits)}, "
            f"{r.active_days} active day{_s(r.active_days)}, "
            f"+{r.lines_added}/-{r.lines_removed} lines across "
            f"{r.files_touched} file{_s(r.files_touched)}{undercount}"
        )
    return lines


def _went_wrong_lines(repos: list[RepoReportData]) -> list[str]:
    silent = [r for r in repos if r.commits == 0]
    if not silent:
        # Every project moved - "What went wrong" must still say something (#16's
        # own AC). Point at the thinnest slice of a portfolio that otherwise
        # looks fine: the failure is spread, not concentrated in one silent repo.
        total = sum(r.commits for r in repos)
        weakest = min(repos, key=lambda r: (r.commits, r.repo))
        return [
            f"Nothing stalled - every one of the {len(repos)} tracked repos had a commit "
            f"this week, but it was spread thin: **{weakest.repo}** carried only "
            f"{weakest.commits} commit{_s(weakest.commits)} of {total} across the portfolio."
        ]
    lines = []
    for r in silent:
        if r.weeks_since_last_commit is None:
            since = "no commit on record"
        else:
            since = (
                f"{r.weeks_since_last_commit} week{_s(r.weeks_since_last_commit)} "
                "since its last commit"
            )
        tag = " - stalled" if r.stalled else ""
        lines.append(f"**{r.repo}** - 0 commits this week, {since}{tag}")
    return lines


def _doing_lines(repos: list[RepoReportData], new_repos: list[NewRepo]) -> list[str]:
    lines = []
    for r in repos:
        for b in r.unmerged_branches:
            lines.append(
                f"**{r.repo}** - branch `{b.name}` ahead by {b.ahead_by} "
                f"commit{_s(b.ahead_by)}, open {b.age_days} day{_s(b.age_days)}"
            )
        for pr in r.open_pull_requests:
            draft = " (draft)" if pr.draft else ""
            lines.append(
                f'**{r.repo}** - PR #{pr.number} "{pr.title}" open '
                f"{pr.age_days} day{_s(pr.age_days)}{draft}"
            )
    for nr in new_repos:
        lines.append(
            f"**{nr.name}** - new repo, created this week, "
            f"{nr.commits} commit{_s(nr.commits)} so far"
        )

    if not lines:
        names = ", ".join(r.repo for r in repos)
        lines.append(
            f"No open branches or pull requests across the {len(repos)} tracked "
            f"repo{_s(len(repos))} ({names})"
        )
    return lines


def _focus_item_text(repos: list[RepoReportData]) -> str:
    """The single deterministic focus item (#16's AC; #28's future LLM version
    replaces this, still capped at one - see docs/decisions.md's reasoning for
    why one is enforced in code, not requested of a model).

    Priority: a repo silent this week (worst weeks-since-last-commit first,
    `None` - never committed - ranks worst) > the oldest open branch/PR in the
    whole portfolio > if everything is moving and current, the repo carrying
    the least of this week's commits, to keep the weakest link visible.
    """
    if not repos:
        return "Track a project this week - nothing is being watched yet (0 tracked repos)."

    silent = [r for r in repos if r.commits == 0]
    if silent:
        never = 1 << 30  # sentinel: "never committed" outranks any finite week count

        def rank(r: RepoReportData) -> tuple[int, str]:
            weeks = never if r.weeks_since_last_commit is None else -r.weeks_since_last_commit
            return (weeks, r.repo)

        worst = min(silent, key=rank)
        if worst.weeks_since_last_commit is None:
            return (
                f"Make the first commit to **{worst.repo}** this week - "
                "it has no commit on record yet."
            )
        return (
            f"Get **{worst.repo}** committing again this week - it has been "
            f"{worst.weeks_since_last_commit} week{_s(worst.weeks_since_last_commit)} "
            "since its last commit."
        )

    mid_flight: list[tuple[int, str, str]] = []
    for r in repos:
        for b in r.unmerged_branches:
            mid_flight.append(
                (
                    b.age_days,
                    r.repo,
                    f"branch `{b.name}` in **{r.repo}**, open {b.age_days} day{_s(b.age_days)}",
                )
            )
        for pr in r.open_pull_requests:
            mid_flight.append(
                (
                    pr.age_days,
                    r.repo,
                    f"PR #{pr.number} in **{r.repo}**, open {pr.age_days} day{_s(pr.age_days)}",
                )
            )
    if mid_flight:
        mid_flight.sort(key=lambda t: (-t[0], t[1]))
        _, _, desc = mid_flight[0]
        return (
            f"Merge or close {desc} this week - it is the oldest mid-flight work in the portfolio."
        )

    total = sum(r.commits for r in repos)
    weakest = min(repos, key=lambda r: (r.commits, r.repo))
    return (
        f"Keep the momentum on **{weakest.repo}** this week - it had only "
        f"{weakest.commits} commit{_s(weakest.commits)}, the least of the {len(repos)} "
        f"tracked repos ({total} commits total)."
    )


def render_report_markdown(data: WeeklyReportData) -> str:
    """The four-section retro as plain markdown text. Pure: no Rich, no Django,
    no LLM, and works with `data.coaching is None` (always true today - see
    `WeeklyReportData`).

    Every bullet carries a repo name and a number (#16's own AC - "no bare
    adjectives"). "What went wrong" is never empty and "This week's focus"
    is always exactly one line - see `_went_wrong_lines`/`_focus_item_text`.
    A week with no tracked repos at all still renders all four sections.
    """
    repos = sorted(data.repos, key=lambda r: r.repo)
    new_repos = sorted(data.new_repos, key=lambda nr: nr.created_at)

    lines = [f"# Weekly Retro - {data.week}", ""]

    lines.append("## What went well")
    lines.append("")
    if not repos:
        lines.append("- No tracked projects this week (0 tracked).")
    else:
        lines += [f"- {line}" for line in _went_well_lines(repos)]
    lines.append("")

    lines.append("## What went wrong")
    lines.append("")
    if not repos:
        lines.append("- No tracked projects this week (0 tracked) - nothing to report on.")
    else:
        lines += [f"- {line}" for line in _went_wrong_lines(repos)]
    lines.append("")

    lines.append("## What I'm doing")
    lines.append("")
    if not repos:
        lines.append("- No tracked projects this week (0 tracked).")
    else:
        lines += [f"- {line}" for line in _doing_lines(repos, new_repos)]
    lines.append("")

    lines.append("## This week's focus")
    lines.append("")
    lines.append(_focus_item_text(repos))
    lines.append("")

    return "\n".join(lines)


def render_report(data: WeeklyReportData) -> None:
    """Print the report to the terminal via Rich's `Markdown` renderer.

    Deliberately not `console.print(markdown_text)` - that would run the
    string through Rich's own `[style]` console markup, which is exactly
    what eats a repo description or commit subject containing `[` (#16's own
    AC, and the bug AGENTS.md's "Conventions" section already warns about).
    `Markdown` parses CommonMark instead, so a literal `[` that is not valid
    markdown link syntax renders as text, not as markup.
    """
    console.print(Markdown(render_report_markdown(data)))


def build_report_snapshot(data: WeeklyReportData) -> dict:
    """The JSON persisted on `WeeklyReport.data` (D5 in docs/decisions.md).

    Momentum numbers are deliberately left out - they already live in
    `RepoWeek`, keyed by (repo, week), and D5 is explicit that those rows are
    "referenced, not duplicated" here. This snapshot only carries what no
    other stored row does: per-repo mid-flight work (#15), the
    new-repos-this-week list (#33), and the single focus item, so #17/#36
    can render without recomputing any of it or calling GitHub again.
    """
    repos = sorted(data.repos, key=lambda r: r.repo)
    return {
        "week": data.week,
        "repos": [
            {
                "repo": r.repo,
                "weeks_since_last_commit": r.weeks_since_last_commit,
                "stalled": r.stalled,
                "unmerged_branches": [
                    {
                        "name": b.name,
                        "ahead_by": b.ahead_by,
                        "last_commit_at": b.last_commit_at.isoformat(),
                    }
                    for b in r.unmerged_branches
                ],
                "open_pull_requests": [
                    {
                        "number": pr.number,
                        "title": pr.title,
                        "created_at": pr.created_at.isoformat(),
                        "draft": pr.draft,
                    }
                    for pr in r.open_pull_requests
                ],
            }
            for r in repos
        ],
        "new_repos": [
            {"name": nr.name, "created_at": nr.created_at.isoformat(), "commits": nr.commits}
            for nr in sorted(data.new_repos, key=lambda nr: nr.created_at)
        ],
        "focus": _focus_item_text(repos),
    }
