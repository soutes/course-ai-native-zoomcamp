"""Deterministic "did this project ship?" detection (#20, D18 in docs/decisions.md).

Three signals, judged from data `report`'s per-project loop already fetches (or
now fetches for this purpose, per D18) - no Django, no LLM, no network of its
own (AGENTS.md's layering rule: this is a pure function over plain values,
same shape as `health.py`). When more than one signal fires for the same repo
in the same run, the reason names only the first to fire, in this priority
order: release, then tag, then README.

`AUTO_PREFIX` marks every reason this module writes, so a caller (`report`'s
reactivation pass, in particular) can tell an auto-detected transition apart
from one a human typed via `ack --shipped` - explicit human state must always
win over inference (#20's own constraint, D18's provenance convention).
"""

from __future__ import annotations

import re

AUTO_PREFIX = "Auto-detected: "

_SEMVER_TAG_RE = re.compile(r"^v?\d+\.\d+(\.\d+)?$")
_MD_STRIP_CHARS = "#*_-`"
_STATUS_COMPLETE = "status: complete"


def shipped_tag(tags: list[str]) -> str | None:
    """The first tag matching `^v?\\d+\\.\\d+(\\.\\d+)?$` (optional leading `v`,
    major.minor with an optional patch) - `v1.0`, `v1.2.0`, `2.0`. Anything
    with a suffix after the numeric part (`v1.0.0-rc1`, `v2.0-beta`) fails the
    pattern and never counts: a pre-release tag signals "not yet final", the
    opposite of shipped. `None` when nothing in `tags` qualifies.
    """
    for tag in tags:
        if _SEMVER_TAG_RE.match(tag):
            return tag
    return None


def _normalize_line(line: str) -> str:
    """Strip markdown wrapping (`#`, `*`, `_`, `-`, backticks, whitespace)
    from a README line's ends, leaving whatever plain text remains."""
    return line.strip().strip(_MD_STRIP_CHARS).strip()


def readme_says_complete(text: str | None) -> bool:
    """True when some line of `text`, once markdown-stripped, is *exactly*
    "status: complete" (case-insensitive) - not a substring search, so
    `Status: Complete, tests pending` does not match (it is not exactly
    "complete"), and neither does `Status: In Progress` or `Status: WIP`.
    """
    if not text:
        return False
    return any(_normalize_line(line).lower() == _STATUS_COMPLETE for line in text.splitlines())


def detect_shipped(*, has_release: bool, tags: list[str], readme_text: str | None) -> str | None:
    """The `"Auto-detected: ..."` reason for the first signal to fire, in
    priority order release > tag > README (D18) - or `None` if none fired.

    Callers pass `GitHub.has_release`, `GitHub.tags`, `GitHub.readme_text` for
    one repo; this function makes no GitHub call of its own.
    """
    if has_release:
        return f"{AUTO_PREFIX}released"

    tag = shipped_tag(tags)
    if tag:
        return f"{AUTO_PREFIX}tag {tag}"

    if readme_says_complete(readme_text):
        return f"{AUTO_PREFIX}README says Status: Complete"

    return None
