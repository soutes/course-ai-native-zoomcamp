"""`portfolio.coach.build_batched_request`/`send_batched_request` (#25).

One batched prompt for the whole portfolio, built only from
`WeeklyReportData`/`RepoReportData` - never a diff, never a secret, never a
project's goal text (D24). Every test here is offline: `send_batched_request`
is only ever exercised against `httpx.MockTransport` fakes, the same pattern
`tests/test_coach.py` (#24) already uses. No test in this file makes, or
could make, a real network call to any LLM endpoint.
"""

from __future__ import annotations

import json

import httpx

from portfolio.coach import (
    MAX_COMMIT_SUBJECTS_PER_REPO,
    CoachClient,
    build_batched_request,
    send_batched_request,
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


def eight_repo_report() -> WeeklyReportData:
    repos = []
    for i in range(8):
        silent = i == 3
        repos.append(
            make_repo(
                repo=f"me/repo-{i}",
                commits=0 if silent else i + 1,
                commit_subjects=[] if silent else [f"repo{i} commit {n}" for n in range(i + 1)],
                lines_added=0 if silent else 10 * i,
                lines_removed=0 if silent else 2 * i,
                files_touched=0 if silent else i,
                weeks_since_last_commit=3 if silent else 0,
            )
        )
    return WeeklyReportData(week="2026-W35", repos=repos)


# --- shape of the built messages ---------------------------------------------------


def test_returns_one_system_and_one_user_message():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])

    messages = build_batched_request(report)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_system_message_says_advice_about_behavior_not_code():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])

    messages = build_batched_request(report)

    system_text = messages[0]["content"].lower()
    assert "behavior" in system_text
    assert "not" in system_text and "code" in system_text
    assert "no access" in system_text or "do not have access" in system_text


def test_repo_name_and_diffstat_numbers_appear_in_prompt():
    repo = make_repo(repo="me/widgets", lines_added=123, lines_removed=45, files_touched=7)
    report = WeeklyReportData(week="2026-W35", repos=[repo])

    content = build_batched_request(report)[1]["content"]

    assert "me/widgets" in content
    assert "123" in content
    assert "45" in content
    assert "7" in content


def test_commit_subjects_appear_in_prompt():
    repo = make_repo(commit_subjects=["fix the flaky test", "wire up the router"])
    report = WeeklyReportData(week="2026-W35", repos=[repo])

    content = build_batched_request(report)[1]["content"]

    assert "fix the flaky test" in content
    assert "wire up the router" in content


# --- silent repos ---------------------------------------------------------------


def test_silent_repo_is_included_and_marked_silent_not_dropped():
    silent = make_repo(repo="me/quiet", commits=0, commit_subjects=[])
    active = make_repo(repo="me/loud", commits=5)
    report = WeeklyReportData(week="2026-W35", repos=[silent, active])

    content = build_batched_request(report)[1]["content"]

    assert "me/quiet" in content
    assert "me/loud" in content
    # The silent repo's own block (from its "### name" heading to the next
    # heading or end of text) says so - repos are sorted alphabetically, so
    # this does not assume which repo's block comes first.
    quiet_block = content.split("### me/quiet", 1)[1].split("### ")[0]
    assert "silent this week: yes" in quiet_block


def test_active_repo_marked_not_silent():
    active = make_repo(repo="me/loud", commits=5, commit_subjects=["a", "b"])
    report = WeeklyReportData(week="2026-W35", repos=[active])

    content = build_batched_request(report)[1]["content"]

    assert "silent this week: no" in content


# --- commit subject cap -----------------------------------------------------------


def test_subjects_capped_at_module_constant():
    assert MAX_COMMIT_SUBJECTS_PER_REPO == 40


def test_200_commit_repo_does_not_blow_the_prompt():
    subjects = [f"commit number {n}" for n in range(200)]
    repo = make_repo(repo="me/busy", commits=200, commit_subjects=subjects)
    report = WeeklyReportData(week="2026-W35", repos=[repo])

    content = build_batched_request(report)[1]["content"]

    kept_subjects = [line for line in content.splitlines() if line.startswith("- commit number")]
    assert len(kept_subjects) == MAX_COMMIT_SUBJECTS_PER_REPO


def test_truncation_drops_oldest_first_and_keeps_most_recent():
    subjects = [f"commit {n}" for n in range(50)]  # chronological, oldest first
    repo = make_repo(repo="me/busy", commits=50, commit_subjects=subjects)
    report = WeeklyReportData(week="2026-W35", repos=[repo])

    content = build_batched_request(report)[1]["content"]

    # The 10 oldest (0-9) are omitted; the most recent 40 (10-49) survive.
    assert "commit 0\n" not in content
    assert "- commit 9" not in content
    assert "- commit 10" in content
    assert "- commit 49" in content


def test_truncation_count_is_stated_in_the_prompt():
    subjects = [f"commit {n}" for n in range(50)]
    repo = make_repo(repo="me/busy", commits=50, commit_subjects=subjects)
    report = WeeklyReportData(week="2026-W35", repos=[repo])

    content = build_batched_request(report)[1]["content"]

    assert "10 oldest omitted" in content


def test_no_truncation_note_when_under_the_cap():
    repo = make_repo(commit_subjects=["one", "two"])
    report = WeeklyReportData(week="2026-W35", repos=[repo])

    content = build_batched_request(report)[1]["content"]

    assert "omitted" not in content


# --- never diffs, never secrets, never goal text -----------------------------------


def test_no_diff_hunk_markers_anywhere_in_the_prompt():
    report = eight_repo_report()

    messages = build_batched_request(report)

    full_text = json.dumps(messages)
    assert "@@" not in full_text
    assert "+++" not in full_text


def test_no_secrets_in_the_prompt():
    report = eight_repo_report()

    messages = build_batched_request(report)

    full_text = json.dumps(messages)
    assert "GITHUB_TOKEN" not in full_text
    assert "LLM_API_KEY" not in full_text
    assert "ghp_" not in full_text
    assert "fake-key" not in full_text


def test_goal_text_is_sent_only_when_set():
    # D28: goal text is sent only for a repo that has one - not for a repo
    # with an empty/unset goal.
    with_goal = make_repo(repo="me/withgoal", commit_subjects=["a"])
    with_goal.goal = "Ship a working v1."
    without_goal = make_repo(repo="me/nogoal", commit_subjects=["b"])
    report = WeeklyReportData(week="2026-W35", repos=[with_goal, without_goal])

    content = build_batched_request(report)[1]["content"]

    with_block = content.split("### me/withgoal", 1)[1].split("### ")[0]
    without_block = content.split("### me/nogoal", 1)[1].split("### ")[0]
    assert "goal: Ship a working v1." in with_block
    assert "goal:" not in without_block


# --- exactly one HTTP request over an 8-repo fixture --------------------------------


def test_batched_request_over_eight_repos_makes_exactly_one_http_call():
    report = eight_repo_report()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "advice"}}]})

    client = make_client(handler)
    try:
        result = send_batched_request(client, report)
    finally:
        client.close()

    assert len(calls) == 1
    assert result == {"choices": [{"message": {"content": "advice"}}]}


def test_all_eight_repos_appear_in_the_single_request_body():
    report = eight_repo_report()
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": []})

    client = make_client(handler)
    try:
        send_batched_request(client, report)
    finally:
        client.close()

    body_text = json.dumps(captured["body"])
    for i in range(8):
        assert f"me/repo-{i}" in body_text


def test_calling_chat_completion_directly_with_built_messages_is_also_one_call():
    report = eight_repo_report()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": []})

    client = make_client(handler)
    try:
        messages = build_batched_request(report)
        client.chat_completion(messages)
    finally:
        client.close()

    assert len(calls) == 1


# --- raw, unparsed response is returned as-is ---------------------------------------


def test_return_value_is_the_raw_unparsed_response():
    report = WeeklyReportData(week="2026-W35", repos=[make_repo()])
    raw_payload = {"choices": [{"message": {"content": "raw advice"}}], "id": "abc123"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=raw_payload)

    client = make_client(handler)
    try:
        result = send_batched_request(client, report)
    finally:
        client.close()

    assert result == raw_payload
