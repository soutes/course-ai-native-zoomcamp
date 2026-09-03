"""`portfolio.services.shipped` (#20) - pure, deterministic, no Django, no network."""

from __future__ import annotations

from portfolio.services.shipped import (
    AUTO_PREFIX,
    detect_shipped,
    readme_says_complete,
    shipped_tag,
)

# --- shipped_tag ---------------------------------------------------------------------


def test_v_prefixed_semver_tag_matches():
    assert shipped_tag(["v1.0"]) == "v1.0"


def test_bare_semver_tag_matches():
    assert shipped_tag(["1.0"]) == "1.0"


def test_semver_with_patch_matches():
    assert shipped_tag(["v1.2.0"]) == "v1.2.0"


def test_prerelease_rc_tag_does_not_match():
    assert shipped_tag(["v1.0.0-rc1"]) is None


def test_prerelease_beta_tag_does_not_match():
    assert shipped_tag(["v2.0-beta"]) is None


def test_non_semver_tag_does_not_match():
    assert shipped_tag(["release-candidate", "latest"]) is None


def test_first_matching_tag_in_list_order_wins():
    assert shipped_tag(["not-a-tag", "v1.0.0-rc1", "v1.0", "v2.0"]) == "v1.0"


def test_empty_tag_list_returns_none():
    assert shipped_tag([]) is None


# --- readme_says_complete --------------------------------------------------------------


def test_plain_status_complete_line_matches():
    assert readme_says_complete("Status: Complete") is True


def test_matching_is_case_insensitive():
    assert readme_says_complete("STATUS: complete") is True


def test_matches_one_line_among_others():
    assert readme_says_complete("# My Project\n\nStatus: Complete\n\nMore text.") is True


def test_markdown_heading_wrapping_is_stripped():
    assert readme_says_complete("## Status: Complete") is True


def test_bold_wrapping_is_stripped():
    assert readme_says_complete("**Status: Complete**") is True


def test_backtick_wrapping_is_stripped():
    assert readme_says_complete("`Status: Complete`") is True


def test_bullet_wrapping_is_stripped():
    assert readme_says_complete("- Status: Complete") is True


def test_trailing_extra_text_is_not_a_match():
    assert readme_says_complete("Status: Complete, tests pending") is False


def test_in_progress_does_not_match():
    assert readme_says_complete("Status: In Progress") is False


def test_wip_does_not_match():
    assert readme_says_complete("Status: WIP") is False


def test_none_text_does_not_match():
    assert readme_says_complete(None) is False


def test_empty_text_does_not_match():
    assert readme_says_complete("") is False


# --- detect_shipped: priority order -----------------------------------------------------


def test_release_wins_when_all_three_signals_fire():
    reason = detect_shipped(has_release=True, tags=["v1.0"], readme_text="Status: Complete")
    assert reason == f"{AUTO_PREFIX}released"


def test_tag_wins_over_readme_when_no_release():
    reason = detect_shipped(has_release=False, tags=["v1.2.0"], readme_text="Status: Complete")
    assert reason == f"{AUTO_PREFIX}tag v1.2.0"


def test_readme_fires_when_neither_release_nor_tag():
    reason = detect_shipped(has_release=False, tags=[], readme_text="Status: Complete")
    assert reason == f"{AUTO_PREFIX}README says Status: Complete"


def test_prerelease_tag_alone_does_not_fall_through_to_tag_signal():
    reason = detect_shipped(has_release=False, tags=["v1.0.0-rc1"], readme_text=None)
    assert reason is None


def test_nothing_fires_returns_none():
    assert detect_shipped(has_release=False, tags=[], readme_text=None) is None


def test_every_reason_carries_the_auto_prefix():
    assert detect_shipped(has_release=True, tags=[], readme_text=None).startswith(AUTO_PREFIX)
