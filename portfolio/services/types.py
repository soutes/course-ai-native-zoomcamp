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
class Commit:
    """One commit I authored, as far as the weekly report cares.

    Deliberately small - just enough for #13 (momentum stats) and #25 (the LLM
    prompt, subjects only, never diffs).
    """

    sha: str
    authored_at: datetime
    subject: str


@dataclass
class CommitStat:
    """The diffstat of one commit, as far as the weekly report cares (#13).

    ``files_changed`` counts every entry GitHub's `files` list returns, including
    binary files and pure renames - those carry no textual diff but are still a
    file touched. ``additions``/``deletions`` come straight from GitHub's own
    per-commit `stats`, which is already 0/0 for a file with no textual diff, so
    nothing here needs to inspect a `patch` that might not exist.
    """

    sha: str
    additions: int
    deletions: int
    files_changed: int


@dataclass
class UnmergedBranch:
    """A non-default branch ahead of the default branch and not merged into it -
    mid-flight work (#15). Sourced from GitHub's `compare` endpoint
    (base=default, head=branch): ``ahead_by`` is its `ahead_by`, and
    ``last_commit_at`` is the branch head commit's date. A branch behind but
    not ahead of default is stale, not mid-flight, and never becomes one of
    these - see `GitHub.unmerged_branches`.
    """

    name: str
    ahead_by: int
    last_commit_at: datetime

    @property
    def age_days(self) -> int:
        return (datetime.now(tz=self.last_commit_at.tzinfo) - self.last_commit_at).days


@dataclass
class OpenPullRequest:
    """One open pull request I opened - mid-flight work (#15). PRs opened by
    someone else in a repo I own are excluded before this type is ever built -
    see `GitHub.open_pull_requests`.
    """

    number: int
    title: str
    created_at: datetime
    draft: bool

    @property
    def age_days(self) -> int:
        return (datetime.now(tz=self.created_at.tzinfo) - self.created_at).days


@dataclass
class TreeListing:
    """One repo's full file listing (#18), from a single
    `GET /repos/{owner}/{repo}/git/trees/{default}?recursive=1` request.

    ``paths`` are every blob/tree path GitHub returned, forward-slash
    separated, in whatever order the API gave them - callers filter/search,
    they do not rely on ordering. ``truncated`` mirrors GitHub's own
    `truncated` field: true when the tree was too large for one response and
    is *not* a complete listing - a caller must then treat "not found in
    `paths`" as unknown, never as "missing" (see `health.judge_health`).
    """

    paths: list[str]
    truncated: bool


@dataclass
class NewRepo:
    """One repo created during the reported week - a start, not a finish (#33).

    A callout, not an achievement: it shows up regardless of how strong the
    repo's first week was, and regardless of whether the repo is a tracked
    project - see `new_repos.new_repos_this_week`.
    """

    name: str
    created_at: datetime
    commits: int


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
