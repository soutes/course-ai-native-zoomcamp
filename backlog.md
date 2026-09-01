# BACKLOG — `weekly`

Groomed task list derived from [SPEC.md](SPEC.md) and [FEATURES.md](FEATURES.md).

Each task is small enough to finish in one sitting, states its own done condition, and leaves
the app runnable. Tasks are worked in order; the phase headings map to the build phases in the
spec.

Status: `[ ]` todo · `[x]` done · `[~]` in progress

---

## Phase 0 — Portfolio curation (CLI core)

- [x] **1. Scaffold the Django project and the `portfolio` app.**
  `django-admin startproject config .`, `manage.py startapp portfolio`, register `portfolio`
  in `INSTALLED_APPS`. Done when `manage.py runserver` boots and `manage.py check` is clean.
- [x] **2. Read configuration from the environment.**
  `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL` via `.env` in development. Refuse to
  start on a default key when `DEBUG` is off. Done when `.env.example` exists and settings
  import with no hardcoded secret.
- [x] **3. GitHub REST client.**
  List owned repos, count commits via the `Link: rel="last"` header, detect README and
  releases. Done when a token in `GITHUB_TOKEN` returns the live repo list.
- [x] **4. Deterministic triage classifier.**
  Sort repos into SHOWCASE / HIDE / DELETE / SKIP from commit count, README, and fork status.
  Done when the rules are covered by unit tests running off fixtures, no network.
- [x] **5. On-disk response cache.**
  Cache GitHub responses so a repeated run costs zero requests; `--refresh` clears it.
  Done when the second run of the plan makes no HTTP calls.
- [x] **6. `triage` management command, dry run by default.**
  `manage.py triage` prints the plan and changes nothing. Done when the three piles render
  with repo name, age, and reasons.
- [~] **7. `--apply` makes the HIDE pile private.**
  Print the stars/forks and contribution-graph warnings, prompt for confirmation, then
  `PATCH /repos/{owner}/{repo}` with `private: true`. Never deletes, never archives.
  Done when a decision is applied and recorded.
  *Written, but not yet verified against a live account - needs a real token.*
- [x] **8. Persist triage decisions.**
  `TriageRun` and `TriageDecision` models replacing `state.toml`. Done when an applied run
  survives a restart and is visible in the Django admin.
- [x] **9. Polish hints for kept repos.**
  Flag missing description, topics, or license on SHOWCASE repos. Done when the hints appear
  beside the repo in the plan output.

## Phase 1 — The weekly report

- [x] **10. `Project` model and the Django admin.**
  Repo name, goal, tracked flag, lifecycle status. Done when goals are editable at `/admin/`
  instead of by hand in a config file.
- [ ] **11. ISO week window helper.**
  Monday 00:00 to Sunday 23:59 local, plus parsing of `2026-W36`. Done when the boundaries are
  unit-tested, including the year-end rollover.
- [ ] **12. Fetch a week of commits per repo.**
  Filtered by my authorship emails so shared repos count only my work. Done when the count
  matches what GitHub's own UI reports for the same week.
- [ ] **13. Momentum stats.**
  Commits, active days, lines added and removed, files touched. Done when a `RepoWeek` row is
  produced per tracked repo.
- [ ] **14. Stalled detection.**
  Weeks since the last commit, per repo. Done when a repo silent for a month is flagged.
- [ ] **15. Mid-flight work.**
  Unmerged branches and open PRs per repo. Done when both appear in the report data.
- [ ] **16. `report` management command.**
  Render the four retro sections as markdown on stdout. Done when every claim carries a repo
  name and a number.
- [ ] **17. Retro web page.**
  A Django view and template for one week's retro, with a list of past weeks. Done when the
  same report readable in the terminal is readable at `/retro/2026-W36/`.

## Phase 2 — Health and lifecycle

- [ ] **18. Repo health checks.**
  Missing README, tests, CI config, license, description. Done when the signals feed the
  "what went wrong" section.
- [ ] **19. Lifecycle transitions.**
  `manage.py ack <repo> --shipped|--pause|--drop`, plus admin actions for the same.
  Done when an ended project leaves the weekly report and keeps its record.
- [ ] **20. Shipped auto-detection.**
  A release, a tag, or a `Status: Complete` README line also counts as shipped. Done when a
  released repo drops out without any manual step.

## Phase 3 — Memory

- [ ] **21. Week-over-week deltas.**
  Every number carries last week's value, read from the stored `RepoWeek` rows. Done when the
  header line shows both weeks.
- [ ] **22. Rhythm over volume.**
  Report the spread of active days, and let it outrank raw totals in the prose. Done when a
  one-day burst and a five-day habit with equal commit counts read differently.
- [ ] **23. Abandoned counter in the header.**
  `2 projects with no commit for 4+ weeks`. Done when the count appears above the sections.

## Phase 4 — Coaching

- [ ] **24. OpenAI-compatible client pointed at Groq.**
  Base URL, model, and key all from the environment; no vendor hardcoded. Done when the same
  code would run against another provider by changing env vars only.
- [ ] **25. One batched call for the whole portfolio.**
  Commit subjects and diffstat numbers only, never full diffs; capped per repo. Done when a
  report with eight repos makes exactly one request.
- [ ] **26. Strict JSON with per-repo fallback.**
  A malformed or missing key degrades one repo, never the whole report. Done when a corrupted
  response still renders a complete report.
- [ ] **27. `--no-llm` flag.**
  Full deterministic report with zero API dependency. Done when the report renders with the
  key unset.
- [ ] **28. The single forward-looking focus item.**
  One action for the week starting today, about behavior rather than code. Done when the
  report ends with exactly one.

## Phase 5 — Goals

- [ ] **29. Goal drift judgement.**
  Did this week's commits move toward the stated goal? Done when a week of unrelated work is
  called out as drift.
- [ ] **30. Stale goal detection.**
  A goal unchanged for eight weeks with nothing shipped is flagged as fiction. Done when the
  check runs without the LLM.

## Phase 6 — Yearly view

- [ ] **31. `year` command and page.**
  Shipped, dropped, and silent side by side. Done when a full year renders from stored data.
- [ ] **32. Time-to-decision.**
  How many silent weeks passed before a project was admitted over. Done when the number
  appears next to each dropped project.

---

## Cross-cutting

- [x] **Tests run with `uv run pytest`.**
- [x] **Linting with `uv run ruff check .` and `uv run ruff format .`.**
- [x] **README documents setup, the token, and every command.**
- [ ] **A dashboard page showing the current week, not only the project list.**
