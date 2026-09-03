"""Time-to-decision (#32, D31 in docs/decisions.md): weeks-silent before a drop.

For every project dropped in the requested year, how many silent weeks passed
between its last stored commit and the week the drop was recorded - the number
that says how slow the drop decision was. Pure stdlib + dataclasses, no Django
import, no LLM, no network - see the services layering and determinism rules
in AGENTS.md.

`weeks_silent` for each dropped project is computed by the caller
(`portfolio/services/year.py`, D31 point 3) via `stalled.weeks_since_last_commit`
reused verbatim, anchored at the drop week instead of "now" - nothing here
recomputes that arithmetic. This module holds only the pure aggregation step
(the median) and the `DroppedRow` dataclass the per-project number lives on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median


@dataclass
class DroppedRow:
    """One dropped project ending inside the requested year, plus its weeks-silent number.

    `weeks_silent` is `None` when no stored `RepoWeek` row carries a commit at
    or before the drop week - rendered as "no commit history," never a number
    (the issue's own AC, and #31's existing convention for the same case).
    `0` means a commit was stored for the drop week itself: dropping something
    you were still committing to that same week is a decision, not a delay.
    """

    repo: str
    end_date: datetime
    weeks_silent: int | None


def median_weeks_silent(dropped: list[DroppedRow]) -> float | None:
    """Median `weeks_silent` across `dropped`, or `None` when nothing qualifies.

    Drop-while-active rows (`weeks_silent == 0`) are included - a fast,
    decisive drop is a real data point about decisiveness, not noise to
    filter out. Rows with no commit history (`weeks_silent is None`) are
    excluded - they contribute no numeric "how long did I wait" answer, the
    same way they are excluded from any other numeric average. `None` is
    returned (never `0` or another placeholder) when no dropped row has a
    numeric answer - zero dropped projects, or every drop has no history.

    An even count of qualifying values averages the two middle ones, which
    can produce a `.5` value - returned as-is, no rounding invented to force
    an integer (D31 point 4).
    """
    values = [row.weeks_silent for row in dropped if row.weeks_silent is not None]
    if not values:
        return None
    return median(values)
