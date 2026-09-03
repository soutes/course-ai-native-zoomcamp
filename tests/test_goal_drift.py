"""`portfolio.coach.get_coaching`'s goal-drift extension (#29, docs/decisions.md D28).

Every test here is offline: `get_coaching` is only ever exercised against
`httpx.MockTransport` fakes, the same pattern `tests/test_coach_get_coaching.py`
(#26) already uses. No test in this file makes, or could make, a real network
call to any LLM endpoint.
"""

from __future__ import annotations

import json

import httpx

from portfolio.coach import CoachClient, CoachingResult, get_coaching
from portfolio.services.render import RepoReportData, WeeklyReportData


def make_repo(**overrides) -> RepoReportData:
    defaults = dict(
        repo="me/demo",
        commits=5,
        active_days=3,
        lines_added=40,
        lines_removed=10,
        files_touched=6,
        partial=False,
        weeks_since_last_commit=0,
        stalled=False,
        commit_subjects=["fix bug", "add feature", "update docs"],
    )
    defaults.update(overrides)
    return RepoReportData(**defaults)


def make_client(handler, *, model="fake-model") -> CoachClient:
    http_client = httpx.Client(
        base_url="https://llm.example.invalid/v1",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer fake-key"},
    )
    return CoachClient(model=model, http_client=http_client)


def json_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


# --- goal set, commits > 0: resolved into drift ---------------------------------------


def test_goal_and_commits_resolves_into_drift():
    repo = make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)
    report = WeeklyReportData(week="2026-W35", repos=[repo])
    payload = json.dumps(
        {
            "advice": {"me/alpha": "Keep it steady."},
            "drift": {"me/alpha": 'On track - see "fix bug".'},
        }
    )

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.drift == {"me/alpha": 'On track - see "fix bug".'}
    assert result.drift_unavailable == []
    assert result.advice == {"me/alpha": "Keep it steady."}


# --- no goal set: skipped silently, never in drift or drift_unavailable ---------------


def test_no_goal_set_is_skipped_silently():
    repo = make_repo(repo="me/alpha", goal="", commits=5)
    report = WeeklyReportData(week="2026-W35", repos=[repo])
    # Even if the model returns a drift verdict for it anyway, it must not appear.
    payload = json.dumps(
        {"advice": {"me/alpha": "Keep it steady."}, "drift": {"me/alpha": "bogus verdict"}}
    )

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.drift == {}
    assert result.drift_unavailable == []
    assert result.advice == {"me/alpha": "Keep it steady."}


# --- zero commits, goal set: skipped silently (that is #14's stalling, not drift) -----


def test_zero_commits_with_goal_is_skipped_silently():
    repo = make_repo(repo="me/alpha", goal="Ship a v1.", commits=0, commit_subjects=[])
    report = WeeklyReportData(week="2026-W35", repos=[repo])
    payload = json.dumps(
        {"advice": {"me/alpha": "Get moving."}, "drift": {"me/alpha": "bogus verdict"}}
    )

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.drift == {}
    assert result.drift_unavailable == []


# --- malformed drift for one repo: only that repo's drift is affected -----------------


def test_malformed_drift_for_one_repo_does_not_affect_other_repos_advice_or_drift():
    alpha = make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)
    beta = make_repo(repo="me/beta", goal="Ship a v2.", commits=3)
    report = WeeklyReportData(week="2026-W35", repos=[alpha, beta])
    payload = json.dumps(
        {
            "advice": {"me/alpha": "Keep going.", "me/beta": "Nice work."},
            "drift": {"me/beta": "On track."},  # me/alpha's drift key is missing
        }
    )

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    # me/alpha: advice unaffected by its own missing drift key.
    assert result.advice["me/alpha"] == "Keep going."
    assert result.drift_unavailable == ["me/alpha"]
    assert "me/alpha" not in result.drift

    # me/beta: unaffected by me/alpha's malformed drift.
    assert result.advice["me/beta"] == "Nice work."
    assert result.drift["me/beta"] == "On track."


def test_malformed_drift_value_type_is_unavailable_advice_still_resolves():
    repo = make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)
    report = WeeklyReportData(week="2026-W35", repos=[repo])
    payload = json.dumps({"advice": {"me/alpha": "Keep going."}, "drift": {"me/alpha": 42}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {"me/alpha": "Keep going."}
    assert result.drift == {}
    assert result.drift_unavailable == ["me/alpha"]


def test_response_missing_drift_key_entirely_puts_every_eligible_repo_in_unavailable():
    alpha = make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)
    beta = make_repo(repo="me/beta", goal="", commits=5)  # no goal: not eligible
    report = WeeklyReportData(week="2026-W35", repos=[alpha, beta])
    payload = json.dumps({"advice": {"me/alpha": "Keep going.", "me/beta": "Nice work."}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.drift == {}
    assert result.drift_unavailable == ["me/alpha"]  # me/beta never eligible
    assert result.advice == {"me/alpha": "Keep going.", "me/beta": "Nice work."}


# --- exactly one HTTP request; same response parsed for both advice and drift ---------


def test_one_request_carries_both_advice_and_drift():
    alpha = make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)
    report = WeeklyReportData(week="2026-W35", repos=[alpha])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = json.dumps(
            {"advice": {"me/alpha": "Keep going."}, "drift": {"me/alpha": "On track."}}
        )
        return json_response(payload)

    client = make_client(handler)
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert len(calls) == 1
    assert result.advice == {"me/alpha": "Keep going."}
    assert result.drift == {"me/alpha": "On track."}


# --- every eligible repo lands in exactly one of drift/drift_unavailable --------------


def test_every_eligible_repo_lands_in_exactly_one_drift_bucket():
    alpha = make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)
    beta = make_repo(repo="me/beta", goal="Ship a v2.", commits=2)
    gamma = make_repo(repo="me/gamma", goal="", commits=5)  # not eligible: no goal
    delta = make_repo(repo="me/delta", goal="Ship a v3.", commits=0)  # not eligible: silent
    report = WeeklyReportData(week="2026-W35", repos=[alpha, beta, gamma, delta])
    payload = json.dumps({"advice": {}, "drift": {"me/alpha": "On track."}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    seen = set(result.drift) | set(result.drift_unavailable)
    assert seen == {"me/alpha", "me/beta"}
    assert "me/gamma" not in seen
    assert "me/delta" not in seen
    assert set(result.drift) & set(result.drift_unavailable) == set()


# --- backward compat: pre-#29 flat advice-only shape still an advice-object failure ---


def test_old_flat_shape_response_has_no_advice_key_so_every_repo_is_unavailable():
    # Pre-#29, the whole object *was* the advice map. Post-#29, get_coaching only
    # reads "advice"/"drift" sub-keys - a flat {repo: text} object at the top level
    # has no "advice" key, so it degrades to every repo unavailable (D28 point 2).
    repo = make_repo(repo="me/alpha")
    report = WeeklyReportData(week="2026-W35", repos=[repo])
    payload = json.dumps({"me/alpha": "old-style flat advice"})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {}
    assert result.unavailable == ["me/alpha"]


def test_get_coaching_never_makes_a_real_network_call():
    """Sanity check that the fake transport is what's exercised, not a real socket."""
    repo = make_repo(repo="me/alpha", goal="Ship a v1.", commits=5)
    report = WeeklyReportData(week="2026-W35", repos=[repo])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert isinstance(client._http._transport, httpx.MockTransport)
        payload = json.dumps({"advice": {"me/alpha": "advice"}, "drift": {"me/alpha": "verdict"}})
        return json_response(payload)

    client = make_client(handler)
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert len(calls) == 1
    assert isinstance(result, CoachingResult)
