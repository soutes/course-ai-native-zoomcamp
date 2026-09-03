"""`manage.py report` - the Monday-morning weekly retrospective.

Wiring only: read settings, fetch each tracked project's week from GitHub,
run it through the deterministic services (`week`, `momentum`, `stalled_lookup`,
`new_repos`), render the four-section markdown via `portfolio.services.render`,
print it, and persist a `WeeklyReport` row (#16, D5 in docs/decisions.md) so
#17/#36 can render later with no GitHub call. All the shaping - what counts as
"went well", the never-empty rule, the one focus item - lives in
`portfolio/services/render.py`, which knows nothing about Django or GitHub.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from portfolio.models import Project, WeeklyReport
from portfolio.services import render
from portfolio.services.cache import Cache
from portfolio.services.github import GitHub, GitHubError
from portfolio.services.health import judge_health
from portfolio.services.lifecycle import apply_transition
from portfolio.services.momentum import compute_repo_week
from portfolio.services.new_repos import new_repos_this_week
from portfolio.services.repoweek import persist_repo_week
from portfolio.services.repoweek_lookup import previous_momentum_for_repo
from portfolio.services.shipped import AUTO_PREFIX, detect_shipped
from portfolio.services.stalled_lookup import stalled_status_for_project
from portfolio.services.week import week_label, week_window

console = Console()


class Command(BaseCommand):
    help = "Print the weekly retrospective as markdown: four sections, every claim numbered."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--week",
            default=None,
            help="ISO week label, e.g. 2026-W35. Defaults to the current week.",
        )
        parser.add_argument(
            "--repo", default=None, help="Limit the report to one repo (owner/name)."
        )
        parser.add_argument("--out", default=None, help="Also write plain markdown to this file.")
        parser.add_argument("--refresh", action="store_true", help="Ignore the cache and re-fetch.")
        parser.add_argument(
            "--last",
            action="store_true",
            help=(
                "Reprint the most recently generated WeeklyReport from storage. "
                "No GitHub request, no LLM request, no token/user/email configuration required."
            ),
        )

    def handle(self, *args, **options) -> None:
        if options["last"]:
            if options["week"]:
                raise CommandError("--last and --week are contradictory - use one or the other.")
            if options["repo"]:
                raise CommandError(
                    "--last and --repo are contradictory - a --repo run never persists a "
                    "WeeklyReport row, so there is nothing narrowed to reprint."
                )
            row = WeeklyReport.objects.order_by("-generated_at").first()
            if row is None:
                self.stdout.write("No weekly report has been generated yet.")
                return
            # Plain `self.stdout.write`, not `console.print` or Rich's `Markdown` -
            # the AC requires printing `row.markdown` back byte-identical to what
            # was stored, and both of those would reinterpret or reformat it.
            self.stdout.write(
                f"Showing the report for {row.week}, generated {row.generated_at.isoformat()}"
            )
            self.stdout.write(row.markdown)
            return

        user = settings.GITHUB_USER
        token = settings.GITHUB_TOKEN
        emails = settings.GITHUB_EMAILS
        if not user:
            raise CommandError("GITHUB_USER is not set. Copy .env.example to .env and fill it in.")
        if not token:
            raise CommandError(
                "GITHUB_TOKEN is not set.\n"
                "Create a Personal Access Token with the `repo` scope at\n"
                "  https://github.com/settings/tokens\n"
                "then put it in .env as GITHUB_TOKEN=..."
            )
        if not emails:
            raise CommandError(
                "GITHUB_EMAILS is not set - the report cannot tell your commits from anyone "
                "else's in a shared repo. Set it in .env (comma separated)."
            )

        tz = ZoneInfo(settings.TIME_ZONE)
        try:
            window = week_window(options["week"], tz=tz) if options["week"] else week_window(tz=tz)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        week = week_label(window)

        if options["repo"]:
            try:
                project = Project.objects.get(repo=options["repo"])
            except Project.DoesNotExist:
                raise CommandError(f"No tracked project named {options['repo']!r}.") from None
            if not project.in_weekly_report:
                raise CommandError(
                    f"{project.repo} is not in the weekly report right now "
                    f"(status={project.status})."
                )
            projects = [project]
        else:
            projects = [p for p in Project.objects.all() if p.in_weekly_report]

        cache = Cache("report")
        if options["refresh"]:
            console.print(f"[dim]cache cleared ({cache.clear()} entries)[/dim]")

        try:
            with GitHub(token, cache) as gh:
                with console.status("[dim]listing repos...[/dim]"):
                    all_repos = list(gh.my_repos())
                by_full_name = {r.full_name: r for r in all_repos}

                repo_rows: list[render.RepoReportData] = []
                commit_counts: dict[str, int] = {}

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[dim]{task.description}[/dim]"),
                    console=console,
                    transient=True,
                ) as progress:
                    task = progress.add_task("fetching...", total=len(projects))
                    for project in projects:
                        progress.update(task, description=f"fetching {project.repo}")
                        full_name = project.repo

                        # #20: shipped-signal detection, before anything else is
                        # fetched for this repo. Only ever runs against a project
                        # with no human-typed status_reason (blank, i.e. still
                        # untouched) or one this same mechanism wrote previously
                        # (D18) - an explicit `ack` reason is never overridden. A
                        # signal that fires writes the transition via #19's
                        # apply_transition and drops the repo from this run's
                        # output, not the next one's.
                        if project.status_reason == "" or project.status_reason.startswith(
                            AUTO_PREFIX
                        ):
                            shipped_reason = detect_shipped(
                                has_release=gh.has_release(full_name),
                                tags=gh.tags(full_name),
                                readme_text=gh.readme_text(full_name),
                            )
                            if shipped_reason:
                                apply_transition(
                                    project, Project.Status.SHIPPED, reason=shipped_reason
                                )
                                progress.advance(task)
                                continue

                        commits = gh.commits_in_window(full_name, window, emails)
                        commit_counts[full_name] = len(commits)
                        commit_subjects = [
                            c.subject for c in sorted(commits, key=lambda c: c.authored_at)
                        ]

                        stats = compute_repo_week(
                            commits,
                            lambda c, fn=full_name: gh.commit_diffstat(fn, c.sha),
                            tz,
                        )
                        previous = previous_momentum_for_repo(full_name, week)
                        persist_repo_week(full_name, week, window, stats)

                        stalled = stalled_status_for_project(project, week, tz)

                        repo = by_full_name.get(full_name)
                        default_branch = repo.default_branch if repo else "main"
                        branches = gh.unmerged_branches(full_name, default_branch)
                        prs = gh.open_pull_requests(full_name, user)

                        # #18: repo health signals - only computable when this
                        # project's repo was actually found among the fetched
                        # `Repo`s (license/description live there, per D15).
                        health = (
                            judge_health(gh.tree(full_name, default_branch), repo) if repo else None
                        )

                        repo_rows.append(
                            render.RepoReportData(
                                repo=full_name,
                                commits=stats.commits,
                                active_days=stats.active_days,
                                lines_added=stats.lines_added,
                                lines_removed=stats.lines_removed,
                                files_touched=stats.files_touched,
                                partial=stats.partial,
                                weeks_since_last_commit=stalled.weeks_since_last_commit,
                                stalled=stalled.stalled,
                                unmerged_branches=branches,
                                open_pull_requests=prs,
                                description=repo.description if repo else None,
                                commit_subjects=commit_subjects,
                                health=health,
                                previous=previous,
                            )
                        )
                        progress.advance(task)

                new_repo_candidates = (
                    all_repos
                    if not options["repo"]
                    else [r for r in all_repos if r.full_name == options["repo"]]
                )
                new_repos = new_repos_this_week(new_repo_candidates, window, commit_counts)

                # #20: reactivation pass, D18 - a project this feature auto-shipped
                # that has since resumed committing goes back to `active`. Scoped to
                # `status_reason` starting with `AUTO_PREFIX` only, so a project a
                # human shipped via `ack --shipped` is never auto-reactivated. Runs
                # only on a full-portfolio run: `--repo` is a narrowed view of one
                # project (same reasoning as skipping `WeeklyReport` persistence
                # below) and must not flip the state of an unrelated repo.
                if not options["repo"]:
                    auto_shipped = Project.objects.filter(status=Project.Status.SHIPPED).filter(
                        status_reason__startswith=AUTO_PREFIX
                    )
                    for shipped_project in auto_shipped:
                        resumed = gh.commits_in_window(shipped_project.repo, window, emails)
                        if resumed:
                            apply_transition(
                                shipped_project,
                                Project.Status.ACTIVE,
                                reason=f"{AUTO_PREFIX}commits resumed",
                            )
        except GitHubError as exc:
            raise CommandError(str(exc)) from exc

        data = render.WeeklyReportData(
            week=week, repos=repo_rows, new_repos=new_repos, coaching=None
        )
        markdown = render.render_report_markdown(data)

        if options["out"]:
            Path(options["out"]).write_text(markdown, encoding="utf-8")

        render.render_report(data)

        if options["repo"]:
            # A --repo run is a narrowed view, not the week's full picture - #17/#36
            # trust WeeklyReport to hold every tracked repo (D5). Persisting a
            # single-repo snapshot here would either create a partial row or
            # silently clobber an existing full-portfolio one for the same week.
            return

        WeeklyReport.objects.update_or_create(
            week=week,
            defaults={"markdown": markdown, "data": render.build_report_snapshot(data)},
        )
