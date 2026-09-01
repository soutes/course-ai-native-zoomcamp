"""Data shapes shared across the app.

Nothing here talks to the network or to an LLM. Everything downstream builds on
these, which is what keeps the deterministic layers testable from fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Verdict(StrEnum):
    """What triage thinks should happen to a repo."""

    SHOWCASE = "showcase"  # stays public, it is the portfolio
    HIDE = "hide"  # make private, dead weight
    DELETE = "delete"  # suggested only, never automated
    SKIP = "skip"  # already private or already handled


@dataclass
class Repo:
    """One GitHub repository, as far as triage cares."""

    name: str
    full_name: str
    html_url: str
    private: bool
    fork: bool
    archived: bool
    description: str | None
    topics: list[str]
    license: str | None
    default_branch: str
    created_at: datetime
    pushed_at: datetime
    stars: int
    forks: int

    # Filled in by a second pass, one request each.
    commits: int = 0
    has_readme: bool = False
    has_release: bool = False

    @property
    def days_since_push(self) -> int:
        return (datetime.now(tz=self.pushed_at.tzinfo) - self.pushed_at).days

    @property
    def age_label(self) -> str:
        """Human age of the last push: 3d, 5mo, 1y2m."""
        days = self.days_since_push
        if days < 31:
            return f"{days}d"
        months = days // 30
        if months < 12:
            return f"{months}mo"
        years, rem = divmod(months, 12)
        return f"{years}y{rem}m" if rem else f"{years}y"


@dataclass
class Decision:
    """Triage's call on one repo, with the reasons that produced it."""

    repo: Repo
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    polish: list[str] = field(default_factory=list)

    @property
    def applied_change(self) -> bool:
        """Whether --apply would actually touch this repo on GitHub."""
        return self.verdict is Verdict.HIDE and not self.repo.private


@dataclass
class TriagePlan:
    decisions: list[Decision]

    def by(self, verdict: Verdict) -> list[Decision]:
        return [d for d in self.decisions if d.verdict is verdict]

    @property
    def changes(self) -> list[Decision]:
        return [d for d in self.decisions if d.applied_change]
