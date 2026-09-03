"""ISO week window helper, tested from pure inputs. No network, no database.

See docs/decisions.md for why 2026-W53 is not used as the "no such week" case:
2026's Jan 1 falls on a Thursday, so 2026 actually has 53 ISO weeks - the issue's
claim that "2026 has 52 weeks" does not hold. 2025 and 2027 do have 52 weeks and
are used instead; a comment was left on issue #11 about the discrepancy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from portfolio.services.week import week_label, week_window


def test_week_window_2026_w36():
    start, end = week_window("2026-W36", tz=UTC)
    assert start == datetime(2026, 8, 31, 0, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 6, 23, 59, 59, 999999, tzinfo=UTC)


def test_no_argument_returns_todays_iso_week():
    tz = UTC
    now = datetime.now(tz)
    start, end = week_window(tz=tz)
    assert start <= now <= end
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert (end - start) == timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)


def test_w01_resolves_across_a_year_boundary():
    # 2026's Jan 1 is a Thursday, so ISO week 1 of 2026 starts in late Dec 2025.
    start, end = week_window("2026-W01", tz=UTC)
    assert start == datetime(2025, 12, 29, 0, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 1, 4, 23, 59, 59, 999999, tzinfo=UTC)
    # And the label helper reports it back as belonging to 2026, not 2025.
    assert week_label((start, end)) == "2026-W01"


def test_w53_raises_for_a_52_week_year():
    # 2025 has 52 ISO weeks (Jan 1 2025 is a Wednesday, not a leap year).
    with pytest.raises(ValueError, match="2025-W53"):
        week_window("2025-W53", tz=UTC)


def test_w53_resolves_for_a_53_week_year():
    start, end = week_window("2020-W53", tz=UTC)
    assert start.isocalendar()[:2] == (2020, 53)
    assert week_label((start, end)) == "2020-W53"


@pytest.mark.parametrize("bad", ["2026-36", "W36", "2026-W0", ""])
def test_malformed_labels_raise_value_error_naming_the_input(bad):
    with pytest.raises(ValueError) as exc_info:
        week_window(bad, tz=UTC)
    assert repr(bad) in str(exc_info.value)


def test_none_raises_value_error():
    with pytest.raises(ValueError) as exc_info:
        week_window(None, tz=UTC)
    assert repr(None) in str(exc_info.value)


def test_week_label_round_trips():
    for label in ["2026-W36", "2026-W01", "2020-W53", "2025-W52"]:
        assert week_label(week_window(label, tz=UTC)) == label


def test_default_tz_is_local_when_omitted():
    start, _end = week_window("2026-W36")
    assert start.tzinfo is not None
    # No tz passed: falls back to the system's local zone, not UTC-naive.
    assert start.utcoffset() is not None


def test_explicit_tzinfo_is_honoured():
    tz = ZoneInfo("America/Sao_Paulo")
    start, end = week_window("2026-W36", tz=tz)
    assert start.tzinfo is tz
    assert end.tzinfo is tz
