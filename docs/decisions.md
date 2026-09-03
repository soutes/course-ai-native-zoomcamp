# Decisions

Calls the spec left open, settled during grooming instead of inside an
issue. Each entry has a reason and, where there is one, the cost accepted.
Read this before grooming or implementing an issue, and do not reopen a
decision without changing it here first.

## D1 - Commit authorship is matched client-side, not via `author=`

**Question:** `config.toml` carries `emails` as a **list** (GitHub, work, and
`noreply` addresses differ across machines), but the commits endpoint
(`GET /repos/{owner}/{repo}/commits?...&author=`) accepts one identity per
call, and GitHub matches `author=` against a linked account, not a literal
email string.

**Decision:** Fetch the window's commits **without** the `author=` filter,
then match each commit's `commit.author.email` against the configured email
list in application code (case-insensitive).

**Reason:** A list of N emails would otherwise mean N requests per repo per
week (or trusting GitHub's account-matching for `author=`, which does not
behave like a literal email match). Client-side filtering needs exactly one
request regardless of list length and its correctness is easy to test from
fixtures.

**Cost accepted:** On a repo with many contributors, the response includes
commits the report will immediately discard - more payload than a
server-filtered call would return. Acceptable at this project's scale (a
personal portfolio, not a large shared repo).

**Applies to:** [#12](https://github.com/soutes/course-ai-native-zoomcamp/issues/12)

---

## D2 - Diffstat request cap per repo per week

**Question:** Issue #13 requires "the number of per-commit diffstat requests
per repo" to be capped so a 200-commit week does not blow the rate limit, but
no number is fixed anywhere - not in `SPEC.md`, not in `backlog.md`. (The
~40-commit-subject cap in `SPEC.md` section 4b is a different cap, for the
LLM prompt in #25, not for diffstat fetches here.)

**Decision:** Cap at **80 per-commit diffstat requests per repo per week**.
Commits beyond the cap still count toward the commit/active-day numbers;
only their lines-added/removed/files-touched are left out of the total, and
the `RepoWeek` row this produces is marked partial so the report can say so.

**Reason:** 80 covers a very active week (SPEC's own rate-limit math assumes
~4 requests/repo for a normal week) with headroom, while bounding the worst
case: a 10-project report where every project has a 200-commit week stays
under 800 diffstat requests, well inside the 5,000 req/h budget alongside
every other endpoint this app calls.

**Cost accepted:** A week with more than 80 commits on one repo reports an
undercount of lines/files touched for that repo, flagged as partial rather
than silently wrong.

**Applies to:** [#13](https://github.com/soutes/course-ai-native-zoomcamp/issues/13)

---

## D3 - Branch comparison bound per repo

**Question:** Issue #15 requires bounding per-repo branch comparisons ("a
repo with 40 stale branches must not spend 40 requests every run"), but no
number is fixed anywhere.

**Decision:** Compare at most the **20 most-recently-pushed non-default
branches** per repo per run. Branches beyond that are omitted from
"mid-flight work" for that run rather than compared.

**Reason:** Recently-pushed branches are the ones most likely to be
genuinely mid-flight; a branch 60th in push-recency order is closer to
abandoned than active. 20 keeps the worst case (a repo with unusually many
branches) from dominating a report's request budget.

**Cost accepted:** A repo with more than 20 branches ahead of default in one
run will not show every one of them as mid-flight work; the oldest-pushed
ones drop off first.

**Applies to:** [#15](https://github.com/soutes/course-ai-native-zoomcamp/issues/15)
