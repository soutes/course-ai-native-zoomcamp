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

**Amended by [D8](#d8---d3-amended-the-branch-bound-cannot-be-most-recently-pushed-without-defeating-itself):** "most-recently-pushed" turned out to be
unachievable without costing more requests than this decision exists to
save. The bound survives; the ordering does not. Read D8 for the current
rule.

**Question (original):** Issue #15 requires bounding per-repo branch comparisons ("a
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

## D9 - Gate 5's live `report` run is deferred to the account owner

**Question:** Gate 5's exit condition (`docs/gates.md`) is "every mvp issue
is closed, and `manage.py report` prints a retrospective for the current
week against seeded data." `manage.py report` (#16) always calls GitHub for
real (`GITHUB_TOKEN`/`GITHUB_USER`/`GITHUB_EMAILS` are hard requirements,
checked at the top of `handle()`) - there is no offline/mocked path for a
real CLI run, and none exists in this environment. `seed_demo` (#38, per
D7) deliberately does not seed `RepoWeek`/`WeeklyReport`, so there is no
"seeded data" `report` could run against even with a token - that gap is
already tracked as `post-mvp` #40.

**Decision:** All 9 remaining mvp issues (11-17, 33, 36) are closed on
their own merits - each individually QA-verified against a fake/mocked
GitHub client, 169 tests green, `report`'s full pipeline exercised
end-to-end in tests (`tests/test_report_command.py`). The literal live run
is left for the account owner, on their own schedule, with their own
token - not attempted by an agent. Unlike D6 (`--apply`, a write), `report`
only reads from GitHub; asked directly, the owner still chose to defer
rather than supply a token now, so the same "an agent doesn't do this
without the owner present" posture from D6 applies here too, extended to
reads for consistency rather than because reads carry the same risk as
writes.

**Reason:** No `GITHUB_TOKEN` exists in this environment, and per D6's
precedent, credential-gated live verification is the account owner's call,
not an agent's to make unilaterally by requesting one mid-run.

**Cost accepted:** Gate 5 is marked closed on "every mvp issue is closed"
plus full test coverage, not on a literal live run against seeded data
having actually happened. That run remains open for the owner to do by
hand at `manage.py report`.

**Applies to:** Gate 5 (`docs/gates.md`), [#16](https://github.com/soutes/course-ai-native-zoomcamp/issues/16)

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

**Applies to:** [#16](https://github.com/soutes/course-ai-native-zoomcamp/issues/16), [#17](https://github.com/soutes/course-ai-native-zoomcamp/issues/17), [#33](https://github.com/soutes/course-ai-native-zoomcamp/issues/33), [#36](https://github.com/soutes/course-ai-native-zoomcamp/issues/36)

---

## D6 - No agent runs `--apply` against a real GitHub account, ever, without the owner's in-the-moment authorization

**Question:** Issue #7's last acceptance criterion is "verified against a live account with a real token." No `GITHUB_TOKEN` exists in this environment, and `--apply` is the one command in this app that writes to GitHub for real (`PATCH .../{owner}/{repo}` with `private: true`) - a hard-to-reverse, account-changing action.

**Decision:** An agent (this session or any future automated run) never runs `--apply` against a real account on its own, even with `--yes`, even if a token happens to be present. The account owner runs that verification themselves, at a time of their choosing. Gate 3 / issue #7 close on everything else - the confirm/abort flow, the write itself, the warnings, the counts, the exit codes - all verified by code reading and a passing test suite with a faked GitHub client. The live check is left as a standing manual step for the owner, not a blocking follow-up issue.

Asked explicitly during this run whether this should become a permanent product change - `--apply` never writes even with the owner's own confirmation, only ever recording a suggestion the owner applies by hand outside the tool - the owner said no, this is about right now only. `--apply`'s existing design (list -> warn -> prompt -> write) stands as specified in `AGENTS.md` and `SPEC.md`.

**Reason:** Flipping a real repository private is the kind of action that needs a human, present, choosing to do it - not a scheduled or agent-driven run deciding on their behalf, regardless of how much test coverage backs the code path.

**Cost accepted:** Issue #7's backlog checkbox and issue close reflect "code correct and tested," not "verified running end-to-end" in the strict sense `AGENTS.md` Working normally requires. That gap is intentional and owner-acknowledged, not an oversight.

**Applies to:** [#7](https://github.com/soutes/course-ai-native-zoomcamp/issues/7)

---

## D8 - D3 amended: the branch bound cannot be "most recently pushed" without defeating itself

**Question:** Implementing #15 against D3 exposed that D3's exact wording -
sort branches by last-push date, take the top 20 - is not cheaply
achievable. `GET /repos/{owner}/{repo}/branches` (confirmed against GitHub's
REST docs) returns only branch name and head SHA, no date. Getting a real
recency signal costs one additional request per branch (`GET
.../commits/{sha}`). For D3's own example - a repo with 40 branches - that
is **40 requests just to sort them**, before the 20 `compare` calls that
follow. The "amended" version the engineer built to honor D3's letter
(fetch every branch's date, then take the top 20) costs *more* total
requests (40 + 20 = 60) than the naive approach D3 exists to prevent
(40 straight `compare` calls) - it satisfies "most recently pushed" while
failing the actual goal, which was request cost.

**Decision:** Drop the recency-ordering requirement. Bound per repo per run
is: one paginated fetch of `GET /repos/{owner}/{repo}/branches` (`per_page`
capped, at most 2 pages - 200 branches - scanned), then `compare` at most
the **first 20 non-default branches in whatever order the API returns
them** (empirically close to creation order, not push recency, but no REST
call reveals push recency without a per-branch request). Total worst-case
requests per repo: ~2 (branch list) + 20 (compare) = ~22, regardless of how
many branches the repo has - the actual property D3 was for.

**Reason:** A "most recently pushed" ordering was a reasonable-sounding
default when D3 was written during grooming, without checking what the
branches endpoint actually returns. The real constraint (GitHub REST has no
bulk branch-recency endpoint) only surfaced once someone tried to implement
it. Bounding request cost is the property that matters; which 20 branches
get shown when a repo has more than 20 is a secondary concern.

**Cost accepted:** On a repo with more than 20 non-default branches, which
20 appear as "mid-flight work" is no longer guaranteed to be the most
recently active ones - it is whichever 20 the branches API lists first for
that repo. Acceptable: a repo with over 20 branches actively ahead of
default is already an outlier this tool is not tuned for, and the
alternative (spending 40+ requests to sort them) is worse.

**Applies to:** [#15](https://github.com/soutes/course-ai-native-zoomcamp/issues/15)

---

## D7 - `seed_demo` seeds only the models that exist today

**Question:** Gate 4 describes `seed_demo` as creating "a realistic portfolio with
several projects, a mix of active and stalled" and its exit condition as
`manage.py seed_demo` followed by `manage.py runserver` showing "a populated
dashboard." Read literally against the current backlog, "stalled" and
"dashboard" both suggest the richer, current-week picture: `RepoWeek` (#13),
`WeeklyReport` (#16, the model D5 introduces to back the web pages), and the
current-week dashboard (#36) - none of which exist yet as of Gate 4. All
three are still open Gate 5 issues, and Gate 4 runs before Gate 5.

**Decision:** `seed_demo` (#38) seeds only `Project`, `TriageRun` and
`TriageDecision` - the three models that exist today. "Active and stalled"
is read as a spread of `Project.status` values (active/paused/shipped/
dropped) plus old vs. recent `status_changed_at`/`goal_set_at` timestamps,
not a `stalled` flag (which lives on `RepoWeek`, not built). "A populated
dashboard" is read against the dashboard that already exists at `/`
(`portfolio/views.py:dashboard`, `portfolio/templates/portfolio/
dashboard.html`, present since the initial commit) - it renders exactly
`Project` and `TriageRun`/`TriageDecision` data and nothing else, so it is
fully satisfiable today. It is not the enriched current-week dashboard #36
will build; #38's acceptance criteria say so explicitly rather than
implying otherwise. A follow-up, [#40](https://github.com/soutes/course-ai-native-zoomcamp/issues/40), `post-mvp` and blocked on
#13/#16/#36, extends `seed_demo` to also seed `RepoWeek`/`WeeklyReport` once
those models land.

**Reason:** An issue's acceptance criteria must be checkable against what
the codebase can actually do (`docs/team/pm.md`); writing criteria that
assume `RepoWeek`/`WeeklyReport` fields that do not exist would make #38
unimplementable as written, or force the engineer to silently invent scope
(building those models early) that belongs to #13/#16 instead.

**Cost accepted:** #38 alone does not make the *richer* current-week
dashboard reviewable offline - only the `/` page that exists today. Gate
4's own wording ("stalled", "dashboard") is more naturally read as the
end-state picture than as what exists at Gate 4 time; #40 closes that gap
once Gate 5 lands its models, but until then Gate 4's exit condition is
satisfied by the pre-existing `/` page, not by the fuller picture the
wording evokes. Flagged to the orchestrator, not papered over.

**Applies to:** [#38](https://github.com/soutes/course-ai-native-zoomcamp/issues/38), [#40](https://github.com/soutes/course-ai-native-zoomcamp/issues/40)
