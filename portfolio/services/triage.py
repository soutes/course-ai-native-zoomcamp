"""Portfolio curation. Deterministic, no LLM.

The sorting question is not "alive or dead" - it is "does this repo help me or hurt
me in an interview". A finished course repo with a README is an asset even after a
year of silence. A three-commit tutorial fork is noise that dilutes the good ones.
"""

from __future__ import annotations

from .types import Decision, Repo, TriagePlan, Verdict


def classify(repo: Repo, min_commits: int) -> Decision:
    reasons: list[str] = []

    if repo.private:
        return Decision(repo, Verdict.SKIP, ["already private"])

    # A fork I never committed to is not my work at all.
    if repo.fork and repo.commits == 0:
        return Decision(repo, Verdict.DELETE, ["fork with no commits of my own"])

    if repo.has_readme and repo.commits >= min_commits:
        polish = _polish_hints(repo)
        reasons.append(f"{repo.commits} commits")
        reasons.append("README")
        if repo.has_release:
            reasons.append("released")
        return Decision(repo, Verdict.SHOWCASE, reasons, polish)

    if not repo.has_readme:
        reasons.append("no README")
    if repo.commits < min_commits:
        reasons.append(f"only {repo.commits} commits")
    if repo.fork:
        reasons.append("fork")
    return Decision(repo, Verdict.HIDE, reasons)


def _polish_hints(repo: Repo) -> list[str]:
    """Small gaps that cost a recruiter's attention on a repo worth keeping."""
    hints: list[str] = []
    if not repo.description:
        hints.append("no description")
    if not repo.topics:
        hints.append("no topics")
    if not repo.license:
        hints.append("no license")
    return hints


def build_plan(repos: list[Repo], min_commits: int) -> TriagePlan:
    decisions = [classify(r, min_commits) for r in repos]
    # Newest push first inside each pile: the ones I still remember come first.
    decisions.sort(key=lambda d: d.repo.pushed_at, reverse=True)
    return TriagePlan(decisions)
