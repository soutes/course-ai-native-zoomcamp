"""Week-over-week momentum delta text (#21).

Pure stdlib + dataclasses, no Django import, no LLM - see the services
layering rule in AGENTS.md. Reading the previous week's stored `RepoWeek`
row is a separate, Django-aware step in
`portfolio/services/repoweek_lookup.py` (D19 in docs/decisions.md),
following the same pure/Django-aware split `stalled_lookup.py` already
established for #14.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PreviousMomentum:
    """The previous week's five stored momentum numbers for one repo.

    Built from a `RepoWeek` row by `repoweek_lookup.py` - plain ints here,
    not the model, so this module stays Django-free. There is no
    ``partial`` field: #21's AC only requires that a partial previous row's
    lines/files deltas are not suppressed, which this module already does
    for every previous row unconditionally (nothing here special-cases
    ``partial`` at all - that flag has no bearing on which numbers are
    shown, only on whether the *current* week's own row is caveated, which
    `render.py` already handles separately).
    """

    commits: int
    active_days: int
    lines_added: int
    lines_removed: int
    files_touched: int


def format_delta(previous: int | None) -> str:
    """``"(last week: N)"`` for a stored previous value, ``"(first week
    tracked)"`` for no previous row (``previous is None``) - kept distinct
    per #21's AC: absent and zero are different facts.

    No styling: a drop renders exactly like a rise (#21's AC) - this only
    ever states the previous number as plain text, never a colored or
    symbol-decorated diff.
    """
    if previous is None:
        return "(first week tracked)"
    return f"(last week: {previous})"


@dataclass
class MomentumDeltaText:
    """The five ready-to-render delta strings for one repo's momentum line."""

    commits: str
    active_days: str
    lines_added: str
    lines_removed: str
    files_touched: str


def momentum_delta_text(previous: PreviousMomentum | None) -> MomentumDeltaText:
    """Build the five delta strings for one repo from `previous` (or `None`
    when the repo has no stored `RepoWeek` row for the previous week - every
    field then reads ``"(first week tracked)"``, not ``"(last week: 0)"``).
    """
    if previous is None:
        first = format_delta(None)
        return MomentumDeltaText(
            commits=first,
            active_days=first,
            lines_added=first,
            lines_removed=first,
            files_touched=first,
        )
    return MomentumDeltaText(
        commits=format_delta(previous.commits),
        active_days=format_delta(previous.active_days),
        lines_added=format_delta(previous.lines_added),
        lines_removed=format_delta(previous.lines_removed),
        files_touched=format_delta(previous.files_touched),
    )
