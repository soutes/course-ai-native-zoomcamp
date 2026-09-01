# FEATURES — `weekly`

## The 4 features the spec settled on

*(homework answer — the whole product in four lines)*

1. **Portfolio triage** — a one-time pass over every repo in my GitHub account that sorts them
   into showcase / hide / delete and makes the dead weight private, so the account reads as a
   portfolio instead of a graveyard of abandoned courses.
2. **Weekly retrospective** — every Monday morning, a report built from GitHub history alone
   (no manual journaling) with four sections: what went well, what went wrong, what I'm
   mid-flight on, and the one thing to focus on this week.
3. **Project lifecycle tracking** — an explicit way to end a project (shipped / paused /
   dropped) so finished and abandoned work leaves the report instead of polluting it forever.
4. **AI coaching** — a single batched LLM call over the whole portfolio that names
   behavioral patterns no per-project view can see, such as starting a third project before
   finishing the first.

Everything below is the implementation backlog for those four.

---

Full feature inventory, grouped by build phase. Each phase ships something runnable.
See [SPEC.md](SPEC.md) for the reasoning behind each decision.

---

## P0 — Portfolio curation (`weekly triage`)

One-time cleanup, run before the weekly ritual has any meaning.

| # | Feature | Notes |
|---|---|---|
| 0.1 | **Repo inventory** | Fetch every repo owned by the account via GitHub REST API |
| 0.2 | **Deterministic classification** | SHOWCASE / HIDE / DELETE. No LLM — last push age, commit count, README, description, releases, fork status |
| 0.3 | **Dry-run by default** | `weekly triage` only prints a plan. Nothing changes without `--apply` |
| 0.4 | **Make private on apply** | HIDE pile → `private: true`. Reversible, code preserved, off the public profile |
| 0.5 | **Never delete, never archive** | Deletion is manual in the GitHub UI. Archiving does not hide a repo, so it solves nothing |
| 0.6 | **Pre-apply warnings** | Public→private loses stars/forks; private contributions need the profile toggle enabled |
| 0.7 | **Polish hints** | For SHOWCASE repos: flag missing README, description, topics, or license |
| 0.8 | **Decision log** | Every applied decision recorded with its date in `state.toml` |
| 0.9 | **Response cache** | GitHub responses cached so re-running the plan costs zero requests |

## P1 — Deterministic weekly report

| # | Feature | Notes |
|---|---|---|
| 1.1 | **ISO week window** | Monday 00:00 → Sunday 23:59, local time |
| 1.2 | **Commits per repo** | Filtered by my authorship emails, so shared repos count only my work |
| 1.3 | **Momentum stats** | Commits, active days, lines +/-, files touched |
| 1.4 | **Stalled detection** | Weeks since last commit. The headline number of the whole tool |
| 1.5 | **Mid-flight work** | Unmerged branches and open PRs |
| 1.6 | **New repos this week** | A portfolio that starts a lot must see its starts |
| 1.7 | **Four-section retro render** | Went well / went wrong / doing / this week's focus |
| 1.8 | **Evidence rule** | Every claim carries a repo name and a number |
| 1.9 | **Markdown to stdout** | Rich for terminal, plain markdown with `--out` |

## P2 — Health checks and lifecycle

| # | Feature | Notes |
|---|---|---|
| 2.1 | **Repo health signals** | Missing README, no tests, no CI config, no license, no description |
| 2.2 | **`weekly ack --shipped`** | Local only, zero GitHub footprint |
| 2.3 | **Shipped auto-detection** | A release/tag or a `Status: Complete` README line also counts |
| 2.4 | **`weekly ack --pause`** | Silenced until a date, then it starts nagging again |
| 2.5 | **`weekly ack --drop`** | Records the drop date and the silent weeks that preceded it |
| 2.6 | **`weekly projects`** | Tracked / paused / dropped / shipped |

## P3 — Memory

| # | Feature | Notes |
|---|---|---|
| 3.1 | **Week-over-week delta** | Every number carries last week's value. A retro without memory is a horoscope |
| 3.2 | **Rhythm over volume** | Active-day spread outranks raw commit totals |
| 3.3 | **Abandoned counter in header** | `2 projects with no commit for 4+ weeks`. The confrontation line |
| 3.4 | **`weekly report --last`** | Reprint the cached report. No network, no LLM |

## P4 — Coaching (LLM)

| # | Feature | Notes |
|---|---|---|
| 4.1 | **One batched call** | All repos in a single Groq request. Only a batched prompt sees portfolio-wide patterns |
| 4.2 | **Provider-agnostic client** | OpenAI-compatible. Groq at runtime; never hardcode a vendor |
| 4.3 | **`--no-llm`** | Full deterministic report with zero API dependency |
| 4.4 | **Strict JSON with per-repo fallback** | One bad key degrades one repo, never the whole report |
| 4.5 | **Behavior-only advice** | "You opened a third project before finishing the first" — never "refactor the parser" |
| 4.6 | **One focus item, forward-looking** | Read Monday morning, so it ends in a decision for the week starting today |

## P5 — Goals

| # | Feature | Notes |
|---|---|---|
| 5.1 | **Goal per repo** | One free-text sentence in config |
| 5.2 | **Goal drift judgement** | Did this week's commits move toward the stated goal? |
| 5.3 | **Stale goal detection** | Unchanged 8+ weeks with nothing shipped = the goal is fiction. Points at the goal, not the effort |

## P6 — Yearly view

| # | Feature | Notes |
|---|---|---|
| 6.1 | **`weekly year`** | Shipped vs dropped vs silent, side by side, no moral difference between the first two |
| 6.2 | **Time-to-decision** | How many silent weeks passed before I admitted a project was over |

---

## Explicitly rejected

| Feature | Why not |
|---|---|
| Streaks, badges, gamification | A streak rewards an empty Sunday-midnight commit. It corrupts the data the tool measures |
| Scoring projects 0–100 | Invented precision. Prose beats a fake metric |
| LLM code-quality review | Slow, costly, and a linter already does it. Deterministic checks give 80% for 0 tokens |
| Per-commit LLM summaries | Commit subjects are already summaries |
| Terminal charts / sparklines | Momentum is six numbers. A table wins |
| OKRs with deadlines and percentages | A second management system to maintain. A one-line goal is the ceiling |
| Web dashboard, email/Slack push | Out of scope. CLI was chosen deliberately |
