# BACKLOG — `weekly`

Groomed task list derived from [SPEC.md](SPEC.md) and [FEATURES.md](FEATURES.md).

Each task is small enough to finish in one sitting, states its own done condition, and leaves
the app runnable. Tasks are worked in order; the phase headings map to the build phases in the
spec.

Status: `[ ]` todo · `[x]` done · `[~]` in progress

Every task has a matching GitHub issue with the same number: task 14 is issue #14.
Tasks are worked top to bottom, which is not the same as numeric order - a task split out
of grooming later gets a higher number but stays inside the phase it belongs to.

---

## Phase 0 — Portfolio curation (CLI core)

- [x] **1. Scaffold the Django project and the `portfolio` app.** ([#1](https://github.com/soutes/course-ai-native-zoomcamp/issues/1))
  `django-admin startproject config .`, `manage.py startapp portfolio`, register `portfolio`
  in `INSTALLED_APPS`. Done when `manage.py runserver` boots and `manage.py check` is clean.
- [x] **2. Read configuration from the environment.** ([#2](https://github.com/soutes/course-ai-native-zoomcamp/issues/2))
  `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL` via `.env` in development. Refuse to
  start on a default key when `DEBUG` is off. Done when `.env.example` exists and settings
  import with no hardcoded secret.
- [x] **3. GitHub REST client.** ([#3](https://github.com/soutes/course-ai-native-zoomcamp/issues/3))
  List owned repos, count commits via the `Link: rel="last"` header, detect README and
  releases. Done when a token in `GITHUB_TOKEN` returns the live repo list.
- [x] **4. Deterministic triage classifier.** ([#4](https://github.com/soutes/course-ai-native-zoomcamp/issues/4))
  Sort repos into SHOWCASE / HIDE / DELETE / SKIP from commit count, README, and fork status.
  Done when the rules are covered by unit tests running off fixtures, no network.
- [x] **5. On-disk response cache.** ([#5](https://github.com/soutes/course-ai-native-zoomcamp/issues/5))
  Cache GitHub responses so a repeated run costs zero requests; `--refresh` clears it.
  Done when the second run of the plan makes no HTTP calls.
- [x] **6. `triage` management command, dry run by default.** ([#6](https://github.com/soutes/course-ai-native-zoomcamp/issues/6))
  `manage.py triage` prints the plan and changes nothing. Done when the three piles render
  with repo name, age, and reasons.
- [x] **7. `--apply` makes the HIDE pile private.** ([#7](https://github.com/soutes/course-ai-native-zoomcamp/issues/7))
  Print the stars/forks and contribution-graph warnings, prompt for confirmation, then
  `PATCH /repos/{owner}/{repo}` with `private: true`. Never deletes, never archives.
  Done when a decision is applied and recorded.
  *Written, but not yet verified against a live account - needs a real token.*
- [x] **8. Persist triage decisions.** ([#8](https://github.com/soutes/course-ai-native-zoomcamp/issues/8))
  `TriageRun` and `TriageDecision` models replacing `state.toml`. Done when an applied run
  survives a restart and is visible in the Django admin.
- [x] **9. Polish hints for kept repos.** ([#9](https://github.com/soutes/course-ai-native-zoomcamp/issues/9))
  Flag missing description, topics, or license on SHOWCASE repos. Done when the hints appear
  beside the repo in the plan output.

## Phase 1 — The weekly report

- [x] **10. `Project` model and the Django admin.** ([#10](https://github.com/soutes/course-ai-native-zoomcamp/issues/10))
  Repo name, goal, tracked flag, lifecycle status. Done when goals are editable at `/admin/`
  instead of by hand in a config file.
- [x] **11. ISO week window helper.** ([#11](https://github.com/soutes/course-ai-native-zoomcamp/issues/11))
  Monday 00:00 to Sunday 23:59 local, plus parsing of `2026-W36`. Done when the boundaries are
  unit-tested, including the year-end rollover.
- [ ] **12. Fetch a week of commits per repo.** ([#12](https://github.com/soutes/course-ai-native-zoomcamp/issues/12))
  Filtered by my authorship emails so shared repos count only my work. Done when the count
  matches what GitHub's own UI reports for the same week.
- [ ] **13. Momentum stats.** ([#13](https://github.com/soutes/course-ai-native-zoomcamp/issues/13))
  Commits, active days, lines added and removed, files touched. Done when a `RepoWeek` row is
  produced per tracked repo.
- [ ] **14. Stalled detection.** ([#14](https://github.com/soutes/course-ai-native-zoomcamp/issues/14))
  Weeks since the last commit, per repo. Done when a repo silent for a month is flagged.
- [ ] **15. Mid-flight work.** ([#15](https://github.com/soutes/course-ai-native-zoomcamp/issues/15))
  Unmerged branches and open PRs per repo. Done when both appear in the report data.
- [ ] **16. `report` management command.** ([#16](https://github.com/soutes/course-ai-native-zoomcamp/issues/16))
  Render the four retro sections as markdown on stdout. Done when every claim carries a repo
  name and a number.
- [ ] **17. Retro web page.** ([#17](https://github.com/soutes/course-ai-native-zoomcamp/issues/17))
  A Django view and template for one week's retro, with a list of past weeks. Done when the
  same report readable in the terminal is readable at `/retro/2026-W36/`.
- [ ] **33. New repos this week.** ([#33](https://github.com/soutes/course-ai-native-zoomcamp/issues/33))
  A repo created during the reported week gets its own callout. Done when a week with a new
  repo says so, and a week without one shows nothing.
- [ ] **36. Current-week dashboard page.** ([#36](https://github.com/soutes/course-ai-native-zoomcamp/issues/36))
  A landing page at `/` showing the current week, not only the project list. Done when the
  page renders from stored data with no network call.

## Phase 2 — Health and lifecycle

- [ ] **18. Repo health checks.** ([#18](https://github.com/soutes/course-ai-native-zoomcamp/issues/18))
  Missing README, tests, CI config, license, description. Done when the signals feed the
  "what went wrong" section.
- [ ] **19. Lifecycle transitions.** ([#19](https://github.com/soutes/course-ai-native-zoomcamp/issues/19))
  `manage.py ack <repo> --shipped|--pause|--drop`, plus admin actions for the same.
  Done when an ended project leaves the weekly report and keeps its record.
- [ ] **20. Shipped auto-detection.** ([#20](https://github.com/soutes/course-ai-native-zoomcamp/issues/20))
  A release, a tag, or a `Status: Complete` README line also counts as shipped. Done when a
  released repo drops out without any manual step.
- [ ] **34. `projects` management command.** ([#34](https://github.com/soutes/course-ai-native-zoomcamp/issues/34))
  List tracked, paused, shipped and dropped projects. Done when the portfolio is readable
  without the admin, with no network call.

## Phase 3 — Memory

- [ ] **21. Week-over-week deltas.** ([#21](https://github.com/soutes/course-ai-native-zoomcamp/issues/21))
  Every number carries last week's value, read from the stored `RepoWeek` rows. Done when the
  header line shows both weeks.
- [ ] **22. Rhythm over volume.** ([#22](https://github.com/soutes/course-ai-native-zoomcamp/issues/22))
  Report the spread of active days, and let it outrank raw totals in the prose. Done when a
  one-day burst and a five-day habit with equal commit counts read differently.
- [ ] **23. Abandoned counter in the header.** ([#23](https://github.com/soutes/course-ai-native-zoomcamp/issues/23))
  `2 projects with no commit for 4+ weeks`. Done when the count appears above the sections.
- [ ] **35. `report --last`, reprint from storage.** ([#35](https://github.com/soutes/course-ai-native-zoomcamp/issues/35))
  Reprint the most recent report. No network, no LLM, no token. Done when it renders with
  both keys unset.

## Phase 4 — Coaching

- [ ] **24. OpenAI-compatible client pointed at Groq.** ([#24](https://github.com/soutes/course-ai-native-zoomcamp/issues/24))
  Base URL, model, and key all from the environment; no vendor hardcoded. Done when the same
  code would run against another provider by changing env vars only.
- [ ] **25. One batched call for the whole portfolio.** ([#25](https://github.com/soutes/course-ai-native-zoomcamp/issues/25))
  Commit subjects and diffstat numbers only, never full diffs; capped per repo. Done when a
  report with eight repos makes exactly one request.
- [ ] **26. Strict JSON with per-repo fallback.** ([#26](https://github.com/soutes/course-ai-native-zoomcamp/issues/26))
  A malformed or missing key degrades one repo, never the whole report. Done when a corrupted
  response still renders a complete report.
- [ ] **27. `--no-llm` flag.** ([#27](https://github.com/soutes/course-ai-native-zoomcamp/issues/27))
  Full deterministic report with zero API dependency. Done when the report renders with the
  key unset.
- [ ] **28. The single forward-looking focus item.** ([#28](https://github.com/soutes/course-ai-native-zoomcamp/issues/28))
  One action for the week starting today, about behavior rather than code. Done when the
  report ends with exactly one.

## Phase 5 — Goals

- [ ] **29. Goal drift judgement.** ([#29](https://github.com/soutes/course-ai-native-zoomcamp/issues/29))
  Did this week's commits move toward the stated goal? Done when a week of unrelated work is
  called out as drift.
- [ ] **30. Stale goal detection.** ([#30](https://github.com/soutes/course-ai-native-zoomcamp/issues/30))
  A goal unchanged for eight weeks with nothing shipped is flagged as fiction. Done when the
  check runs without the LLM.

## Phase 6 — Yearly view

- [ ] **31. `year` command and page.** ([#31](https://github.com/soutes/course-ai-native-zoomcamp/issues/31))
  Shipped, dropped, and silent side by side. Done when a full year renders from stored data.
- [ ] **32. Time-to-decision.** ([#32](https://github.com/soutes/course-ai-native-zoomcamp/issues/32))
  How many silent weeks passed before a project was admitted over. Done when the number
  appears next to each dropped project.

---

## Cross-cutting

- [x] **Tests run with `uv run pytest`.**
- [x] **Linting with `uv run ruff check .` and `uv run ruff format .`.**
- [x] **README documents setup, the token, and every command.**
- [ ] **A dashboard page showing the current week, not only the project list.** - now task 36 ([#36](https://github.com/soutes/course-ai-native-zoomcamp/issues/36))
- [x] **37. CI on GitHub Actions.** ([#37](https://github.com/soutes/course-ai-native-zoomcamp/issues/37))
  `uv run pytest` and `uv run ruff check .` on push and pull request. Done when main is green.
- [x] **38. `seed_demo` management command.** ([#38](https://github.com/soutes/course-ai-native-zoomcamp/issues/38))
  A realistic portfolio, offline, no token needed. Done when `seed_demo` then `runserver` shows
  a populated dashboard on a fresh database.
- [ ] **39. CI polish: `manage.py check`, README badge, branch protection.** ([#39](https://github.com/soutes/course-ai-native-zoomcamp/issues/39)) `post-mvp`
  Out of scope split from #37 while grooming. Branch protection is a repo-settings change the
  owner makes by hand, not an agent write.
- [ ] **40. `seed_demo`: seed `RepoWeek` and `WeeklyReport` once #13/#16/#36 land.** ([#40](https://github.com/soutes/course-ai-native-zoomcamp/issues/40)) `post-mvp`
  Out of scope split from #38 while grooming - those models don't exist yet. See decisions.md D7.
