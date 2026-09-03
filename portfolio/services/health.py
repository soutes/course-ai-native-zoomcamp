"""Deterministic per-repo health signals (#18, D15 in docs/decisions.md).

Judges five signals from data already fetched elsewhere - no Django, no LLM,
no network of its own (AGENTS.md's layering rule: this is a pure function
over plain values). Three of the five (README, tests-directory, CI-config)
come from a repo's file tree (`GitHub.tree`, one cached
`git/trees/{default}?recursive=1` request); the other two (license,
description) reuse `Repo.license`/`Repo.description`, already populated by
`GitHub.my_repos()` - D15 explains why those two cannot and should not come
from the tree.

This is new, separate logic - it does not replace or touch
`GitHub.has_readme()` or triage's classifier (#4); see D15's "cost accepted".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .types import Repo, TreeListing

_README_RE = re.compile(r"^readme(\.(md|rst))?$", re.IGNORECASE)
_CI_PREFIX = ".github/workflows/"
_TEST_DIR_NAMES = {"tests", "test"}
_TEST_FILE_RE = re.compile(r"^(test_.+\.py|.+_test\.py)$", re.IGNORECASE)


@dataclass
class HealthSignals:
    """One repo's health verdict.

    ``missing_readme``/``missing_tests``/``missing_ci`` are tri-state: `True`
    (missing), `False` (present) or `None` - the tree response was truncated,
    so this signal is unknown, not missing (#18's AC). ``missing_license``/
    ``missing_description`` are always a plain `bool` - they never depend on
    the tree, so truncation cannot affect them (D15).
    """

    missing_readme: bool | None
    missing_tests: bool | None
    missing_ci: bool | None
    missing_license: bool
    missing_description: bool
    tree_truncated: bool = False

    @property
    def missing_labels(self) -> list[str]:
        """Human-readable names of the signals definitively missing.

        A `None` (unknown, from a truncated tree) signal is never reported as
        missing - it is not evidence of a gap, only of an incomplete read.
        """
        labels = []
        if self.missing_readme:
            labels.append("README")
        if self.missing_tests:
            labels.append("tests")
        if self.missing_ci:
            labels.append("CI")
        if self.missing_license:
            labels.append("license")
        if self.missing_description:
            labels.append("description")
        return labels

    @property
    def healthy(self) -> bool:
        """True when every signal is known-present. A repo with an unknown
        (truncated) signal is not asserted healthy, but also produces no
        "missing" noise - see `missing_labels`."""
        return not self.missing_labels


def _has_readme(paths: list[str]) -> bool:
    """A README at repo root, case-insensitive, `.md`/`.rst`/extensionless."""
    return any("/" not in p and _README_RE.match(p) for p in paths)


def _has_ci(paths: list[str]) -> bool:
    """A workflow file under `.github/workflows/` - the directory alone,
    with nothing inside it, does not count."""
    return any(p.startswith(_CI_PREFIX) and len(p) > len(_CI_PREFIX) for p in paths)


def _has_tests(paths: list[str]) -> bool:
    """`tests/`, `test/` (anywhere in the tree, not just at root),
    `test_*.py` or `*_test.py`."""
    for p in paths:
        segments = p.split("/")
        if any(seg.lower() in _TEST_DIR_NAMES for seg in segments):
            return True
        if _TEST_FILE_RE.match(segments[-1]):
            return True
    return False


def judge_health(tree: TreeListing, repo: Repo) -> HealthSignals:
    """The five signals for one repo.

    ``tree`` must be this repo's own listing (`GitHub.tree(repo.full_name,
    repo.default_branch)`); ``repo`` supplies `license`/`description`
    straight from its already-fetched fields (D15) - no extra request.

    A repo with an empty default branch (no commits) naturally falls out of
    this without special-casing: `GitHub.tree` returns an empty, non-truncated
    listing for that case, so README/tests/CI all read as missing here, same
    as license/description would if unset - "all signals missing", never a
    raise (#18's AC).
    """
    if tree.truncated:
        missing_readme = missing_tests = missing_ci = None
    else:
        missing_readme = not _has_readme(tree.paths)
        missing_tests = not _has_tests(tree.paths)
        missing_ci = not _has_ci(tree.paths)

    return HealthSignals(
        missing_readme=missing_readme,
        missing_tests=missing_tests,
        missing_ci=missing_ci,
        missing_license=not repo.license,
        missing_description=not repo.description,
        tree_truncated=tree.truncated,
    )
