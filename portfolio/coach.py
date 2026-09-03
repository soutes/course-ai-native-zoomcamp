"""OpenAI-compatible chat-completions client (#24).

This is the only module in the app that constructs an LLM client or imports
an LLM/HTTP-to-LLM dependency - `portfolio/services/` imports no Django and
no LLM (`AGENTS.md`, Layering). It lives here, not under `portfolio/services/`,
for exactly that reason.

It talks to "an OpenAI-compatible endpoint" - never to a named vendor. No
vendor name, vendor SDK or vendor-specific branch appears anywhere in this
file. `settings.LLM_BASE_URL` happens to default to Groq's endpoint
(`config/settings.py`, `docs/decisions.md` D23) - this module does not know
or care what that default resolves to.

This issue is the client only: no prompt is built here and nothing in this
app calls `CoachClient.chat_completion` yet. The retry/timeout machinery on
that method exists because #24's acceptance criteria require a bounded
timeout and a bounded retry policy to exist on the client itself; #25 builds
the prompt that will eventually be sent through it, #26 parses the response.

#25 adds `build_batched_request`/`send_batched_request` below: the prompt
builder for the whole portfolio in one request, per `AGENTS.md` ("One
batched LLM call per report, never one per repo") and `docs/decisions.md`
D24 (commit subjects and diffstat numbers only - never full diffs, never a
project's goal text). It reads only `portfolio.services.render.
WeeklyReportData`/`RepoReportData`, already built by the deterministic
layers - nothing is re-fetched and no new GitHub/database call is made
here.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx
from django.conf import settings as django_settings

if TYPE_CHECKING:
    from portfolio.services.render import RepoReportData, WeeklyReportData

# SPEC.md section 4b: "~40 commit subjects per project." Commits beyond this
# cap are dropped oldest-first (the most recent subjects are the most
# useful signal); the prompt states how many were omitted for that repo so
# the model is never misled about how much actually happened.
MAX_COMMIT_SUBJECTS_PER_REPO = 40

# Status codes worth retrying: 429 (rate limited) and 5xx (server-side
# hiccup). A 4xx that is not 429 (bad request, unauthorized, not found, ...)
# means the request or the key is wrong - retrying changes nothing.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Bounded: at most this many *extra* attempts after the first one, so a
# persistently failing endpoint fails in finite time instead of retrying
# forever.
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.5


class CoachConfigError(RuntimeError):
    """The coach client could not be built from the current configuration."""


class CoachRequestError(RuntimeError):
    """The LLM endpoint could not be reached, or returned a non-retryable error.

    Never includes the API key - only the status code and attempt count.
    """


class CoachClient:
    """A small OpenAI-compatible chat-completions client.

    Wraps an `httpx.Client` pre-configured with the base URL, bearer auth and
    a bounded timeout. `model` travels alongside for a future caller (#25) to
    put in the request body - this class never inspects or branches on its
    value.
    """

    def __init__(self, *, model: str, http_client: httpx.Client) -> None:
        self.model = model
        self._http = http_client

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> CoachClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        """POST to the chat-completions endpoint, with a bounded retry.

        Retries (up to `MAX_RETRIES` further attempts) on a connection/network
        error or a 429/5xx response - the cases where trying again is likely
        to help. A 4xx that is not 429 (bad request, unauthorized, ...) is
        never retried and raises immediately: the request or the key is
        wrong, and another attempt will not change that.
        """
        body: dict[str, Any] = {"model": self.model, "messages": messages, **kwargs}
        attempt = 0
        last_exc: httpx.HTTPError | None = None

        while attempt <= MAX_RETRIES:
            try:
                response = self._http.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    raise CoachRequestError(
                        f"Network error calling the LLM endpoint after "
                        f"{attempt + 1} attempt(s): {exc.__class__.__name__}"
                    ) from exc
                attempt += 1
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                attempt += 1
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

            if response.status_code >= 400:
                raise CoachRequestError(
                    f"LLM endpoint returned {response.status_code} after {attempt + 1} attempt(s)."
                )

            return response.json()

        # Unreachable - the loop above always returns or raises - kept so
        # the function has an explicit terminal case rather than falling
        # off the end.
        raise CoachRequestError("LLM request failed.") from last_exc


def build_client(settings: Any = None) -> CoachClient:
    """Build a `CoachClient` from `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`.

    Reads configuration from `django.conf.settings` by default (or from the
    `settings` object passed in, for tests) - never from `os.environ`
    directly, and never `GITHUB_TOKEN`/`GITHUB_USER`.

    Raises `CoachConfigError`, naming the missing setting, before any network
    attempt when `LLM_API_KEY` is unset - there is nothing to authenticate
    with, so building a client that would only fail on first use is worse
    than failing here.
    """
    cfg = settings if settings is not None else django_settings

    api_key = getattr(cfg, "LLM_API_KEY", "") or ""
    if not api_key:
        raise CoachConfigError(
            "LLM_API_KEY is not set. Set it in the environment (see .env.example) "
            "before building the coach client."
        )

    base_url = getattr(cfg, "LLM_BASE_URL", "") or ""
    model = getattr(cfg, "LLM_MODEL", "") or ""
    timeout_seconds = float(getattr(cfg, "LLM_TIMEOUT_SECONDS", 10))

    http_client = httpx.Client(
        base_url=base_url,
        timeout=timeout_seconds,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    return CoachClient(model=model, http_client=http_client)


# --- batched portfolio prompt (#25) -------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a coach reviewing one person's weekly portfolio of side projects. "
    "You are given, for every tracked repo this week: whether it was silent "
    "(zero commits), a list of this week's commit subjects, and diffstat "
    "numbers (lines added, lines removed, files touched). You do not have "
    "access to the codebase, any file, or any diff - only what is listed "
    "below. Give advice about behavior, not code: talk about patterns like "
    "starting a project before finishing another, going silent on one repo "
    "while another gets all the attention, or working in short bursts versus "
    "a steady rhythm. Never suggest a code change, a refactor, or comment on "
    "implementation details you cannot see."
)


def _repo_prompt_lines(repo: RepoReportData) -> list[str]:
    """One repo's block of prompt text, built only from a `RepoReportData`.

    Carries the repo name, the silent flag, commit subjects (capped at
    `MAX_COMMIT_SUBJECTS_PER_REPO`, oldest dropped first, with a note of how
    many were omitted), and diffstat numbers. Never a diff, never a file's
    content, never `repo.description` or any goal text (D24) - only fields
    this function reads below.
    """
    lines = [f"### {repo.repo}"]
    lines.append(f"silent this week: {'yes' if repo.commits == 0 else 'no'}")
    lines.append(f"commits: {repo.commits}")
    lines.append(
        f"diffstat: +{repo.lines_added}/-{repo.lines_removed} lines across "
        f"{repo.files_touched} file(s) touched"
    )

    subjects = repo.commit_subjects
    total = len(subjects)
    if total > MAX_COMMIT_SUBJECTS_PER_REPO:
        omitted = total - MAX_COMMIT_SUBJECTS_PER_REPO
        # Oldest truncated first: subjects are chronological (oldest first,
        # per RepoReportData's own docstring), so keep the most recent
        # MAX_COMMIT_SUBJECTS_PER_REPO and drop the earliest ones.
        kept = subjects[-MAX_COMMIT_SUBJECTS_PER_REPO:]
        lines.append(
            f"commit subjects ({MAX_COMMIT_SUBJECTS_PER_REPO} of {total} shown, "
            f"{omitted} oldest omitted):"
        )
    else:
        kept = subjects
        lines.append(f"commit subjects ({total}):")

    if kept:
        lines.extend(f"- {subject}" for subject in kept)
    else:
        lines.append("- (none)")

    return lines


def build_batched_request(report: WeeklyReportData) -> list[dict[str, str]]:
    """Build one `messages` list for the whole portfolio from `report`.

    One call site, not a loop - every tracked repo (silent ones included,
    marked silent, never dropped) is folded into a single user message, so
    `CoachClient.chat_completion(build_batched_request(report))` makes
    exactly one HTTP request per report (`AGENTS.md`, D24). Built entirely
    from `WeeklyReportData`/`RepoReportData` fields already computed by the
    deterministic layers - nothing is re-fetched, no GitHub call, no
    database query. Never includes a full diff, file content, a secret
    (`GITHUB_TOKEN`/`LLM_API_KEY`), or a project's goal text (`RepoReportData`
    has no `goal` field - D24).

    Returns the `messages` list only; sending it through
    `CoachClient.chat_completion` and returning that call's raw, unparsed
    response is `send_batched_request`'s job below - parsing/validating the
    response is #26's, not this function's.
    """
    repos = sorted(report.repos, key=lambda r: r.repo)

    user_lines = [f"# Weekly portfolio - {report.week}", ""]
    if not repos:
        user_lines.append("No tracked repos this week.")
    else:
        for repo in repos:
            user_lines.extend(_repo_prompt_lines(repo))
            user_lines.append("")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines).rstrip()},
    ]


def send_batched_request(client: CoachClient, report: WeeklyReportData) -> dict[str, Any]:
    """Build the portfolio prompt from `report` and send it through `client`.

    Exactly one `CoachClient.chat_completion` call - the batched request is
    `build_batched_request(report)`'s output, sent as-is. Returns
    `chat_completion`'s raw, unparsed response; this function does not
    inspect, validate, or shape it (#26's job).
    """
    messages = build_batched_request(report)
    return client.chat_completion(messages)
