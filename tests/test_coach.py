"""`portfolio.coach` - the OpenAI-compatible client builder (#24).

Every test here is offline. `build_client` is exercised against a small fake
settings object (never `django.conf.settings` directly, so these tests never
depend on - or risk touching - whatever is in this machine's real `.env`),
and `CoachClient.chat_completion` is exercised against `httpx.MockTransport`
fakes, the same pattern `tests/test_github.py` uses for `GitHub`. No test in
this file makes, or could make, a real network call to Groq, OpenAI, or any
other endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from portfolio.coach import (
    CoachClient,
    CoachConfigError,
    CoachRequestError,
    build_client,
)


def fake_settings(**overrides):
    base = {
        "LLM_BASE_URL": "https://llm.example.invalid/v1",
        "LLM_MODEL": "fake-model",
        "LLM_API_KEY": "fake-key",
        "LLM_TIMEOUT_SECONDS": 5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# --- missing key -------------------------------------------------------------


def test_missing_api_key_raises_before_any_network_attempt():
    settings = fake_settings(LLM_API_KEY="")

    with pytest.raises(CoachConfigError) as exc_info:
        build_client(settings)

    assert "LLM_API_KEY" in str(exc_info.value)


def test_missing_api_key_error_names_the_setting_not_a_value():
    # There is no key value to leak when it's missing - this just confirms
    # the error text is about the setting, never a stray key-shaped string.
    settings = fake_settings(LLM_API_KEY="")

    with pytest.raises(CoachConfigError) as exc_info:
        build_client(settings)

    message = str(exc_info.value)
    assert "gsk_" not in message  # no accidental key-like content


# --- provider swap by env (settings) only, no code change --------------------


def test_provider_swap_by_settings_only_picks_up_base_url_and_model():
    groq_like = fake_settings(
        LLM_BASE_URL="https://api.groq.com/openai/v1",
        LLM_MODEL="llama-3.3-70b-versatile",
        LLM_API_KEY="key-a",
    )
    other_provider = fake_settings(
        LLM_BASE_URL="https://llm.other-provider.invalid/v1",
        LLM_MODEL="some-other-model",
        LLM_API_KEY="key-b",
    )

    client_a = build_client(groq_like)
    client_b = build_client(other_provider)

    try:
        assert str(client_a._http.base_url) == "https://api.groq.com/openai/v1/"
        assert client_a.model == "llama-3.3-70b-versatile"

        assert str(client_b._http.base_url) == "https://llm.other-provider.invalid/v1/"
        assert client_b.model == "some-other-model"
    finally:
        client_a.close()
        client_b.close()


def test_client_carries_configured_timeout():
    settings = fake_settings(LLM_TIMEOUT_SECONDS=3)

    client = build_client(settings)
    try:
        assert client._http.timeout.connect == 3
    finally:
        client.close()


def test_client_uses_hardcoded_default_timeout_when_unset():
    settings = fake_settings()
    del settings.LLM_TIMEOUT_SECONDS

    client = build_client(settings)
    try:
        assert client._http.timeout.connect == 10
    finally:
        client.close()


def test_api_key_sent_as_bearer_header_never_logged_or_echoed():
    settings = fake_settings(LLM_API_KEY="super-secret-key")

    client = build_client(settings)
    try:
        assert client._http.headers["Authorization"] == "Bearer super-secret-key"
    finally:
        client.close()


def test_github_settings_are_never_read_by_build_client():
    settings = fake_settings()
    settings.GITHUB_TOKEN = "should-never-be-touched"
    settings.GITHUB_USER = "should-never-be-touched"

    client = build_client(settings)
    try:
        assert "should-never-be-touched" not in str(client._http.headers)
        assert "should-never-be-touched" not in str(client._http.base_url)
    finally:
        client.close()


# --- chat_completion: retry policy, against a fake transport -----------------


def make_client(handler, *, model="fake-model") -> CoachClient:
    http_client = httpx.Client(
        base_url="https://llm.example.invalid/v1",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer fake-key"},
    )
    return CoachClient(model=model, http_client=http_client)


def test_chat_completion_succeeds_on_first_try():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = make_client(handler)
    try:
        result = client.chat_completion([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    assert len(calls) == 1
    assert result["choices"][0]["message"]["content"] == "ok"


def test_chat_completion_retries_on_429_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"choices": []})

    client = make_client(handler)
    try:
        result = client.chat_completion([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    assert len(calls) == 2
    assert result == {"choices": []}


def test_chat_completion_retries_on_5xx_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"choices": []})

    client = make_client(handler)
    try:
        result = client.chat_completion([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    assert len(calls) == 3
    assert result == {"choices": []}


def test_chat_completion_retry_is_bounded_then_raises():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, text="always down")

    client = make_client(handler)
    try:
        with pytest.raises(CoachRequestError):
            client.chat_completion([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    # First attempt plus MAX_RETRIES (2) further attempts, never unbounded.
    assert len(calls) == 3


def test_chat_completion_does_not_retry_non_429_4xx():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, text="bad request")

    client = make_client(handler)
    try:
        with pytest.raises(CoachRequestError):
            client.chat_completion([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    assert len(calls) == 1


def test_chat_completion_error_never_includes_the_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    http_client = httpx.Client(
        base_url="https://llm.example.invalid/v1",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer super-secret-key"},
    )
    client = CoachClient(model="fake-model", http_client=http_client)
    try:
        with pytest.raises(CoachRequestError) as exc_info:
            client.chat_completion([{"role": "user", "content": "hi"}])
    finally:
        client.close()

    assert "super-secret-key" not in str(exc_info.value)


def test_chat_completion_retries_on_connection_error_then_raises_coach_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler)
    try:
        with pytest.raises(CoachRequestError):
            client.chat_completion([{"role": "user", "content": "hi"}])
    finally:
        client.close()
