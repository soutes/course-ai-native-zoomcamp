"""Web surface. The terminal and the browser read the same data."""

from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import WeeklyReport
from .services import render as render_service
from .services.markdown_render import render_markdown_html
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
