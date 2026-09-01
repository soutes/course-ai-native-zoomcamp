"""Web surface. The terminal and the browser read the same data."""

from django.shortcuts import render

from .models import Project, TriageRun


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
