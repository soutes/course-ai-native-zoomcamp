"""`portfolio.coach.get_coaching`/`CoachingResult` (#26, docs/decisions.md D25).

Every test here is offline: `get_coaching` is only ever exercised against
`httpx.MockTransport` fakes, the same pattern `tests/test_coach.py` (#24) and
`tests/test_coach_batched_request.py` (#25) already use. No test in this file makes,
or could make, a real network call to any LLM endpoint.
"""

from __future__ import annotations

import json

import httpx

from portfolio.coach import (
    MAX_ADVICE_CHARS,
    CoachClient,
    CoachingResult,
    get_coaching,
)
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


# --- valid response: every sent repo gets advice ------------------------------------


def test_valid_response_puts_every_repo_in_advice():
    report = WeeklyReportData(
        week="2026-W35",
        repos=[make_repo(repo="me/alpha"), make_repo(repo="me/beta")],
    )
    payload = json.dumps(
        {"advice": {"me/alpha": "Ship the small thing first.", "me/beta": "Keep it up."}}
    )

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert isinstance(result, CoachingResult)
    assert result.advice == {
        "me/alpha": "Ship the small thing first.",
        "me/beta": "Keep it up.",
    }
    assert result.unavailable == []


# --- total failure: malformed/truncated JSON -> None, same as --no-llm --------------


def test_malformed_json_is_total_failure_returns_none():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])
    # Truncated/invalid JSON.
    client = make_client(lambda request: json_response('{"me/demo": "unterminated'))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result is None


def test_non_object_json_is_total_failure_returns_none():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])
    client = make_client(lambda request: json_response(json.dumps(["not", "an", "object"])))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result is None


def test_missing_content_is_total_failure_returns_none():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])
    client = make_client(lambda request: httpx.Response(200, json={"choices": []}))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result is None


def test_network_error_is_total_failure_returns_none():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler)
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result is None


def test_non_retryable_http_error_is_total_failure_returns_none():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])
    client = make_client(lambda request: httpx.Response(400, text="bad request"))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result is None


# --- missing key for one repo: that repo unavailable, others keep advice ------------


def test_missing_key_for_one_repo_degrades_only_that_repo():
    report = WeeklyReportData(
        week="2026-W35",
        repos=[make_repo(repo="me/alpha"), make_repo(repo="me/beta")],
    )
    payload = json.dumps({"advice": {"me/alpha": "Ship the small thing first."}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {"me/alpha": "Ship the small thing first."}
    assert result.unavailable == ["me/beta"]


# --- unknown repo key: dropped, never in either list ---------------------------------


def test_unknown_repo_key_is_dropped_silently():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    payload = json.dumps(
        {"advice": {"me/alpha": "Ship the small thing first.", "me/never-sent": "bogus advice"}}
    )

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {"me/alpha": "Ship the small thing first."}
    assert "me/never-sent" not in result.advice
    assert "me/never-sent" not in result.unavailable
    assert result.unavailable == []


# --- markdown-fenced JSON is recovered -----------------------------------------------


def test_json_fence_is_stripped_and_recovered():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    fenced = (
        "```json\n" + json.dumps({"advice": {"me/alpha": "Ship the small thing first."}}) + "\n```"
    )

    client = make_client(lambda request: json_response(fenced))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {"me/alpha": "Ship the small thing first."}


def test_bare_fence_without_json_language_tag_is_also_recovered():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    fenced = "```\n" + json.dumps({"advice": {"me/alpha": "Ship the small thing first."}}) + "\n```"

    client = make_client(lambda request: json_response(fenced))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {"me/alpha": "Ship the small thing first."}


# --- empty-string / whitespace-only value treated as missing ------------------------


def test_empty_string_value_is_treated_as_unavailable():
    report = WeeklyReportData(
        week="2026-W35",
        repos=[make_repo(repo="me/alpha"), make_repo(repo="me/beta")],
    )
    payload = json.dumps({"advice": {"me/alpha": "", "me/beta": "Keep it up."}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {"me/beta": "Keep it up."}
    assert result.unavailable == ["me/alpha"]


def test_whitespace_only_value_is_treated_as_unavailable():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    payload = json.dumps({"advice": {"me/alpha": "   \n\t  "}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {}
    assert result.unavailable == ["me/alpha"]


def test_non_string_value_is_treated_as_unavailable():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    payload = json.dumps({"advice": {"me/alpha": 42}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice == {}
    assert result.unavailable == ["me/alpha"]


# --- truncation cap -------------------------------------------------------------------


def test_advice_longer_than_cap_is_truncated_with_marker():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    long_advice = "x" * (MAX_ADVICE_CHARS + 200)
    payload = json.dumps({"advice": {"me/alpha": long_advice}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert "me/alpha" in result.advice
    assert result.advice["me/alpha"].startswith("x" * 10)
    assert result.advice["me/alpha"].endswith("truncated]")
    # Truncated to MAX_ADVICE_CHARS plus the marker; escaping the marker's own
    # brackets (rich.markup.escape) adds a couple of backslashes on top of that.
    assert len(result.advice["me/alpha"]) <= MAX_ADVICE_CHARS + len("... [truncated]") + 4


def test_advice_at_or_under_cap_is_not_truncated():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    advice = "y" * MAX_ADVICE_CHARS
    payload = json.dumps({"advice": {"me/alpha": advice}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    assert result.advice["me/alpha"] == advice
    assert "truncated" not in result.advice["me/alpha"]


# --- every sent repo lands in exactly one of advice/unavailable ---------------------


def test_every_sent_repo_lands_in_exactly_one_bucket():
    report = WeeklyReportData(
        week="2026-W35",
        repos=[make_repo(repo="me/alpha"), make_repo(repo="me/beta"), make_repo(repo="me/gamma")],
    )
    payload = json.dumps({"advice": {"me/alpha": "good advice", "me/gamma": ""}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    all_repos = {"me/alpha", "me/beta", "me/gamma"}
    seen = set(result.advice) | set(result.unavailable)
    assert seen == all_repos
    assert set(result.advice) & set(result.unavailable) == set()


# --- model output is escaped, never rendered as raw Rich console markup -------------


def test_advice_containing_bracket_markup_is_escaped():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo(repo="me/alpha")])
    payload = json.dumps({"advice": {"me/alpha": "Try [bold red]this[/bold red] approach."}})

    client = make_client(lambda request: json_response(payload))
    try:
        result = get_coaching(report, client)
    finally:
        client.close()

    advice_text = result.advice["me/alpha"]
    # rich.markup.escape backslash-escapes the brackets so Rich's console markup
    # parser (used elsewhere in render.py, e.g. render_changes) never treats model
    # output as a style directive.
    assert "\\[bold red]" in advice_text
    assert "\\[/bold red]" in advice_text


# --- no real network call is ever made -----------------------------------------------


def test_get_coaching_never_makes_a_real_network_call():
    """Sanity check that the fake transport is what's exercised, not a real socket.

    `httpx.MockTransport` never opens a socket - the handler above is the entire
    "network." This test documents the invariant the whole file relies on.
    """
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert isinstance(client._http._transport, httpx.MockTransport)
        return json_response(json.dumps({"advice": {"me/demo": "advice"}}))

    client = make_client(handler)
    try:
        get_coaching(report, client)
    finally:
        client.close()

    assert len(calls) == 1
