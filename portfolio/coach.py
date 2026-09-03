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

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from django.conf import settings as django_settings
from rich.markup import escape as escape_markup

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
    "numbers (lines added, lines removed, files touched). Some repos also "
    "carry a stated goal - one sentence describing what finishing that "
    "project looks like. You do not have access to the codebase, any file, "
    "or any diff - only what is listed below. Give advice about behavior, "
    "not code: talk about patterns like starting a project before finishing "
    "another, going silent on one repo while another gets all the "
    "attention, or working in short bursts versus a steady rhythm. Never "
    "suggest a code change, a refactor, or comment on implementation "
    "details you cannot see. Phrase each repo's advice as something to do "
    "in the coming week, not a recap of the week that just ended.\n\n"
    "For every repo that has a stated goal AND had at least one commit "
    "this week, also judge whether this week's commits moved toward that "
    "goal - a drift verdict. Skip drift entirely (no verdict, not even a "
    "'no drift' one) for a repo with no stated goal, or a repo with zero "
    "commits this week - those are not yours to judge. Judge the work "
    "against the goal, never the person: never phrase a verdict as a "
    "judgement of effort or character. Every verdict must cite at least "
    "one of this week's commit subjects as evidence, so it can be checked. "
    "Either confirm briefly that the commits moved toward the goal, or call "
    "out drift by naming the goal and what the commits were about instead.\n\n"
    "Return your answer as a single JSON object with exactly two top-level "
    'keys: "advice", an object mapping each repo name to its advice '
    'string, and "drift", an object mapping each goal-and-commits-eligible '
    "repo name to its drift verdict string. Return no other text."
)


def _repo_prompt_lines(repo: RepoReportData) -> list[str]:
    """One repo's block of prompt text, built only from a `RepoReportData`.

    Carries the repo name, the silent flag, commit subjects (capped at
    `MAX_COMMIT_SUBJECTS_PER_REPO`, oldest dropped first, with a note of how
    many were omitted), diffstat numbers, and - only when `repo.goal` is
    non-empty - a `goal: {text}` line (#29, D28; D24 named #29 as the one
    issue allowed to send goal text). Never a diff, never a file's content,
    never `repo.description` - only fields this function reads below.
    """
    lines = [f"### {repo.repo}"]
    lines.append(f"silent this week: {'yes' if repo.commits == 0 else 'no'}")
    lines.append(f"commits: {repo.commits}")
    lines.append(
        f"diffstat: +{repo.lines_added}/-{repo.lines_removed} lines across "
        f"{repo.files_touched} file(s) touched"
    )
    if repo.goal:
        lines.append(f"goal: {repo.goal}")

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

    A repo's goal text (`RepoReportData.goal`) is included via
    `_repo_prompt_lines` only when that repo has one set (#29, D28) - D24
    named #29 as the one issue allowed to extend this call to send it.

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


# --- response parsing and CoachingResult (#26, docs/decisions.md D25) --------------

# Any advice string longer than this is truncated (with a trailing marker) before
# being stored - never a named-nowhere magic number, matching
# `MAX_COMMIT_SUBJECTS_PER_REPO`'s pattern above.
MAX_ADVICE_CHARS = 500

_TRUNCATION_MARKER = "... [truncated]"


@dataclass
class CoachingResult:
    """The parsed, per-repo outcome of one batched coaching request (D25, extended by
    #29/D28).

    Every repo in the `WeeklyReportData.repos` that was sent lands in exactly one of
    `advice` (a usable, capped, escaped advice string) or `unavailable` (sent, but no
    usable advice came back for it) - never silently absent from both. A repo name
    that appears in the model's response but was never sent is dropped, not added to
    either collection.

    `drift`/`drift_unavailable` mirror that same shape for the goal-drift verdict
    (#29, D28), but only for the subset of repos that were *eligible* for drift
    judgement - sent with both a non-empty `RepoReportData.goal` and `commits > 0`.
    A repo with no goal, or zero commits, is skipped silently and appears in
    neither list (that is #14's/D28's job, not a drift outcome). An eligible repo
    with a missing/malformed verdict lands in `drift_unavailable`, independent of
    whether that same repo's `advice` resolved successfully.
    """

    advice: dict[str, str] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)
    drift: dict[str, str] = field(default_factory=dict)
    drift_unavailable: list[str] = field(default_factory=list)


def _strip_markdown_fence(text: str) -> str:
    """Strip one leading/trailing markdown code fence (```` ```json ```` or ```` ``` ````).

    Only a single fence wrapping the whole content is recognized - if present, the
    fence lines themselves are dropped and the text between them is returned for
    `json.loads`. Content with no fence is returned unchanged.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parsed_advice_object(response: dict[str, Any]) -> dict[str, Any] | None:
    """Recover the top-level `{"advice": {...}, "drift": {...}}` object (D28) from a
    raw response.

    Returns `None` (total failure, per D25) when `choices[0].message.content` is
    missing/not a string, when the content is not valid JSON after fence-stripping,
    or when it parses to something other than a JSON object (e.g. a bare array or
    string) - `json.loads` succeeding is not enough on its own. This function only
    recovers the outer object; `get_coaching` reads `"advice"`/`"drift"` off it.
    """
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None

    if not isinstance(content, str):
        return None

    try:
        parsed = json.loads(_strip_markdown_fence(content))
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    return parsed


def _clean_and_escape(value: object, unavailable: list[str], repo_name: str) -> str | None:
    """Shared per-repo cleanup for one advice/drift value (D25 point 4, reused by D28).

    Returns the stripped, capped, escaped string on success. On any failure - not a
    string, or empty/whitespace-only after stripping - appends `repo_name` to
    `unavailable` and returns `None`. Identical handling for `advice` and `drift`, so
    a malformed value in one never affects the other's outcome for the same repo.
    """
    if not isinstance(value, str):
        unavailable.append(repo_name)
        return None

    cleaned = value.strip()
    if not cleaned:
        unavailable.append(repo_name)
        return None

    if len(cleaned) > MAX_ADVICE_CHARS:
        cleaned = cleaned[:MAX_ADVICE_CHARS].rstrip() + _TRUNCATION_MARKER

    return escape_markup(cleaned)


def get_coaching(report: WeeklyReportData, client: CoachClient) -> CoachingResult | None:
    """Get per-repo coaching advice and goal-drift verdicts for `report`, or `None` on
    any failure.

    Calls `send_batched_request(client, report)` itself (#26 is the first issue to
    actually invoke it against real report data). Never raises: `CoachRequestError`
    and any other exception `chat_completion`/`send_batched_request` can raise are
    caught here and resolve to `None` - identical to what `--no-llm` (#27) already
    produces, per AGENTS.md's determinism rule and D25.

    A response that fails to parse as the expected top-level JSON object (missing
    content, non-JSON, fenced-but-still-broken, or valid JSON that is not an object)
    is a total failure and returns `None`. Once parsed, `parsed.get("advice", {})`
    and `parsed.get("drift", {})` are read independently (#29, D28) - a response
    missing either key entirely degrades that key's whole bucket to empty, exactly
    as D25/D26 already specified for the pre-#29 flat shape (every sent repo lands
    in `unavailable`, or every eligible repo in `drift_unavailable`).

    Every repo in `report.repos` is resolved individually for `advice`/`unavailable`:
    a missing key, or a value that is not a non-empty string, puts that repo in
    `unavailable`; everything else is stripped, truncated to `MAX_ADVICE_CHARS`,
    escaped the same way `render.py` escapes other GitHub-sourced text
    (`rich.markup.escape`), and stored in `advice`. A key naming a repo that was
    never sent is dropped silently.

    Drift is resolved only for repos *eligible* for judgement - `repo.goal` non-empty
    and `repo.commits > 0` (#29, D28) - using the identical clean/cap/escape rule via
    `_clean_and_escape`, landing in `drift`/`drift_unavailable`. An ineligible repo
    (no goal, or zero commits) is skipped silently: it appears in neither `drift` nor
    `drift_unavailable`, matching the "skipped silently, never reported as drifting"
    ACs. A malformed drift value for one repo never touches that repo's own `advice`
    outcome, or any other repo's `advice`/`drift` outcome - each is computed
    independently from its own key lookup.
    """
    try:
        response = send_batched_request(client, report)
    except Exception:
        return None

    parsed = _parsed_advice_object(response)
    if parsed is None:
        return None

    advice_obj = parsed.get("advice")
    if not isinstance(advice_obj, dict):
        advice_obj = {}
    drift_obj = parsed.get("drift")
    if not isinstance(drift_obj, dict):
        drift_obj = {}

    advice: dict[str, str] = {}
    unavailable: list[str] = []
    drift: dict[str, str] = {}
    drift_unavailable: list[str] = []

    for repo in sorted(report.repos, key=lambda r: r.repo):
        cleaned = _clean_and_escape(advice_obj.get(repo.repo), unavailable, repo.repo)
        if cleaned is not None:
            advice[repo.repo] = cleaned

        if not repo.goal or repo.commits == 0:
            continue

        cleaned_drift = _clean_and_escape(drift_obj.get(repo.repo), drift_unavailable, repo.repo)
        if cleaned_drift is not None:
            drift[repo.repo] = cleaned_drift

    return CoachingResult(
        advice=advice, unavailable=unavailable, drift=drift, drift_unavailable=drift_unavailable
    )
