"""The admin is how goals get edited - a form instead of hand-editing TOML."""

from django.contrib import admin

from .models import Project, TriageDecision, TriageRun


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["repo", "status", "goal", "paused_until"]
    list_filter = ["status"]
    search_fields = ["repo", "goal"]


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
