"""`portfolio.services.health.judge_health` (#18) - pure, no Django, no network.

Covers all five signals, tree-truncation-as-unknown, empty-default-branch,
CI/tests pattern matching, and the healthy-repo-no-noise case.
"""

from __future__ import annotations

from datetime import UTC, datetime

from portfolio.services.health import judge_health
from portfolio.services.types import Repo, TreeListing


def make_repo(**overrides) -> Repo:
    defaults = dict(
        name="demo",
        full_name="me/demo",
        html_url="https://github.com/me/demo",
        private=False,
        fork=False,
        archived=False,
        description="a project",
        topics=[],
        license="MIT",
        default_branch="main",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        pushed_at=datetime(2026, 1, 1, tzinfo=UTC),
        stars=0,
        forks=0,
    )
    defaults.update(overrides)
    return Repo(**defaults)


def tree(paths, truncated=False) -> TreeListing:
    return TreeListing(paths=paths, truncated=truncated)


# --- a fully healthy repo produces no gaps --------------------------------------------


def test_healthy_repo_has_no_missing_signals():
    repo = make_repo(license="MIT", description="does a thing")
    t = tree(["README.md", "tests/test_thing.py", ".github/workflows/ci.yml", "src/thing.py"])

    signals = judge_health(t, repo)

    assert signals.healthy
    assert signals.missing_labels == []


# --- README ------------------------------------------------------------------------


def test_readme_missing_when_no_readme_file_at_root():
    signals = judge_health(tree(["src/main.py"]), make_repo())
    assert signals.missing_readme is True


def test_readme_detected_case_insensitively():
    signals = judge_health(tree(["ReadMe.MD"]), make_repo())
    assert signals.missing_readme is False


def test_readme_detected_extensionless():
    signals = judge_health(tree(["README"]), make_repo())
    assert signals.missing_readme is False


def test_readme_detected_rst():
    signals = judge_health(tree(["readme.rst"]), make_repo())
    assert signals.missing_readme is False


def test_readme_not_detected_when_not_at_repo_root():
    signals = judge_health(tree(["docs/README.md"]), make_repo())
    assert signals.missing_readme is True


# --- tests -------------------------------------------------------------------------


def test_tests_detected_via_tests_directory():
    signals = judge_health(tree(["tests/test_foo.py"]), make_repo())
    assert signals.missing_tests is False


def test_tests_detected_via_test_directory_singular():
    signals = judge_health(tree(["test/foo_test.py"]), make_repo())
    assert signals.missing_tests is False


def test_tests_detected_via_test_prefixed_file_at_root():
    signals = judge_health(tree(["test_foo.py"]), make_repo())
    assert signals.missing_tests is False


def test_tests_detected_via_test_suffixed_file():
    signals = judge_health(tree(["foo_test.py"]), make_repo())
    assert signals.missing_tests is False


def test_tests_missing_when_none_of_the_patterns_match():
    signals = judge_health(tree(["src/main.py", "docs/notes.md"]), make_repo())
    assert signals.missing_tests is True


# --- CI ------------------------------------------------------------------------------


def test_ci_detected_from_a_workflow_file():
    signals = judge_health(tree([".github/workflows/ci.yml"]), make_repo())
    assert signals.missing_ci is False


def test_ci_missing_when_workflows_dir_absent():
    signals = judge_health(tree(["src/main.py"]), make_repo())
    assert signals.missing_ci is True


def test_ci_missing_when_workflows_dir_present_but_empty():
    """The directory entry alone, with nothing inside it, does not count."""
    signals = judge_health(tree([".github/workflows"]), make_repo())
    assert signals.missing_ci is True


# --- license / description come from Repo, not the tree (D15) ----------------------


def test_license_and_description_come_from_repo_fields_not_the_tree():
    repo = make_repo(license=None, description=None)
    # A LICENSE file present in the tree must not satisfy the license signal (D15) -
    # only `Repo.license` (GitHub's own SPDX detection) does.
    signals = judge_health(tree(["LICENSE", "README.md"]), repo)

    assert signals.missing_license is True
    assert signals.missing_description is True


def test_license_and_description_present_when_repo_fields_are_set():
    repo = make_repo(license="Apache-2.0", description="does a thing")
    signals = judge_health(tree([]), repo)

    assert signals.missing_license is False
    assert signals.missing_description is False


# --- truncated tree -> unknown, not missing -----------------------------------------


def test_truncated_tree_marks_readme_tests_ci_unknown_not_missing():
    signals = judge_health(tree(["src/a.py"], truncated=True), make_repo())

    assert signals.missing_readme is None
    assert signals.missing_tests is None
    assert signals.missing_ci is None
    assert signals.tree_truncated is True


def test_truncated_tree_produces_no_noise_when_license_and_description_are_set():
    """Unknown signals from truncation are never reported as missing - a repo
    that is otherwise fine produces no `missing_labels` noise."""
    repo = make_repo(license="MIT", description="does a thing")
    signals = judge_health(tree(["src/a.py"], truncated=True), repo)

    assert signals.missing_labels == []
    assert signals.healthy


def test_truncated_tree_still_reports_missing_license_or_description():
    repo = make_repo(license=None, description=None)
    signals = judge_health(tree(["src/a.py"], truncated=True), repo)

    assert signals.missing_labels == ["license", "description"]


# --- empty default branch: all signals missing, not a raise ------------------------


def test_empty_default_branch_reports_all_five_signals_missing():
    """`GitHub.tree` turns an empty default branch into an empty, non-truncated
    listing (see test_github.py) - this must read as "all signals missing",
    never raise."""
    repo = make_repo(license=None, description=None)

    signals = judge_health(tree([], truncated=False), repo)

    assert signals.missing_readme is True
    assert signals.missing_tests is True
    assert signals.missing_ci is True
    assert signals.missing_license is True
    assert signals.missing_description is True
    assert signals.missing_labels == ["README", "tests", "CI", "license", "description"]
