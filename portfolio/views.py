"""Web surface. The terminal and the browser read the same data."""

from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import Project, TriageDecision, TriageRun, WeeklyReport
from .services import render as render_service
from .services.markdown_render import render_markdown_html
from .services.projects import STATUS_LABELS, STATUS_ORDER, group_projects, triage_history
from .services.week import week_label, week_window


def dashboard(request):
    """Landing page (#36): "where am I right now," this week.

    Reads only the current ISO week's stored `WeeklyReport` row (D5) - no GitHub
    call, no LLM call, opening the page costs nothing. When the current week has
    no stored data yet (`report` has not run for it), the page says so and links
    to the most recent week that does, instead of 404ing or rendering empty
    sections (`WeeklyReport.Meta.ordering = ["-week"]` makes `.first()` the most
    recent by ISO week label, same lexicographic-sort property `retro_list` relies
    on). The abandoned count is computed via the shared D4 helper
    (`portfolio.services.render.abandoned_count`) from #14's stalled flags already
    carried in the stored snapshot - not recomputed, not re-fetched.
    """
    current_week = week_label(week_window())
    report = WeeklyReport.objects.filter(week=current_week).first()

    if report is not None:
        return render(
            request,
            "portfolio/dashboard.html",
            {
                "current_week": current_week,
                "report": report,
                "abandoned": render_service.abandoned_count(report.data.get("repos", [])),
                "report_html": render_markdown_html(report.markdown),
                "most_recent": None,
            },
        )

    most_recent = WeeklyReport.objects.first()
    return render(
        request,
        "portfolio/dashboard.html",
        {
            "current_week": current_week,
            "report": None,
            "abandoned": None,
            "report_html": None,
            "most_recent": most_recent,
        },
    )


def retro_list(request):
    """Every week that has a stored retro (#17), newest first, each linking to its page.

    `WeeklyReport`'s own `Meta.ordering = ["-week"]` already sorts newest-first - ISO
    week labels (``YYYY-Www``) sort correctly as plain strings.
    """
    return render(
        request,
        "portfolio/retro_list.html",
        {"reports": WeeklyReport.objects.all()},
    )


def retro_detail(request, week):
    """One week's retro (#17), read straight from its stored `WeeklyReport` row (D5).

    No GitHub call and no recomputation: `week_window` (#11) only validates the label
    shape here, it does not fetch anything. A malformed label or a week with no stored
    row both 404 - never an empty page or a traceback.
    """
    try:
        week_window(week)
    except ValueError as exc:
        raise Http404(f"malformed ISO week label: {week!r}") from exc

    report = get_object_or_404(WeeklyReport, week=week)
    return render(
        request,
        "portfolio/retro_detail.html",
        {"week": week, "report_html": render_markdown_html(report.markdown)},
    )


def projects(request):
    """Public, no-login home for tracked projects and a triage-history summary (#43).

    Reads `Project`/`TriageRun`/`TriageDecision` from the database only - no GitHub
    call, no LLM call, same offline guarantee `dashboard`/`retro_list`/`retro_detail`
    already give. The grouping/counting (D12) lives in `portfolio.services.projects`;
    this view only queries and hands rows to it. Triage history never names a repo or
    renders `TriageDecision.reason` (decision D13) - only each run's date and how many
    of its decisions made a repo private, aggregated here with `Count` so the service
    module never has to touch the ORM.
    """
    shaped = group_projects(Project.objects.all())
    sections = [
        {
            "key": status,
            "label": STATUS_LABELS[status],
            "rows": shaped["groups"][status],
            "count": shaped["counts"][status],
        }
        for status in STATUS_ORDER
    ]

    runs = TriageRun.objects.annotate(
        hidden_count=Count("decisions", filter=Q(decisions__action=TriageDecision.Action.HIDE))
    )
    history = triage_history(runs)

    return render(
        request,
        "portfolio/projects.html",
        {
            "sections": sections,
            "total": shaped["total"],
            "triage_history": history,
        },
    )
