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

---

## D10 - Branch protection on `main` is a standing manual action for the owner, not scoped into #39

**Question:** #39's original issue body listed branch protection (CI
required to pass before a PR can merge) as an acceptance criterion,
verified by screenshot or `gh api repos/{owner}/{repo}/branches/main/
protection`. `backlog.md`'s own note on #39 already says branch protection
"is a repo-settings change the owner makes by hand, not an agent write,"
and #39's own Constraints already forbade automating it via `gh api` write
calls - but that leaves an acceptance criterion asking for an end state no
agent is allowed to produce, which the issue can never close on its own
merits.

**Decision:** Branch protection moves out of #39's acceptance criteria
entirely, into out of scope. No agent (this session or any future one)
makes the write call that changes `main`'s branch protection settings,
with or without a token, following D6's precedent for repo-settings and
account-affecting writes. #39 documents the exact click-path for the owner
(Settings -> Branches -> add a protection rule for `main` -> require status
checks to pass -> select the `CI` workflow) inside the issue, but does not
carry enabling it as a checkable criterion. It is a standing manual action
for the owner, not a blocking follow-up issue - same treatment as D6's
`--apply` verification and D9's live `report` run.

**Reason:** An acceptance criterion an agent structurally cannot satisfy
either blocks the issue from ever closing cleanly or invites an
unauthorized write to close it. D6 already establishes the pattern this
project uses for repo-settings-affecting actions: they wait for the owner,
present, choosing to do it - extended here from account writes (`--apply`)
to repo-settings writes (branch protection), the same category of risk.

**Cost accepted:** #39 closes on the workflow step and README badge alone;
branch protection is not actually enabled by the issue closing - that
remains true only once the owner clicks it by hand. Same acknowledged gap
as D6/D9's deferred manual verification.

**Applies to:** [#39](https://github.com/soutes/course-ai-native-zoomcamp/issues/39)

---

## D11 - Error templates live flat in `portfolio/templates/`, not namespaced under `portfolio/templates/portfolio/`

**Question:** Every existing template (`dashboard.html`, `retro_detail.html`,
`retro_list.html`) lives under `portfolio/templates/portfolio/` - the
standard Django app-namespacing convention, so `{% include %}`/`render()`
calls referencing `"portfolio/dashboard.html"` cannot collide with
same-named templates from a different app. Django's default error views
(`django.views.defaults.page_not_found`, `permission_denied`,
`server_error`) do not follow that convention - they look up the literal
names `404.html`, `403.html`, `500.html` with no app prefix, via whatever is
on the template engine's search path. `TEMPLATES[0]["DIRS"]` in
`config/settings.py` points at `BASE_DIR / "templates"`, a project-root
directory that does not exist in this repo; `APP_DIRS` is `True`, so the
only search path that actually resolves anything today is
`<app>/templates/` for each installed app, i.e. `portfolio/templates/`
itself (not the `portfolio/` subfolder inside it).

**Decision:** `403.html`, `404.html`, `500.html` go directly in
`portfolio/templates/` (sibling to the existing `portfolio/` subfolder), not
inside `portfolio/templates/portfolio/` and not in a new project-root
`templates/` directory. No `TEMPLATES["DIRS"]` change, no new directory.

**Reason:** Django's error-view lookup is not namespace-aware and there is
exactly one search path that already reaches `portfolio/templates/` -
`APP_DIRS`. Namespacing the error templates the way the page templates are
namespaced would make them invisible to `page_not_found`/`server_error`,
silently falling back to Django's built-in pages with `DEBUG=False`, which
is the exact failure #41 exists to fix.

**Cost accepted:** None - this only fixes a location that would otherwise
need a second, harder-to-diagnose grooming pass once the first attempt
mysteriously didn't render.

**Applies to:** [#41](https://github.com/soutes/course-ai-native-zoomcamp/issues/41)

---

## D12 - #43 builds the shared project-grouping helper; #34 becomes its second caller

**Question:** #43's own filed body suggests its shape as "a `/projects/`
page mirroring what #34 (`projects` management command, terminal) shows,
reusing the same query/shaping so the CLI and the page cannot drift apart."
But #34 is still open and unimplemented - there is no existing
query/shaping to reuse. Grooming #43 to depend on #34 landing first would
block a `post-mvp` issue on another `post-mvp` issue with no forcing
function to build either.

**Decision:** #43 builds the grouping/shaping logic itself, as a function
in `portfolio/services/` (e.g. `portfolio/services/projects.py`) - grouping
`Project` rows by status, with counts, following `AGENTS.md`'s layering
rule (no Django, no LLM, rules not delivery). The `/projects/` view is thin
wiring over that helper. When #34 is picked up, it becomes the helper's
second caller instead of inventing its own grouping logic - same pattern as
D4 (#36 built `abandoned_count`, #23 became its second caller).

**Reason:** The property that matters - CLI and page not drifting apart -
only requires that whichever issue lands *first* builds the shared helper
and whichever lands *second* reuses it. Nothing about #43 requires #34 to
exist first; blocking on it would stall #43 for no functional reason.

**Cost accepted:** None beyond ordinary shared-helper design, provided #34,
when implemented, is written against #43's helper rather than duplicating
the grouping/formatting rules inline.

**Applies to:** [#43](https://github.com/soutes/course-ai-native-zoomcamp/issues/43), [#34](https://github.com/soutes/course-ai-native-zoomcamp/issues/34)

---

## D13 - The public `/projects/` page never shows free-text reasons or which repos triage made private

**Question:** #43's underlying models carry free text not written for a
public audience: `Project.status_reason` (why a project was paused/shipped/
dropped) and `TriageDecision.reason` (why one specific repo was made
private), plus `TriageDecision.repo` itself (which repo triage acted on).
The pre-#36 dashboard (restored in git history at `4ccc577^`) already showed
`status_reason` for ended projects, and the "candidate shape" language in
#43's filed body says "triage history" without qualifying what part of it.
Read literally, "triage history" could mean rendering `TriageDecision` rows
one by one - repo name, reason, timestamp - to a page with no login.

**Decision:** The public page shows, for triage history, only what the
pre-#36 dashboard already showed at the aggregate level: each `TriageRun`'s
date and the count of repos it made private. It does not list which repos
were affected and does not render `TriageDecision.reason`. For `Project`,
the page shows `status_reason` for ended/paused projects (as the pre-#36
dashboard did) - this field is about the project's own trajectory, written
by the same person choosing to expose the project publicly in the first
place, and was already public prior to #36. `TriageDecision.reason` is
different in kind: it is commentary about a repo the owner deliberately
chose to hide from the public, so publishing the reason (or which repo)
defeats the purpose of having hidden it.

**Reason:** Naming a privated repo, or publishing why it was hidden,
on a public page directly contradicts the reason triage exists - AGENTS.md
already treats `triage`'s single write (`private: true`) as sensitive
enough to require a warn-and-confirm flow before it happens; showing the
result's details publicly afterward undermines that same intent.

**Cost accepted:** The public page is less detailed about triage than the
admin view (`/admin/`, login required) or the terminal `triage` command -
by design. Anyone wanting per-repo triage detail still has the admin.

**Applies to:** [#43](https://github.com/soutes/course-ai-native-zoomcamp/issues/43)

---

## D14 - The privacy note lives at `docs/privacy.md`, and covers only what's actually committed today

**Question:** #42's filed body offered a choice - "README.md or a new
`docs/privacy.md`, linked from README" - without picking one, and its
acceptance criteria hedged on repo descriptions/goals with "unless later
decided otherwise" rather than stating the current rule plainly. Separately,
`AGENTS.md`'s Determinism rule ("commit subjects and diffstat numbers,
never full diffs") only describes the coaching call (#25, Phase 4). Goal
drift (#29, Phase 5, still `post-mvp` and unimplemented) will need to send
each project's `goal:` string to the same LLM to judge drift - a second kind
of data, not covered by the existing rule, and not yet decided anywhere.

**Decision:** The note is a standalone file, `docs/privacy.md`, linked from
a new "Privacy" section in `README.md` (placed after "The four features",
before "Status" - where a reader meets "AI coaching" for the first time).
Not a section inside `README.md` itself, so it can grow (goal drift, any
future LLM-backed feature) without bloating the README's own length. Its
scope is exactly what today's `AGENTS.md` and `SPEC.md` already commit to:
commit subjects and diffstat numbers, sent for every tracked repo including
private ones (`SPEC.md` section 10, already accepted for a personal tool),
never full diffs, never repo descriptions, never goal text - with a note
that goal drift (#29) will send goal text once built and this document must
be updated then, rather than the note speculatively covering data #29
doesn't send yet.

**Reason:** A checkable acceptance criterion needs one answer, not an
either/or left to the engineer. A separate file keeps the README short and
gives future LLM-sending features (#29 and beyond) one place to extend
instead of re-litigating where privacy content lives. Describing only what
is actually sent today (not "unless later decided otherwise") keeps the
document accurate without needing another grooming pass just to remove a
hedge.

**Cost accepted:** `docs/privacy.md` will need a follow-up edit when #29
(goal drift) ships, since it sends a new kind of data this version does not
cover. That edit belongs to #29's own acceptance criteria, not to #42.

**Applies to:** [#42](https://github.com/soutes/course-ai-native-zoomcamp/issues/42), [#29](https://github.com/soutes/course-ai-native-zoomcamp/issues/29)

---

## D15 - Only three of #18's five health signals come from the tree fetch

**Question:** #18's filed body said "detection reads the repo tree in one
request" for all five signals (README, tests, CI, license, description), but
a `git/trees/{default}?recursive=1` response is a file listing - it cannot
produce a repo's description, which is not a file at all. `Repo.license` and
`Repo.description` are also already populated for every tracked repo by
`GitHub.my_repos()` (`github.py:_to_repo`, reading the repos-list response's
own `license.spdx_id` and `description` fields) - zero extra requests. A
literal reading of "one request" would have an engineer re-derive license
and description from the tree (description is impossible; license would mean
scanning for a `LICENSE` file, which is weaker than GitHub's own license
detector - it recognizes license text in files GitHub names differently).
Separately, `GitHub.has_readme()` already exists (one request per repo,
`github.py:254`) and backs triage's shipped Phase 0 classifier (#4) - #18
naming README detection among its tree-based signals could be read as
replacing that call, which would touch already-shipped code for a Phase 2
issue with no requirement to do so.

**Decision:** Of #18's five signals, only **README, tests-directory, and
CI-config** come from the single tree fetch - these are the three that
depend on directory layout GitHub's repo metadata doesn't expose. **License**
and **description** reuse the existing `Repo.license`/`Repo.description`
fields (already fetched, zero additional requests); "no license" is
`Repo.license` falsy, "no description" is `Repo.description` falsy. #18's
tree-based README check is new logic in its own health-signals module (not
`triage.py`), separate from and not a replacement for `GitHub.has_readme()` -
that call and everything that reads it (#4's classifier) is untouched.

**Reason:** A description cannot be read from a file tree under any
interpretation, so the AC as filed was unimplementable literally for that
one signal. Reusing already-fetched fields for license/description costs
nothing and avoids a weaker, redundant filename-based license check.
Leaving `has_readme()` and triage alone keeps this Phase 2 issue from
touching Phase 0 code it has no acceptance criterion requiring it to change.

**Cost accepted:** Two near-duplicate "does a README exist" checks now exist
in the codebase - triage's `has_readme()` (single GET) and #18's tree-parsed
version (part of the one-request tree read). Acceptable: they serve
different callers with different cost profiles (triage already pays for its
own GET; #18 gets README for free as a side effect of the tree fetch it
needs for tests/CI anyway), and merging them is a refactor with no
acceptance criterion asking for it.

**Applies to:** [#18](https://github.com/soutes/course-ai-native-zoomcamp/issues/18), [#4](https://github.com/soutes/course-ai-native-zoomcamp/issues/4)

---

## D16 - `--pause`'s argument is an ISO date; free-text reasons move to a separate `--reason` flag

**Question:** #19's filed body gives `--pause "back in November"` as its example, then separately
requires "`--pause` without a parseable date is rejected rather than stored as an open-ended
pause." Those two lines describe the same single argument two incompatible ways: the example
reads as free text (matching `--drop "no longer worth it"`, clearly a reason), but the AC requires
that same argument to be a date the code can parse. "back in November" is not parseable by
`datetime` without a natural-language date library, and `AGENTS.md` says not to add a dependency
without asking.

**Decision:** `--pause` takes one required argument, an ISO date (`YYYY-MM-DD`), parsed with
`datetime.date.fromisoformat` - standard library only. All three flags (`--shipped`, `--pause`,
`--drop`) additionally accept an optional `--reason "text"` for the free text that becomes
`Project.status_reason`. The issue's `"back in November"` example is illustrative of the kind of
text a reason carries, not the literal argument to `--pause`.

**Reason:** Keeps the date-parsing AC satisfiable with the standard library, keeps `--drop`'s and
`--pause`'s argument handling consistent (both take a reason the same way), and does not read the
issue's own illustrative example as a literal spec that contradicts the very next bullet in the
same issue.

**Cost accepted:** None beyond the CLI surface reading `--pause 2026-11-01 --reason "back in
November"` instead of `--pause "back in November"` - one extra flag to type, not a capability
loss.

**Applies to:** [#19](https://github.com/soutes/course-ai-native-zoomcamp/issues/19)

---

## D17 - Re-acking overwrites the single transition record; no multi-entry transition history is built

**Question:** #19's filed body requires "Re-acking an already-shipped project is allowed and
records a second transition; the history is not overwritten." `Project` (#10) carries exactly one
set of transition fields - `status`, `status_reason`, `status_changed_at` - not a log table.
Reading the AC literally (every past transition individually visible later) would mean adding a
new model and migration, which neither `backlog.md`'s one-line description ("Done when an ended
project leaves the weekly report and keeps its record") nor the rest of #19's own acceptance
criteria call for - the closest existing pattern for that shape, `TriageRun`/`TriageDecision`, was
built for a different feature (#4/#7) and #19 does not ask to extend it.

**Decision:** Re-acking a project overwrites `status`, `status_reason` and `status_changed_at`
with the new transition's values - it does not error, and it does not preserve the previous
transition's reason or timestamp anywhere. "Keeps its record" (`backlog.md`) means the `Project`
row itself is never deleted (`AGENTS.md`: nothing is deleted), not that every past transition
remains individually queryable. A full multi-entry transition log is out of scope for #19; no
follow-up issue is filed for it since nothing today asks for it - it can be groomed properly if a
real need for one shows up.

**Reason:** The model that exists supports "current status, reason, and when it changed," not a
log. Building a log table is scope invention beyond what #19 or `backlog.md` asks for, and the
literal AC as filed cannot be satisfied without one.

**Cost accepted:** After several re-acks, only the latest transition's reason and timestamp are
visible anywhere in the app - the sequence of prior transitions (e.g. paused, then shipped, then
re-shipped with a different reason) is not recoverable.

**Applies to:** [#19](https://github.com/soutes/course-ai-native-zoomcamp/issues/19)

---

## D18 - #20's README signal costs one new request per active repo per week; auto vs. manual "shipped" is told apart by a `status_reason` prefix, not a new field

**Question:** #20's filed body claimed detection "reuses the tree read from #18" for all three
signals and that the README check needs "no new per-repo request beyond" releases/tags/README
"already fetched." That is not true for the README signal: #18's tree (`GitHub.tree`,
`git/trees/{default}?recursive=1`) is a **file listing** - paths only, no blob content - and the
existing `GitHub.has_readme()` (used by triage, #4) only reads a response status code, never the
README's body. Detecting a `Status: Complete` *line inside* the README requires fetching its
actual content, which no existing call does - a genuinely new request per repo. Separately, #20's
AC requires a shipped-by-release repo that starts committing again to return to "active", but
**not** to override a status a human set with `ack --shipped` - `Project` (#10/#19, D17) has no
field recording whether a transition was automatic or human, only `status`/`status_reason`/
`status_changed_at`, and D17 already rejected adding a transition-history model for a lesser
reason (re-ack bookkeeping) than this.

**Decision:**
1. **README signal is a new request.** A new `GitHub.readme_text(full_name) -> str | None` method
   fetches the README's decoded content (`Accept: application/vnd.github.raw+json` on the same
   `/repos/{full}/readme` endpoint `has_readme` already calls), cached like every other read. It
   runs once per in-report-window (active, non-paused) project per week, alongside the tags call
   below - both are new but bounded to the same population `report` already fetches
   `commits_in_window`/`gh.tree` for, so the added cost is proportional to what the command
   already pays, not unbounded.
2. **Tags are a new `GitHub.tags(full_name)` method** (`/repos/{full}/tags`, cached), filtered to
   names matching `^v?\d+\.\d+(\.\d+)?$` (optional leading `v`, major.minor with optional patch).
   A pre-release-looking tag (`v1.0.0-rc1`, `v2.0-beta`) does **not** count - it signals "not yet
   final," the opposite of shipped.
3. **`Status: Complete` matching:** case-insensitive, read one line at a time; markdown wrapping
   characters (`#`, `*`, `_`, `-`, backticks, leading/trailing whitespace) are stripped from the
   line before matching `^status:\s*complete$` against what remains - an exact value match, not a
   substring search, so `Status: Complete, tests pending` does **not** match (it is not exactly
   "complete") and `Status: In Progress`/`Status: WIP` do not either.
4. **Signal priority when more than one fires:** release, then tag, then README, in that order -
   the reason recorded names whichever fired first by this priority, not every signal that fired.
5. **Auto vs. manual provenance uses the existing `status_reason` field**, not a new column: every
   auto-fired transition's reason is written with a fixed prefix, `"Auto-detected: "` (e.g.
   `"Auto-detected: released"`, `"Auto-detected: tag v1.2.0"`, `"Auto-detected: README says Status:
   Complete"`). The "keeps committing -> active again" check (a second pass over
   `Project.objects.filter(status=SHIPPED)`, after the main per-project loop, calling
   `commits_in_window` for the current report week same as every other project) only fires for
   rows whose `status_reason` starts with that prefix. A project shipped by `ack --shipped` never
   carries that prefix, so it is never auto-reactivated or otherwise touched - "explicit human
   state wins over inference, always" (#20's own constraint) holds without a schema change.
6. **Detection happens inside `report`'s existing per-project loop**, at the start of each
   iteration, before that project's row is added to `repo_rows`: if a signal fires, call `#19`'s
   `apply_transition(project, SHIPPED, reason=...)` and skip appending the row, so the repo drops
   out of the *same* run's report, not the next one. No second `report` invocation is required to
   observe the drop.

**Reason:** The issue as filed described a free lunch (three signals, zero new requests) that the
codebase cannot deliver - `has_readme`/`tree` genuinely do not carry README content. Rather than
leave that AC unimplementable or have the engineer quietly invent a workaround, the real cost
(two new, cached, once-per-active-repo-per-week requests) is named and bounded here. Reusing
`status_reason`'s existing prefix convention for auto/manual provenance avoids a second model or
migration for a one-bit distinction, consistent with D17's refusal to add transition-history
machinery for a smaller need.

**Cost accepted:** `report` now makes two more GitHub requests (tags, README content) per active
project per week than it did before #20, on top of what #18 already added. A `status_reason` that
happens to start with `"Auto-detected: "` for another reason (unlikely, but a human could type it)
would be treated as auto-provenance - accepted as a naming convention, not a bulletproof flag, the
same way #18/#19 already lean on plain-string conventions elsewhere in this codebase.

**Applies to:** [#20](https://github.com/soutes/course-ai-native-zoomcamp/issues/20)

---

## D19 - #21's "previous week" is new code, not literal reuse of #11; the `RepoWeek` lookup follows the `stalled_lookup.py` split

**Question:** #21's filed body said "Previous-week arithmetic reuses #11," but #11
(`portfolio/services/week.py`) only ships `week_window` (label -> window) and
`week_label` (window -> label) - there is no "week label N-1" function anywhere in the
codebase today. Read literally, "reuses #11" could be misread as "the function already
exists, just call it," which it does not; getting the calendar-previous ISO week label
right across a year boundary (`2027-W01` -> `2026-W53`, not `2027-W00`; 2026 is a
53-ISO-week year, so `W52` - the number this entry originally used - is itself wrong,
corrected during #21's QA pass) needs its own
date arithmetic, the same `date.fromisocalendar` shape `week_window` already uses, not a
generic `week - 1` string operation. Separately, #21's Constraints said the calculation
lives in `portfolio/services/`, "no Django and no LLM," but the previous week's numbers
have to come from a `RepoWeek` row - a Django model - so a literal read of "no Django in
the calculation" would make the AC unimplementable inside a single pure function, the
same shape of problem D15/D18 already found in other issues' filed claims.

**Decision:**
1. `previous_week_label(week: str) -> str` is a new function added to
   `portfolio/services/week.py`, alongside `week_window`/`week_label` (same file, same
   pure-stdlib style: resolve `week`'s Monday via `date.fromisocalendar`, subtract 7
   days, read the ISO year/week off the result via `.isocalendar()` - which is exactly
   what makes the year-boundary case correct for free, the same mechanism `week_window`
   already relies on). It is new code #21 adds, not a call into something #11 already
   built.
2. The delta math itself (`current - previous`, and the "first week tracked" vs.
   "last week: 0" distinction) is a pure function taking plain numbers/`None`, no Django,
   no LLM - this is what "the calculation" in #21's Constraints means.
3. Reading the previous week's `RepoWeek` row is a **Django-aware companion module** in
   `portfolio/services/`, following the split `stalled_lookup.py` already established for
   #14 (a pure `stalled.py` plus a Django-aware `stalled_lookup.py` that queries
   `RepoWeek` and hands plain values to it). #21 either adds a sibling function to
   `stalled_lookup.py` or a new small module next to it - an engineer's implementation
   choice, not a decision this grooming pass needs to fix - but it does **not** put a
   `RepoWeek.objects` query inside `portfolio/services/render.py`, which stays
   Django-free per `AGENTS.md`.

**Reason:** "Reuses #11" as filed would have an engineer either invent the year-boundary
arithmetic inline wherever deltas are computed (duplicating `week_window`'s
`fromisocalendar` logic) or go looking for a function that isn't there. Naming the split
explicitly - new pure date helper, pure delta math, Django-aware lookup mirroring an
already-shipped pattern - keeps #21 buildable without an engineer having to rediscover
the `stalled_lookup.py` precedent mid-implementation.

**Cost accepted:** None - this only writes down a design #14 already established and
that #21 was always going to need; no scope changes.

**Applies to:** [#21](https://github.com/soutes/course-ai-native-zoomcamp/issues/21), [#11](https://github.com/soutes/course-ai-native-zoomcamp/issues/11)

---

## D20 - #22's "which days were active" reads as a rhythm category from the existing count, not a literal day list

**Question:** #22's filed body asks each repo-week to report "which **days** were
active, not only how many commits happened," and to compute "day-of-week... in local
time, so a late-night Sunday commit is not counted as Monday." Read literally, that
implies rendering actual calendar dates or weekday names (`Mon, Wed, Fri`) per repo.
But #13's `compute_repo_week` (`portfolio/services/momentum.py`) builds the set of
distinct local-calendar days internally only to take its `len()` -
`RepoWeekStats.active_days`, the `RepoWeek.active_days` column, and
`RepoReportData.active_days` all persist and pass along a **count**, never the dates
themselves. Nothing downstream of #13 has the actual day list to render, and #22's own
Constraints say to read "the active-day data already produced by #13; do not re-fetch
commits" and to stay inside `portfolio/services/` with no new fetch - which rules out
re-deriving the date set from raw commits at render time, and D5 already requires the
web pages (and by the same logic, anything `render.py` produces) to work from stored
data with no recomputation from GitHub. Adding a stored day-list would mean a new
`RepoWeek` field and migration, which neither `backlog.md`'s one-line description ("the
spread of active days... outrank raw totals") nor `SPEC.md` section 6 (which only ever
shows the pattern as "18 commits, 5 active days," never named weekdays) asks for.

**Decision:** "Which days were active" is satisfied by a **rhythm category** derived
from the two counts #13 already stores - `commits` and `active_days` - not by listing
specific calendar dates or weekday names anywhere in the report:
- `active_days == 1` (and `commits > 0`) -> **burst** wording, e.g. "all on one day"
- `active_days >= 5` -> **habit** wording, e.g. "spread across N days - a habit"
- `active_days` between 2 and 4 -> a neutral **spread** wording that names the count
  ("spread across N days") without applying either the "burst" or "habit" label - the
  literal middle-ground AC ("two and three active days are not artificially forced
  into different labels")
- `commits == 0` -> no rhythm wording at all (these repos already render through
  `_went_wrong_lines`, not `_went_well_lines`, so this falls out of the existing split
  rather than needing a new check)

The AC bullet about local time is already satisfied by #13's existing
`active_days = {c.authored_at.astimezone(tz).date() for c in commits}`
(`momentum.py`) - #22 adds no new day-of-week computation, it only reads the count that
computation already produces correctly. No new model field, no migration, no re-fetch:
the categorization is a pure function of `RepoReportData.commits`/`.active_days`
(already on every row `render.py` builds).

**Reason:** The literal reading (render actual dates/weekday names) is not buildable
from data #13 stores today without a schema change #22's own Constraints forbid
("reads the data already produced by #13; do not re-fetch commits"). The property the
issue's acceptance test actually checks - "a one-day burst and a five-day habit with
equal commit counts read differently" - only requires the count and the category label,
not the literal dates. `SPEC.md`'s own worked example ("5 active days," not "Mon Tue Wed
Thu Fri") backs this reading.

**Cost accepted:** The rendered prose never names which specific days (Monday,
Tuesday, ...) had a commit, only how many distinct days and which rhythm bucket that
falls into. If a future issue wants literal weekday names, it will need to extend
`RepoWeekStats`/`RepoWeek` with a stored day-list (or day-of-week bitmask) and a
migration - not scoped here.

**Applies to:** [#22](https://github.com/soutes/course-ai-native-zoomcamp/issues/22), [#13](https://github.com/soutes/course-ai-native-zoomcamp/issues/13)

---

## D21 - The abandoned-count line renders as plain text, without `SPEC.md`'s `⚠` prefix

**Question:** `SPEC.md` section 8b's report skeleton shows the count line as
`⚠ 2 projects with no commit for 4+ weeks` - prefixed with a warning glyph.
But #23's own filed Constraints say "Tone is blunt. No softening, no
encouragement, **no emoji**." `⚠` is a symbol, not a letter, and reads as
exactly the kind of decoration the constraint rules out. Nothing in
`AGENTS.md` or `docs/process.md` says which one wins when `SPEC.md`'s worked
example and an issue's own Constraints disagree - `process.md` only settles
`docs/outdated/` losing to an issue, and `SPEC.md` is not in that directory.

**Decision:** Render the line as plain text, exactly `N projects with no
commit for 4+ weeks` (or the zero/singular variants), with no leading
symbol. #23's Constraints are the more specific, more recently written
instruction for this exact line, and match the rest of the report's existing
style - `render.py` uses no emoji or symbol prefix anywhere else
(`_went_wrong_lines`, `_focus_item_text`, the dashboard's own `.abandoned`
block in #36 all render plain text or CSS-driven color, never a glyph).

**Reason:** An issue's own Constraints are what an engineer implements
against; `SPEC.md`'s skeleton is illustrative of the shape of the report
(headings, sections, roughly this content) rather than a literal
character-for-character spec, and section 8b predates #23's explicit tone
constraint. Keeping the whole report free of symbols also avoids a second,
narrower question this would otherwise raise - whether `⚠` is itself
readable through `rich.markdown.Markdown` and copy-pasted terminals - that
plain text sidesteps entirely.

**Cost accepted:** The rendered report differs from `SPEC.md`'s literal
worked example by one dropped character. Nothing else about the line's
wording, placement or content changes.

**Applies to:** [#23](https://github.com/soutes/course-ai-native-zoomcamp/issues/23)

---

## D22 - #35's `--last` bypasses the GITHUB_TOKEN/USER/EMAILS check by moving it, not skipping it after the fact; "most recent" means most recently generated, not the highest week label

**Question:** #35's filed body asks for `report --last` to reprint the most recent `WeeklyReport`
row with "no network, no LLM, no token," but `report.py`'s `handle()` checks
`GITHUB_USER`/`GITHUB_TOKEN`/`GITHUB_EMAILS` unconditionally in its first ten lines, before any
option is even read - `--refresh`, `--repo` and every other flag are already downstream of that
check. As filed, the AC "it works with `GITHUB_TOKEN` unset" cannot be satisfied without a code
change to `handle()` itself, which the issue's Constraints ("this task adds no new data source")
could be misread as ruling out. Separately, #35 never says what "most recent" means. `WeeklyReport`
is unique on `week` and `Meta.ordering = ["-week"]` (highest week label first) - but a report is
also re-run out of order in practice (e.g. backfilling an older week, or `--repo` narrowing), so the
row with the highest `week` label is not always the row that was written most recently. Both
readings are defensible and produce different output when reports are generated out of order.
Third, several ACs as filed (coaching reprinted from storage, a `--no-llm`-produced report reprints
without coaching sections) assume Phase 4 (#24-28, coaching) and #27 (`--no-llm`) already exist -
neither does yet (`Phase 3`, this issue, and `Phase 4` are both still open; `render.py`'s own
docstring says `coaching` is "always `None` today"). An issue cannot be tested against
infrastructure that is not built.

**Decision:**
1. The `GITHUB_USER`/`GITHUB_TOKEN`/`GITHUB_EMAILS` check moves inside `handle()` to run only when
   `options["last"]` is falsy - `--last` returns before that check is reached, not after it, so no
   token/user/email is read, required, or referenced on that path at all. This is real code that
   the engineer must write, not an existing branch the issue skips.
2. "Most recent" means **the `WeeklyReport` row with the greatest `generated_at`** (when it was
   last saved to the database), not the greatest `week` label. `generated_at` is `auto_now=True`
   (already there), so no new field is needed - the query is
   `WeeklyReport.objects.order_by("-generated_at").first()`. This matches the issue's own framing
   ("reprint the most recent report... so the Monday retro is readable on a plane") - a person
   wants what they last generated, not necessarily the calendar-latest week, since `report` can be
   re-run for an older week (backfill) after a newer one already ran.
3. The coaching-related ACs are satisfied structurally, not by new code: `WeeklyReport.markdown`
   already holds the exact printed text (coaching section present or absent, whatever `render.py`
   produced at generation time), and `--last` only ever prints that stored string back - it never
   calls `render.render_report_markdown` or anything in `portfolio/services/render.py` again. That
   means "coaching is reprinted from storage, never regenerated" and "a `--no-llm` report reprints
   without coaching" hold automatically once `--last` exists, for free, before #24-28/#27 are ever
   built - there is nothing coaching-specific to implement in #35. The test for #35 (this repo,
   today) exercises this with `coaching = None` (the only state that exists); it does not need to
   wait on Phase 4 to be written or to pass.

**Reason:** An acceptance criterion an agent cannot satisfy without a named code change either
blocks the issue or invites the engineer to guess whether the Constraints forbid that change - D15,
D18 and D19 hit the same shape of problem in other issues and the fix each time was to name the real
change explicitly rather than leave it implicit. "Most recent" needs one answer for the same reason
D16 needed one for `--pause`'s argument: two readings that diverge on real data cannot both be
"the" acceptance criterion. Grounding the coaching ACs in what `render.py` already guarantees (full
markdown stored, verbatim reprint) means #35 does not have to fake or stub Phase 4 to be
implementable now, and nothing about it will need revisiting once #24-28 land - the design already
covers that case.

**Cost accepted:** None beyond the `handle()` reordering itself, which #35 was always going to need
to satisfy its own "works with both keys unset" AC as filed.

**Applies to:** [#35](https://github.com/soutes/course-ai-native-zoomcamp/issues/35)

---

## D23 - #24's client reads existing `LLM_*` settings as-is; only the API-key variable is renamed off `groq`

**Question:** Grooming #24 found that `config/settings.py` already defines `LLM_BASE_URL`,
`LLM_MODEL` and `LLM_API_KEY` (reading `GROQ_API_KEY`), with `LLM_BASE_URL` and `LLM_MODEL`
defaulting to Groq's endpoint and `llama-3.3-70b-versatile` - present since the initial commit,
ahead of #24 ever being built. #24's own filed acceptance criteria say "no vendor default
compiled in" and "the string `groq` appears in no module name, no class name and no default
value" - read literally, that forbids the `LLM_BASE_URL`/`LLM_MODEL` defaults that already exist
and are already documented as intentional (`docs/privacy.md`, D14: "The default is Groq. No
vendor is hardcoded."). The two statements conflict: `docs/privacy.md` treats a Groq-pointing
default as compatible with "no vendor hardcoded" (hardcoded means the *client* cannot special-case
a vendor, not that the *settings default* cannot point at one); #24's drafted ACs read more strictly
than that. `GROQ_API_KEY` as the key's variable name is a separate problem neither document
addresses: it puts the literal string `groq` into a name the runtime imports and reads, which
holds regardless of how the base-URL-default question is settled.

**Decision:** `LLM_BASE_URL` and `LLM_MODEL` keep their existing defaults (Groq's endpoint and
model) - #24 does not touch them, and its acceptance criteria are worded against `docs/privacy.md`
("no vendor hardcoded" = the client module never special-cases a vendor; a default value pointing
at Groq is allowed and already shipped). The API key gets no default (missing raises the clear,
catchable error #24 already requires) and its environment variable is renamed from `GROQ_API_KEY`
to `LLM_API_KEY` for consistency with the other two `LLM_*` variables - that one-line settings.py
edit and the matching `.env.example` line are in #24's scope, since #24 is the first issue that
actually reads the key at runtime and the only issue that touches this variable before Phase 4.

**Reason:** Reopening #2 (closed, mvp) to fix a name picked before this document existed would be
scope creep on a closed issue; #24 is the natural, and only, place left to fix it before any code
depends on the old name. Keeping the base-URL/model defaults matches the product decision already
recorded in `docs/privacy.md` and avoids forcing a fresh clone to configure two extra variables
just to try the app.

**Cost accepted:** Anyone with a `.env` carrying `GROQ_API_KEY=...` from before this decision needs
to rename it to `LLM_API_KEY` - acceptable pre-MVP-completion, no deployed instance exists yet.

**Applies to:** [#24](https://github.com/soutes/course-ai-native-zoomcamp/issues/24), [#2](https://github.com/soutes/course-ai-native-zoomcamp/issues/2)

---

## D24 - #25's prompt carries commit subjects and diffstat numbers only; goal text stays out until #29

**Question:** #25's filed acceptance criteria said "the prompt carries, per repo: the goal,
commit **subjects**, and diffstat **numbers**." But `docs/privacy.md` (D14) already states
plainly, for exactly this feature, that what is sent is "commit subjects and diffstat numbers ...
Nothing else," lists "goal text" under "What is never sent," and says goal text is sent only once
goal drift (#29, Phase 5, unbuilt) ships - at which point `docs/privacy.md` itself must be
updated to cover it. `AGENTS.md`'s Determinism rule and `SPEC.md` section 4b agree: both name
"commit subjects and diffstat numbers," never a goal. Separately, `portfolio/services/render.py`'s
`RepoReportData` (what #25 is constrained to build the prompt from, fetching nothing new) has no
`goal` field at all - `Project.goal` exists on the model but was never threaded through to the
report's data shape, so satisfying the AC as filed would mean #25 quietly adding a new field and a
new query, which contradicts its own Constraints ("fetches nothing new").

**Decision:** #25's prompt carries, per repo: the repo name, silent-or-not plus commit count,
commit subjects (capped), and diffstat numbers (lines added/removed, files touched) - exactly what
`docs/privacy.md` already commits to and exactly what `RepoReportData` already holds. No goal text.
Sending a project's goal to the LLM is #29's job (goal drift), not #25's - #29 already carries the
obligation to update `docs/privacy.md` when it ships (D14). #25's grooming pass removed "the goal"
from its acceptance criteria and Constraints rather than have it silently dropped or, worse,
implemented and shipping goal text a week before the privacy document says it does.

**Reason:** `docs/privacy.md` is the document a reader is pointed to for exactly this question
("what leaves the machine when the LLM layer is on") and it gives one unambiguous answer, written
after #25 was first filed. Two documents cannot both be authoritative about the same request body;
`decisions.md`/`privacy.md`'s explicit, reasoned answer wins over an unreviewed line in #25's
original issue text, per `docs/process.md` ("do not reopen a decision without changing it here
first" - the reverse also holds: an issue does not silently reopen a decision already on record).

**Cost accepted:** None - #25 was never going to be able to send `Project.goal` without first
adding a field to `RepoReportData` and a query for it, which its own Constraints already forbid;
this only removes an AC that could not have been implemented as filed without contradicting either
`docs/privacy.md` or #25's own "fetches nothing new" rule.

**Applies to:** [#25](https://github.com/soutes/course-ai-native-zoomcamp/issues/25), [#29](https://github.com/soutes/course-ai-native-zoomcamp/issues/29)

---

## D25 - #26 owns invoking `send_batched_request`, the exact per-repo JSON shape, and the new `CoachingResult` type; per-repo "visible" degradation is a data guarantee, not a render change

**Question:** #26's filed body left three things unstated that an engineer could not proceed
without guessing. First, whether #26 calls `coach.send_batched_request` itself or only receives
an already-obtained raw response to parse - #25's own "Out of scope" says wiring the call into
`report`'s command flow "lands with #26/#27/#28," without saying which one actually makes the
call. Second, "parsed as JSON with a known shape, keyed by repo" names no concrete schema -
object of objects, object of strings, a wrapper key, all read equally as "keyed by repo."
Third, `WeeklyReportData.coaching` (`portfolio/services/render.py`) is typed `str | None` today,
but #26's own ACs require *simultaneously* tracking which repos got usable advice and which
didn't ("a missing key for one repo leaves that repo without coaching and every other repo
intact") - a single string cannot carry that distinction, and #26's Constraints forbid putting
parsing logic in `render` ("All parsing lives in the LLM module, not in `render`"), so the shape
handed to `render` has to already be resolved before it gets there. Separately, `SPEC.md`
section 4b/8b's original vision ("section prose comes from the batched LLM call") is superseded
by the shipped architecture: `render_report_markdown`'s three narrative sections
(`_went_well_lines`/`_went_wrong_lines`/`_doing_lines`) are already fully deterministic prose
with no LLM hook, and only "This week's focus" (#28, not yet built) is documented anywhere in
`backlog.md`/`SPEC.md`'s own table (`SPEC.md` line 62: "This week's focus | coaching + goal
drift") as coaching-fed - so per-repo advice text has exactly one filed consumer (#28's focus
item), not a place in the three deterministic sections.

**Decision:**
1. `portfolio/coach.py` (not `render.py`) gains one entry point, e.g.
   `get_coaching(report: WeeklyReportData, client: CoachClient) -> CoachingResult | None`, that
   itself calls `send_batched_request(client, report)`, catches `CoachRequestError` (and any
   other exception `chat_completion` can raise) as a **total failure**, and then parses the raw
   response. #26 is the first and only issue that actually invokes `send_batched_request` for a
   real report; `report.py`'s command wiring (built alongside #26/#27) calls `get_coaching` once,
   inside a `try/except` that also catches `CoachConfigError` from `build_client` - any exception
   anywhere on this path resolves to `coaching = None`, never a raised error reaching `report`'s
   own flow (per #26's own Constraint, "never raise out of the coaching path into the report
   path").
2. **Schema:** the model is asked for, and #26 parses, a **flat JSON object keyed by repo name**,
   values are plain advice strings - `{"repo-name": "advice text", ...}`. No nesting, no wrapper
   key. Repo names are matched exactly against `RepoReportData.repo` for the repos actually sent
   in the prompt (`report.repos`).
3. **New type**, defined in `portfolio/coach.py` (not `render.py`, keeping parsing logic in the
   LLM module per #26's own Constraint):
   ```python
   @dataclass
   class CoachingResult:
       advice: dict[str, str]       # repo name -> capped, non-empty advice text
       unavailable: list[str]       # repos sent, but with no usable advice
   ```
   `WeeklyReportData.coaching`'s type changes from `str | None` to `CoachingResult | None`.
   `coaching = None` means **total failure or not attempted** (unparseable JSON, wrong top-level
   JSON type, a response with no `choices[0].message.content`, a request-level exception, or
   `--no-llm`/no key at all, #27's job) - `render` already works with `coaching = None`
   unconditionally (`AGENTS.md`), and this is what makes "unparseable JSON overall leaves the
   whole report deterministic, exactly as if `--no-llm` had been passed" literally true: the two
   paths produce the identical `coaching = None` state, not merely similar-looking output.
   `coaching = CoachingResult(...)` means the JSON parsed as a valid keyed object, with each sent
   repo landing in exactly one of `advice` or `unavailable` - never silently absent from both.
4. **Parsing rules** (all in `coach.py`): read `response["choices"][0]["message"]["content"]`
   (missing/wrong shape -> total failure); strip a single leading/trailing markdown code fence
   (`` ```json `` or `` ``` ``) if present before parsing; `json.loads` (failure -> total
   failure); reject a parsed value that is not a JSON object (total failure - this is "unparseable
   JSON overall" even though `json.loads` itself succeeded, e.g. a bare JSON array or string).
   For each key in a successfully-parsed object: a key not matching a sent repo name is dropped,
   not rendered (per #26's own AC); a key matching a sent repo whose value is not a non-empty
   string goes to `unavailable`; otherwise the value is stripped and truncated to a new named
   constant `MAX_ADVICE_CHARS = 500` (with a trailing marker on truncation) and stored in
   `advice`. A sent repo whose name never appears as a key in the parsed object also lands in
   `unavailable` - the same outcome as an invalid value, so "missing key" and "malformed value"
   degrade identically.
5. **What "every degradation is visible" means for #26 specifically:** #26 guarantees the *data*
   never silently loses a repo (point 3 above - every sent repo is accounted for in `advice` or
   `unavailable`) and that the whole-report failure path is byte-for-byte the same `coaching =
   None` state `--no-llm` already produces and is already required to render sensibly (#27's AC).
   #26 does **not** itself add a "coaching unavailable" line to `render_report_markdown` - no
   section of the shipped report renders per-repo advice text or a per-repo unavailability notice
   today (the three narrative sections are deterministic and un-hooked, per the Question above),
   and the only filed consumer of `CoachingResult.advice` is #28's single focus item, which
   already carries its own "states plainly that focus needs the LLM" AC for the case it has
   nothing usable to choose from. If a future issue wants per-repo advice or unavailability text
   woven into "What went well"/"What went wrong"/"What I'm doing", it is scoped there, against
   `CoachingResult` as the data source - not invented inside #26.

**Reason:** Each of these was a real fork in how #26 gets implemented, not a stylistic choice -
guessing wrong on point 1 means `report.py`'s wiring is built twice (once in #26, redone in
#27); guessing wrong on point 2 means #26's own tests target a schema #25's prompt was never
asked to produce; guessing wrong on point 3 means either #26 is unimplementable as filed (a
`str` cannot carry per-repo pass/fail) or an engineer quietly invents a wider change to
`render.py` that its own Constraints forbid. Point 5 keeps #26 from silently absorbing UI work
(weaving advice text into the three deterministic sections) that no filed issue actually asks
for and that would contradict the shipped, deterministic-prose architecture the Question section
documents.

**Cost accepted:** `CoachingResult.unavailable` is tracked but has no rendered UI anywhere yet -
a repo whose advice degraded is only "visible" in the sense that the data says so and a test can
assert it, not in the sense that a reader of the report sees a note about that specific repo.
Closing that gap, if ever wanted, is new scope for a future issue, not a defect in #26.

**Applies to:** [#26](https://github.com/soutes/course-ai-native-zoomcamp/issues/26), [#25](https://github.com/soutes/course-ai-native-zoomcamp/issues/25), [#27](https://github.com/soutes/course-ai-native-zoomcamp/issues/27), [#28](https://github.com/soutes/course-ai-native-zoomcamp/issues/28)
