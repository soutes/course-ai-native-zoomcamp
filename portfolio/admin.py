"""The admin is how goals get edited - a form instead of hand-editing TOML."""

from django import forms
from django.contrib import admin
from django.shortcuts import redirect, render
from django.urls import path

from .models import Project, TriageDecision, TriageRun
from .services.lifecycle import apply_transition


class PauseUntilForm(forms.Form):
    """Collects the date the pause action needs - a bulk pause with no date
    would silently become an open-ended one, which #19 rules out.
    """

    paused_until = forms.DateField(
        label="Paused until", help_text="ISO date, e.g. 2026-11-01. Required."
    )
    reason = forms.CharField(label="Reason", required=False, max_length=280)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["repo", "status", "goal", "paused_until"]
    list_filter = ["status"]
    search_fields = ["repo", "goal"]
    actions = ["mark_shipped", "mark_dropped", "mark_paused"]

    def get_urls(self):
        return [
            path(
                "pause/",
                self.admin_site.admin_view(self.pause_view),
                name="portfolio_project_pause",
            ),
        ] + super().get_urls()

    @admin.action(description="Mark selected projects as shipped")
    def mark_shipped(self, request, queryset):
        for project in queryset:
            apply_transition(project, Project.Status.SHIPPED)
        self.message_user(request, f"{queryset.count()} project(s) marked shipped.")

    @admin.action(description="Drop selected projects")
    def mark_dropped(self, request, queryset):
        for project in queryset:
            apply_transition(project, Project.Status.DROPPED)
        self.message_user(request, f"{queryset.count()} project(s) dropped.")

    @admin.action(description="Pause selected projects until…")
    def mark_paused(self, request, queryset):
        # A bulk action can only return a redirect, not render a form directly -
        # stash the selected ids in the session and hand off to a real view that
        # asks for the one thing this transition cannot do without: a date.
        request.session["ack_pause_project_ids"] = list(queryset.values_list("pk", flat=True))
        return redirect("admin:portfolio_project_pause")

    def pause_view(self, request):
        ids = request.session.get("ack_pause_project_ids", [])
        queryset = Project.objects.filter(pk__in=ids)
        if request.method == "POST":
            form = PauseUntilForm(request.POST)
            if form.is_valid() and queryset.exists():
                for project in queryset:
                    apply_transition(
                        project,
                        Project.Status.PAUSED,
                        reason=form.cleaned_data["reason"],
                        paused_until=form.cleaned_data["paused_until"],
                    )
                self.message_user(request, f"{queryset.count()} project(s) paused.")
                request.session.pop("ack_pause_project_ids", None)
                return redirect("admin:portfolio_project_changelist")
        else:
            form = PauseUntilForm()
        return render(
            request,
            "admin/portfolio/project/pause.html",
            {
                "form": form,
                "projects": queryset,
                "opts": self.model._meta,
                "title": "Pause projects until…",
            },
        )


class TriageDecisionInline(admin.TabularInline):
    model = TriageDecision
    extra = 0
    can_delete = False
    readonly_fields = ["repo", "action", "reason"]


@admin.register(TriageRun)
class TriageRunAdmin(admin.ModelAdmin):
    list_display = ["ran_at", "repo_count"]
    inlines = [TriageDecisionInline]
    readonly_fields = ["ran_at"]

    @admin.display(description="repos")
    def repo_count(self, run: TriageRun) -> int:
        return run.decisions.count()
