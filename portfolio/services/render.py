"""Terminal rendering. Knows nothing about GitHub or classification rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from .health import HealthSignals
from .momentum_delta import PreviousMomentum, momentum_delta_text
from .stalled import STALLED_THRESHOLD_WEEKS
from .types import Decision, NewRepo, OpenPullRequest, TriagePlan, UnmergedBranch, Verdict
from .week import previous_week_label

if TYPE_CHECKING:
    # `portfolio.coach` is the LLM module - `portfolio/services/` imports no Django and
    # no LLM at runtime (AGENTS.md, Layering). This import only exists for type
    # checkers; `CoachingResult` is referenced below as a string annotation so no
    # runtime import of `coach.py` (and therefore no `httpx`/Django settings) happens
    # here. `coach.py` does the same in reverse for `WeeklyReportData`/`RepoReportData`.
    from portfolio.coach import CoachingResult

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
# Everything below renders `manage.py report`'s retro: four sections always, plus an
# optional fifth "Goal check" section (#29, D28). `render_report_markdown`
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
    ``stalled`` mirror `stalled.StalledStatus` (#14). ``description`` is the repo's GitHub
    description (``Repo.description``, may be `None`); ``commit_subjects`` are this week's
    commit subjects (``Commit.subject``), in chronological order - both rendered so the
    "renders literally, does not swallow text" AC is exercised against real content, not
    only PR titles.
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
    description: str | None = None
    commit_subjects: list[str] = field(default_factory=list)
    health: HealthSignals | None = None
    """Deterministic repo-health signals (#18) - README/tests/CI/license/
    description. `None` when health was not computed for this row (e.g. the
    repo could not be matched to a fetched `Repo`); a healthy `HealthSignals`
    (`missing_labels` empty) and `None` both produce no "went wrong" noise -
    see `_health_lines`."""
    previous: PreviousMomentum | None = None
    """This repo's previous-week momentum (#21), or `None` when no
    `RepoWeek` row is stored for the previous week ("first week tracked").
    Read by `repoweek_lookup.previous_momentum_for_repo`, not computed here."""
    goal: str = ""
    """This project's stated goal (`Project.goal`), or `""` when unset (#29,
    D28) - matches `Project.goal`'s own `blank=True`, so there is no `None`
    vs `""` ambiguity to handle. `report.py` passes `project.goal` through at
    the same call site that builds this row - no new query. Read by the
    "Goal check" section below and by `portfolio.coach` for drift judgement;
    never sent to the LLM for a repo where this is empty (D24/D28)."""


@dataclass
class WeeklyReportData:
    """Everything one week's retro needs to render.

    ``coaching`` carries the LLM advice built by `portfolio.coach.get_coaching` (#26) -
    a `CoachingResult` (every repo in `repos` landing in exactly one of
    `advice`/`unavailable`) on a successful parse, or `None` on total failure/not
    attempted (`--no-llm`, #27). `report.py`'s command wiring still always passes
    `coaching=None` today - actually calling `get_coaching` and threading a real
    result through is #27's job, not #26's. `render_report_markdown` must produce a
    complete, four-section report with it unset; see AGENTS.md's determinism rule
    ("`render` must work with `coaching = None`. Always.").
    """

    week: str
    repos: list[RepoReportData] = field(default_factory=list)
    new_repos: list[NewRepo] = field(default_factory=list)
    coaching: CoachingResult | None = None


def abandoned_count(repos: list[RepoReportData] | list[dict]) -> int:
    """How many tracked repos are flagged stalled this week (D4 in docs/decisions.md).

    The headline number #36's dashboard leads with - "how many projects have I
    quietly abandoned." Computed straight from #14's stalled flags: `repos` already
    excludes shipped/dropped repos and paused-in-force repos (`Project.in_weekly_report`
    filters those out before a `RepoReportData` list - or the `WeeklyReport.data["repos"]`
    snapshot built from it - ever exists), so this is a plain count of `stalled=True`
    entries, not a re-filter of status/pause rules.

    Accepts either `RepoReportData` instances (the terminal/#16 path, and #23's future
    header line) or the plain dicts stored in `WeeklyReport.data["repos"]` (D5 - the web
    path, #36 and later #17) - both shapes carry a `stalled` field, so either works
    without the caller converting one into the other.
    """
    return sum(
        1 for r in repos if (r.stalled if isinstance(r, RepoReportData) else bool(r.get("stalled")))
    )


def _s(n: int) -> str:
    """Pluralizes: `_s(1)` -> "", `_s(2)` -> "s"."""
    return "" if n == 1 else "s"


def _rhythm_phrase(active_days: int) -> str:
    """Categorize a repo's rhythm from its `active_days` count alone (#22, D20).

    Thresholds and wording live here, in one place, so `_went_well_lines`
    never duplicates them inline:
    - 1 active day -> **burst** ("all on one day")
    - 2-4 active days -> neutral **spread** ("spread across N days") - 2 and 3
      are deliberately not split into their own labels
    - 5+ active days -> **habit** ("spread across N days - a habit")

    Only called for repos with `commits > 0` (`_went_well_lines` filters
    silent repos out before calling this) - a repo with 0 commits never
    reaches here and gets no rhythm wording anywhere.
    """
    if active_days == 1:
        return "all on one day"
    if active_days >= 5:
        return f"spread across {active_days} days - a habit"
    return f"spread across {active_days} days"


def _went_well_lines(repos: list[RepoReportData]) -> list[str]:
    moved = [r for r in repos if r.commits > 0]
    if not moved:
        return [f"No repo moved this week (0 of {len(repos)} tracked)."]
    lines = []
    for r in moved:
        undercount = " (diffstat capped at 80/week - lines/files undercounted)" if r.partial else ""
        desc = f" - {r.description}" if r.description else ""
        latest = f'; latest commit: "{r.commit_subjects[-1]}"' if r.commit_subjects else ""
        delta = momentum_delta_text(r.previous)
        rhythm = _rhythm_phrase(r.active_days)
        lines.append(
            f"**{r.repo}**{desc} - {rhythm}, {r.commits} commit{_s(r.commits)} {delta.commits}, "
            f"{r.active_days} active day{_s(r.active_days)} {delta.active_days}, "
            f"+{r.lines_added} {delta.lines_added}/-{r.lines_removed} {delta.lines_removed} "
            f"lines across {r.files_touched} file{_s(r.files_touched)} "
            f"{delta.files_touched}{undercount}{latest}"
        )
    return lines


def _health_lines(repos: list[RepoReportData]) -> list[str]:
    """One line per repo carrying a definitively missing health signal (#18).

    A repo with `health is None` or with every signal known-present
    (`missing_labels` empty) contributes nothing - a healthy repo produces no
    noise here (#18's own AC). A signal left unknown by a truncated tree read
    is never reported as missing - see `health.HealthSignals.missing_labels`.
    """
    lines = []
    for r in repos:
        if r.health is None:
            continue
        labels = r.health.missing_labels
        if not labels:
            continue
        lines.append(f"**{r.repo}** - missing {', '.join(labels)}")
    return lines


def _went_wrong_lines(repos: list[RepoReportData]) -> list[str]:
    silent = [r for r in repos if r.commits == 0]
    if not silent:
        # Every project moved - "What went wrong" must still say something (#16's
        # own AC). Point at the thinnest slice of a portfolio that otherwise
        # looks fine: the failure is spread, not concentrated in one silent repo.
        total = sum(r.commits for r in repos)
        weakest = min(repos, key=lambda r: (r.commits, r.repo))
        weakest_desc = f" - {weakest.description}" if weakest.description else ""
        lines = [
            f"Nothing stalled - every one of the {len(repos)} tracked repos had a commit "
            f"this week, but it was spread thin: **{weakest.repo}**{weakest_desc} carried only "
            f"{weakest.commits} commit{_s(weakest.commits)} of {total} across the portfolio."
        ]
        return lines + _health_lines(repos)
    lines = []
    for r in silent:
        if r.weeks_since_last_commit is None:
            since = "0 commits on record"
        else:
            since = (
                f"{r.weeks_since_last_commit} week{_s(r.weeks_since_last_commit)} "
                "since its last commit"
            )
        tag = " - stalled" if r.stalled else ""
        desc = f" - {r.description}" if r.description else ""
        commits_delta = momentum_delta_text(r.previous).commits
        lines.append(f"**{r.repo}**{desc} - 0 commits this week {commits_delta}, {since}{tag}")
    return lines + _health_lines(repos)


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


def _deterministic_focus_sentence(repos: list[RepoReportData]) -> tuple[str, str | None]:
    """The existing #16 deterministic sentence, plus which repo it names (or
    `None` for the "0 tracked repos" case, which names no repo).

    Priority: a repo silent this week (worst weeks-since-last-commit first,
    `None` - never committed - ranks worst) > the oldest open branch/PR in the
    whole portfolio > if everything is moving and current, the repo carrying
    the least of this week's commits, to keep the weakest link visible.
    """
    if not repos:
        return (
            "Track a project this week - nothing is being watched yet (0 tracked repos).",
            None,
        )

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
                "it has 0 commits on record.",
                worst.repo,
            )
        return (
            f"Get **{worst.repo}** committing again this week - it has been "
            f"{worst.weeks_since_last_commit} week{_s(worst.weeks_since_last_commit)} "
            "since its last commit.",
            worst.repo,
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
        _, repo, desc = mid_flight[0]
        return (
            f"Merge or close {desc} this week - it is the oldest mid-flight work in the portfolio.",
            repo,
        )

    total = sum(r.commits for r in repos)
    weakest = min(repos, key=lambda r: (r.commits, r.repo))
    return (
        f"Keep the momentum on **{weakest.repo}** this week - it had only "
        f"{weakest.commits} commit{_s(weakest.commits)}, the least of the {len(repos)} "
        f"tracked repos ({total} commits total).",
        weakest.repo,
    )


def _focus_item_text(repos: list[RepoReportData], coaching: CoachingResult | None = None) -> str:
    """The single focus item (#16, extended by #28/D27).

    Which repo is the focus is always #16's existing deterministic priority
    algorithm (`_deterministic_focus_sentence`) - `coaching` never changes the
    pick, only the wording of the line about the repo already chosen (D27
    point 1/2). When `coaching` is not `None` and the selected repo has a
    usable entry in `coaching.advice` (present, not in `coaching.unavailable`),
    the line is that advice text wrapped in a fixed template naming the repo.
    Otherwise (`coaching is None`, or the repo missing from `advice`, or in
    `unavailable`) this renders today's unchanged deterministic sentence -
    never a "focus needs the LLM" placeholder (D27 point 4).
    """
    sentence, repo = _deterministic_focus_sentence(repos)
    if coaching is None or repo is None:
        return sentence

    advice = coaching.advice.get(repo)
    if advice is None or repo in coaching.unavailable:
        return sentence

    return f"This week: **{repo}** - {advice}"


def _goal_check_lines(repos: list[RepoReportData], coaching: CoachingResult | None) -> list[str]:
    """One line per repo with a stated goal, commits this week, and a resolved
    drift verdict (#29, D28).

    A repo is skipped - contributes no line - when: `coaching is None`
    (`--no-llm`, total LLM failure, or not attempted), `r.goal` is empty
    (no goal set), `r.commits == 0` (silent this week - #14's job, not
    drift's), or `r.repo` has no entry in `coaching.drift` (never sent for
    drift judgement, or sent but resolved into `coaching.drift_unavailable`
    instead). Each surviving line names the goal and the model's verdict
    text, which is asked (in `coach.py`'s prompt) to cite a commit subject as
    evidence.
    """
    if coaching is None:
        return []
    lines = []
    for r in repos:
        if not r.goal or r.commits == 0:
            continue
        verdict = coaching.drift.get(r.repo)
        if verdict is None:
            continue
        lines.append(f"**{r.repo}** - goal: {r.goal} - {verdict}")
    return lines


def render_report_markdown(data: WeeklyReportData) -> str:
    """The retro as plain markdown text: four sections always, plus an optional
    fifth "Goal check" section (#29, D28). Pure: no Rich, no Django, no LLM,
    and works with `data.coaching is None` (the default - see
    `WeeklyReportData`).

    Every bullet carries a repo name and a number (#16's own AC - "no bare
    adjectives"). "What went wrong" is never empty and "This week's focus"
    is always exactly one line - see `_went_wrong_lines`/`_focus_item_text`.
    A week with no tracked repos at all still renders all four sections.
    "Goal check" is entirely absent (no heading) when `_goal_check_lines`
    has nothing to show - see its own docstring for exactly when that is.
    """
    repos = sorted(data.repos, key=lambda r: r.repo)
    new_repos = sorted(data.new_repos, key=lambda nr: nr.created_at)

    prior_week = previous_week_label(data.week)
    lines = [f"# Weekly Retro - {data.week} (this week), vs {prior_week} (last week)", ""]

    abandoned = abandoned_count(repos)
    lines.append(
        f"{abandoned} project{_s(abandoned)} with no commit for {STALLED_THRESHOLD_WEEKS}+ weeks"
    )
    lines.append("")

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
    lines.append(_focus_item_text(repos, data.coaching))
    lines.append("")

    goal_lines = _goal_check_lines(repos, data.coaching)
    if goal_lines:
        lines.append("## Goal check")
        lines.append("")
        lines += [f"- {line}" for line in goal_lines]
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
        "focus": _focus_item_text(repos, data.coaching),
    }
