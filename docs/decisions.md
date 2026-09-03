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

---

## D4 - The abandoned count is built where it is first needed, not by #23

**Question:** #36 (mvp, Cross-cutting) requires "the abandoned count" as the
page's most prominent element. The issue that specifies that exact feature -
wording, placement, the "count stays honest" rules - is #23, "Abandoned
counter in the header," which Gate 1 put in `post-mvp` (it is Phase 3). #36
cannot wait on a `post-mvp` issue.

**Decision:** #36 computes its own count directly from #14's stalled flags
(tracked, non-`paused`/`shipped`/`dropped` repos where `stalled=True`),
using a shared helper in `portfolio/services/render.py` rather than
recomputing the threshold logic inline (`AGENTS.md`: rules live in one
place). #23, when it is picked up post-MVP, reuses that same helper for the
terminal report's header line instead of re-defining the count - #36 becomes
the helper's first caller, #23 its second, not its origin.

**Reason:** The count itself - "how many tracked, active repos are
stalled" - is a one-line derivation of data #14 (mvp) already produces.
Nothing about #23's specific wording ("N projects with no commit for 4+
weeks", singular handling) is required by #36's acceptance criteria; #36
only needs the number and its prominence.

**Cost accepted:** None beyond ordinary shared-helper design - no feature is
deferred or duplicated, provided #23 is written against the helper #36
creates rather than inventing its own.

**Applies to:** [#36](https://github.com/soutes/course-ai-native-zoomcamp/issues/36), [#23](https://github.com/soutes/course-ai-native-zoomcamp/issues/23)

---

## D5 - What "stored data" means for the web pages

**Question:** #17 and #36 must render with **no GitHub call** - opening
either page must cost nothing. That requires the full weekly picture to
already be in the database by the time either view runs. Today only
momentum numbers are persisted (`RepoWeek`, #13). Mid-flight work
(branches/PRs, #15) and new-repos-this-week (#33) are computed but nothing
in any mvp issue says they are stored anywhere - as written, `report` (#16)
would have to be re-run against GitHub for the web pages to show the same
thing, which contradicts both pages' own acceptance criteria.

**Decision:** `report` (#16) persists one `WeeklyReport` row per ISO week
(unique on the week label, overwritten on re-run, same rule as `RepoWeek`)
holding: the rendered markdown it printed, and a structured JSON snapshot of
the data that markdown was built from - per-repo mid-flight lists (#15), the
new-repos-this-week list (#33), and the single focus item. `RepoWeek` rows
are referenced, not duplicated, for the momentum numbers. #17 and #36 read
`WeeklyReport` (plus the `RepoWeek` rows it points at) to render; they call
neither GitHub nor an LLM.

**Reason:** #36's own constraint already requires the three surfaces (`report`,
the per-week page, the dashboard) to share one service function "so the
three surfaces cannot drift apart" - that only holds if the web pages read
the exact data the command computed, not a re-derived approximation of it.

**Cost accepted:** #16 grows a persistence responsibility beyond "prints
markdown" as its goal literally states, and a new model/migration. It is the
only mvp issue that ever holds the full computed picture in one place, so it
is the only one that can write it down.

**Applies to:** [#16](https://github.com/soutes/course-ai-native-zoomcamp/issues/16), [#17](https://github.com/soutes/course-ai-native-zoomcamp/issues/17), [#36](https://github.com/soutes/course-ai-native-zoomcamp/issues/36)
