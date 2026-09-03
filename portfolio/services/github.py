"""GitHub REST client. The only module that touches the network.

Deliberately small: list my repos, count commits, check for a README and a release,
and (#15) find mid-flight work - unmerged branches and open PRs. Commit counting uses
the `Link: rel="last"` header trick so one request per repo is enough instead of
paginating through every commit.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from .cache import Cache
from .types import Commit, CommitStat, OpenPullRequest, Repo, TreeListing, UnmergedBranch

API = "https://api.github.com"
LAST_PAGE = re.compile(r'[?&]page=(\d+)>;\s*rel="last"')
BRANCH_COMPARE_CAP = 20  # docs/decisions.md D8 (amends D3)
BRANCH_LIST_PAGE_CAP = 2  # docs/decisions.md D8 - at most 200 branches scanned


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

    def _get(
        self, path: str, headers: dict[str, str] | None = None, **params: Any
    ) -> httpx.Response:
        try:
            r = self.client.get(path, params=params, headers=headers)
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

    def commit_diffstat(self, full_name: str, sha: str) -> CommitStat:
        """One commit's added/removed lines and files touched (#13).

        `GET /repos/{owner}/{repo}/commits/{sha}` - cached like every other read,
        so re-fetching the same commit's diffstat (a re-run of the same week)
        costs nothing after the first call. `stats` and `files` are read
        defensively (`or {}`/`or []`): GitHub omits `stats` for some odd repo
        states, and a commit touching only binary/renamed files still returns
        `stats.additions`/`stats.deletions` as 0 rather than omitting them, so
        totals stay correct without ever needing to look at a `patch`.
        """
        data = self._cached_json(f"/repos/{full_name}/commits/{sha}")
        stats = data.get("stats") or {}
        files = data.get("files") or []
        return CommitStat(
            sha=sha,
            additions=stats.get("additions", 0),
            deletions=stats.get("deletions", 0),
            files_changed=len(files),
        )

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

    def tags(self, full_name: str) -> list[str]:
        """Every tag name for a repo (#20's version-tag shipped signal).

        `GET /repos/{owner}/{repo}/tags`, paginated and cached page by page
        like `branches` - a re-run costs zero requests. Names are returned
        exactly as GitHub has them (e.g. `v1.2.0`); matching against the
        `^v?\\d+\\.\\d+(\\.\\d+)?$` semver-style pattern is `shipped.shipped_tag`'s
        job, not this method's.
        """
        result: list[str] = []
        page = 1
        while True:
            batch = self._cached_json(f"/repos/{full_name}/tags", per_page=100, page=page)
            if not batch:
                return result
            result.extend(t["name"] for t in batch)
            if len(batch) < 100:
                return result
            page += 1

    def readme_text(self, full_name: str) -> str | None:
        """The README's decoded text content (#20, D18).

        `has_readme()` only checks presence via a status code; detecting a
        `Status: Complete` *line inside* the README needs its actual body,
        which no existing call fetches - a genuinely new request, cached like
        every other read. The raw media type on the same
        `/repos/{full}/readme` endpoint returns the file's literal bytes
        instead of a JSON-wrapped base64 blob. `None` means no README (a 404)
        or an unreadable response; an empty cached string round-trips back to
        `None` rather than being confused with "not yet fetched".
        """
        key = f"README_TEXT {full_name}"
        hit = self.cache.get(key)
        if hit is not None:
            return hit or None
        r = self._get(
            f"/repos/{full_name}/readme",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        text = r.text if r.status_code == 200 else None
        self.cache.set(key, text or "")
        return text

    def tree(self, full_name: str, default_branch: str) -> TreeListing:
        """A repo's full file listing, one request (#18): `git/trees/{default}?recursive=1`,
        cached like every other read - a re-run costs zero requests.

        An empty default branch (a repo with no commits yet) makes GitHub answer
        404/409 for this call; that is treated as an empty, non-truncated listing
        rather than an error, so `health.judge_health` sees "no files at all" and
        reports every tree-based signal missing - never a raise (#18's AC).

        `truncated` is passed through from GitHub's own response field: when the
        tree is too large for one response, GitHub does not return every entry,
        so a caller must not read a missing README/tests/CI path as "not
        present" - see `TreeListing` and `health.judge_health`.
        """
        key = f"TREE {full_name} {default_branch}"
        hit = self.cache.get(key)
        if hit is not None:
            return TreeListing(paths=hit["paths"], truncated=hit["truncated"])

        r = self._get(f"/repos/{full_name}/git/trees/{default_branch}", recursive=1)
        if r.status_code >= 400:
            result = {"paths": [], "truncated": False}
        else:
            data = r.json()
            result = {
                "paths": [e["path"] for e in data.get("tree", []) if e.get("path")],
                "truncated": bool(data.get("truncated", False)),
            }
        self.cache.set(key, result)
        return TreeListing(paths=result["paths"], truncated=result["truncated"])

    # --- mid-flight work (#15) ------------------------------------------------

    def branches(self, full_name: str) -> list[dict[str, Any]]:
        """Up to `BRANCH_LIST_PAGE_CAP` pages of branches (200 at 100/page),
        cached page by page like `my_repos`.

        GitHub's response here is name + head `commit.sha` only - no push
        date - so it cannot alone answer "most recently pushed". See
        `unmerged_branches` for how the D8 bound is applied on top of this.

        Capped at `BRANCH_LIST_PAGE_CAP` pages (D8): the whole point of the
        bound is a request count that does not grow with a repo's branch
        count, so a repo with hundreds or thousands of branches must not
        turn this listing step itself into an unbounded number of requests.
        A repo with more branches than the cap covers simply has some of
        them invisible to `unmerged_branches` for that run - same accepted
        cost D8 already takes for the 20-compare cap.
        """
        result: list[dict[str, Any]] = []
        page = 1
        while page <= BRANCH_LIST_PAGE_CAP:
            batch = self._cached_json(f"/repos/{full_name}/branches", per_page=100, page=page)
            if not batch:
                return result
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1
        return result

    def unmerged_branches(self, full_name: str, default_branch: str) -> list[UnmergedBranch]:
        """Branches ahead of default and not merged into it - mid-flight work (#15).

        The default branch itself is never included. A branch behind but not
        ahead of default (``ahead_by == 0``) is stale, not mid-flight, and is
        excluded - this also drops a branch identical to default.

        Bounded per D8 (amending D3): GitHub's branches list carries no
        per-branch push date, and fetching one costs one extra request per
        branch - for a 40-branch repo that is 40 requests just to *order*
        them, before any `compare` call, which is worse than the 40 requests
        the bound exists to prevent. So there is no recency sort: only the
        first 20 non-default branches, in whatever order
        `GET /repos/{owner}/{repo}/branches` returns them, are ever compared.
        A repo's total cost here is at most ~2 list-pagination requests plus
        20 `compare` calls, regardless of how many branches it has.

        ``last_commit_at`` comes from the `compare` response itself (the
        newest entry in its `commits` list) rather than a separate request,
        so the 20 `compare` calls remain the only per-branch cost.
        """
        raw = self.branches(full_name)
        names = [b["name"] for b in raw if b["name"] != default_branch]
        top = names[:BRANCH_COMPARE_CAP]

        unmerged: list[UnmergedBranch] = []
        for name in top:
            compare = self._cached_json(f"/repos/{full_name}/compare/{default_branch}...{name}")
            ahead_by = compare.get("ahead_by", 0)
            if ahead_by == 0:
                continue  # behind-or-identical: stale, not mid-flight
            unmerged.append(
                UnmergedBranch(
                    name=name,
                    ahead_by=ahead_by,
                    last_commit_at=self._last_commit_date(compare),
                )
            )
        return unmerged

    @staticmethod
    def _last_commit_date(compare: dict[str, Any]) -> datetime:
        """The newest commit date in a `compare` response's `commits` list -
        that list's last entry is the branch's own most recent commit."""
        commits = compare.get("commits") or []
        if not commits:
            return datetime.fromtimestamp(0, tz=UTC)
        commit = (commits[-1].get("commit") or {}).get("author") or {}
        date_str = commit.get("date")
        if not date_str:
            return datetime.fromtimestamp(0, tz=UTC)
        return _parse_dt(date_str)

    def open_pull_requests(self, full_name: str, github_user: str) -> list[OpenPullRequest]:
        """Open PRs I opened in this repo - mid-flight work (#15).

        PRs opened by someone else in a repo I own are excluded:
        `pull.user.login` is matched against `github_user` case-insensitively.
        Draft PRs are included and carry their `draft` flag.
        """
        wanted = github_user.strip().lower()
        result: list[OpenPullRequest] = []
        page = 1
        while True:
            batch = self._cached_json(
                f"/repos/{full_name}/pulls", state="open", per_page=100, page=page
            )
            if not batch:
                return result
            for raw in batch:
                login = ((raw.get("user") or {}).get("login") or "").strip().lower()
                if wanted and login != wanted:
                    continue
                result.append(
                    OpenPullRequest(
                        number=raw["number"],
                        title=raw["title"],
                        created_at=_parse_dt(raw["created_at"]),
                        draft=bool(raw.get("draft", False)),
                    )
                )
            if len(batch) < 100:
                return result
            page += 1

    # --- the only write this app ever performs -------------------------------

    def make_private(self, full_name: str) -> None:
        """Flip a repo to private. Reversible, and the strongest action we take."""
        try:
            r = self.client.patch(f"/repos/{full_name}", json={"private": True})
        except httpx.HTTPError as exc:
            raise GitHubError(f"Network error updating {full_name}: {exc}") from exc
        if r.status_code >= 400:
            raise GitHubError(f"Could not make {full_name} private: {r.status_code} {r.text[:200]}")
