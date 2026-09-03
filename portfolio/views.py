"""Web surface. The terminal and the browser read the same data."""

from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import Project, TriageRun, WeeklyReport
from .services.markdown_render import render_markdown_html
from .services.week import week_window


def dashboard(request):
    """Portfolio at a glance: tracked projects and the triage history."""
    projects = list(Project.objects.all())
    return render(
        request,
        "portfolio/dashboard.html",
        {
            "projects": projects,
            "active": [p for p in projects if p.status == Project.Status.ACTIVE],
            "ended": [
                p
                for p in projects
                if p.status in {Project.Status.SHIPPED, Project.Status.DROPPED}
            ],
            "runs": TriageRun.objects.prefetch_related("decisions")[:5],
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
