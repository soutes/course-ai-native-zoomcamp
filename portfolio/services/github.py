"""GitHub REST client. The only module that touches the network.

Deliberately small: list my repos, count commits, check for a README and a release.
Commit counting uses the `Link: rel="last"` header trick so one request per repo is
enough instead of paginating through every commit.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from .cache import Cache
from .types import Commit, Repo

API = "https://api.github.com"
LAST_PAGE = re.compile(r'[?&]page=(\d+)>;\s*rel="last"')


class GitHubError(RuntimeError):
    """A GitHub call failed in a way the user needs to know about."""


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHub:
    def __init__(self, token: str, cache: Cache) -> None:
        self.cache = cache
        self.client = httpx.Client(
            base_url=API,
            timeout=30.0,
            follow_redirects=True,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "weekly-cli",
            },
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> GitHub:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- low level -----------------------------------------------------------

    def _get(self, path: str, **params: Any) -> httpx.Response:
        try:
            r = self.client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise GitHubError(f"Network error calling {path}: {exc}") from exc

        if r.status_code == 401:
            raise GitHubError("GitHub rejected the token (401). Is it valid and unexpired?")
        if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubError("GitHub rate limit exhausted. Try again later.")
        return r

    def _cached_json(self, path: str, **params: Any) -> Any:
        key = f"GET {path} {sorted(params.items())}"
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        r = self._get(path, **params)
        if r.status_code >= 400:
            raise GitHubError(f"GET {path} failed: {r.status_code} {r.text[:200]}")
        data = r.json()
        self.cache.set(key, data)
        return data

    # --- calls used by triage ------------------------------------------------

    def my_repos(self) -> Iterator[Repo]:
        """Every repo I own. Paginated, cached page by page."""
        page = 1
        while True:
            batch = self._cached_json(
                "/user/repos",
                affiliation="owner",
                sort="pushed",
                direction="desc",
                per_page=100,
                page=page,
            )
            if not batch:
                return
            for raw in batch:
                yield self._to_repo(raw)
            if len(batch) < 100:
                return
            page += 1

    @staticmethod
    def _to_repo(raw: dict[str, Any]) -> Repo:
        license_info = raw.get("license") or {}
        return Repo(
            name=raw["name"],
            full_name=raw["full_name"],
            html_url=raw["html_url"],
            private=raw["private"],
            fork=raw["fork"],
            archived=raw["archived"],
            description=raw.get("description"),
            topics=list(raw.get("topics") or []),
            license=license_info.get("spdx_id"),
            default_branch=raw.get("default_branch") or "main",
            created_at=_parse_dt(raw["created_at"]),
            pushed_at=_parse_dt(raw["pushed_at"] or raw["created_at"]),
            stars=raw.get("stargazers_count", 0),
            forks=raw.get("forks_count", 0),
        )

    def commit_count(self, full_name: str, author: str | None = None) -> int:
        """Total commits, via the pagination Link header. One request."""
        key = f"COMMITS {full_name} {author}"
        hit = self.cache.get(key)
        if hit is not None:
            return int(hit)

        params: dict[str, Any] = {"per_page": 1}
        if author:
            params["author"] = author
        r = self._get(f"/repos/{full_name}/commits", **params)

        if r.status_code == 409:  # empty repository
            count = 0
        elif r.status_code >= 400:
            count = 0
        else:
            link = r.headers.get("Link", "")
            match = LAST_PAGE.search(link)
            count = int(match.group(1)) if match else len(r.json())

        self.cache.set(key, count)
        return count

    def commits_in_window(
        self,
        full_name: str,
        window: tuple[datetime, datetime],
        emails: list[str],
    ) -> list[Commit]:
        """Commits *I* authored in `window` - see docs/decisions.md D1.

        `window` is the local-time ``(start, end)`` tuple #11's `week_window` returns;
        converted here to UTC ISO-8601 for `since`/`until`. No server-side `author=`
        filter is sent - every commit in the window comes back and is matched here,
        client-side, against `emails` (`commit.author.email`, case-insensitive), since
        GitHub, work and `noreply` addresses differ across machines.

        Merge commits (more than one parent) are excluded so a merge does not inflate
        a quiet week. Results are deduped by sha, so a commit I authored but someone
        else committed (rebase, merge) is counted once. A repo with zero commits in
        the window, or an empty repo (GitHub answers 409), returns an empty list.
        Paginated to the end - a week with more than 100 commits returns them all.
        """
        start, end = window
        since = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        wanted = {e.strip().lower() for e in emails if e.strip()}

        commits: dict[str, Commit] = {}
        page = 1
        while True:
            batch = self._cached_json_allow_409(
                f"/repos/{full_name}/commits",
                since=since,
                until=until,
                per_page=100,
                page=page,
            )
            if not batch:
                break

            for raw in batch:
                if len(raw.get("parents") or []) > 1:
                    continue  # merge commit
                author_email = ((raw.get("commit") or {}).get("author") or {}).get("email", "")
                if author_email.strip().lower() not in wanted:
                    continue
                sha = raw["sha"]
                if sha in commits:
                    continue
                commits[sha] = self._to_commit(raw)

            if len(batch) < 100:
                break
            page += 1

        return list(commits.values())

    @staticmethod
    def _to_commit(raw: dict[str, Any]) -> Commit:
        commit = raw["commit"]
        subject = commit["message"].splitlines()[0] if commit.get("message") else ""
        return Commit(
            sha=raw["sha"],
            authored_at=_parse_dt(commit["author"]["date"]),
            subject=subject,
        )

    def _cached_json_allow_409(self, path: str, **params: Any) -> Any:
        """Like `_cached_json`, but a 409 (empty repository) is an empty list,
        not an error - the commits endpoint answers 409 for repos with no commits."""
        key = f"GET {path} {sorted(params.items())}"
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        r = self._get(path, **params)
        if r.status_code == 409:
            data: Any = []
        elif r.status_code >= 400:
            raise GitHubError(f"GET {path} failed: {r.status_code} {r.text[:200]}")
        else:
            data = r.json()
        self.cache.set(key, data)
        return data

    def has_readme(self, full_name: str) -> bool:
        key = f"README {full_name}"
        hit = self.cache.get(key)
        if hit is not None:
            return bool(hit)
        found = self._get(f"/repos/{full_name}/readme").status_code == 200
        self.cache.set(key, found)
        return found

    def has_release(self, full_name: str) -> bool:
        key = f"RELEASE {full_name}"
        hit = self.cache.get(key)
        if hit is not None:
            return bool(hit)
        r = self._get(f"/repos/{full_name}/releases", per_page=1)
        found = r.status_code == 200 and bool(r.json())
        self.cache.set(key, found)
        return found

    # --- the only write this app ever performs -------------------------------

    def make_private(self, full_name: str) -> None:
        """Flip a repo to private. Reversible, and the strongest action we take."""
        try:
            r = self.client.patch(f"/repos/{full_name}", json={"private": True})
        except httpx.HTTPError as exc:
            raise GitHubError(f"Network error updating {full_name}: {exc}") from exc
        if r.status_code >= 400:
            raise GitHubError(f"Could not make {full_name} private: {r.status_code} {r.text[:200]}")
