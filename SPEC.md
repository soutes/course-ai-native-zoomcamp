# SPEC — Weekly Project Feedback CLI

Working name: `weekly` (rename later)

## 1. Problem

I run several projects in parallel (course, work, side apps). I lose track of which ones
moved, which stalled, and whether the work actually pushed toward the goal I set. I do not
want to keep a manual journal.

## 2. Solution in one sentence

A CLI that first cleans up my abandoned GitHub repos, then — every Monday morning — reads the
GitHub history of the ones that survived and prints a retrospective: what went well, what went
wrong, what is mid-flight, and the one thing to focus on this week.

## 3. Scope decisions (locked)

| Question | Decision |
|---|---|
| Audience | Solo — me, across a portfolio of projects |
| Input | **GitHub REST API**, my personal account. No local clones, no manual weekly form. |
| Output surface | Django management command (markdown to stdout) **plus** web pages |
| Stack | Python 3.12+ · uv · **Django** · Rich · httpx · pytest · ruff |
| Runtime LLM | Groq free tier (OpenAI-compatible API). Provider swappable via config. |
| Week boundary | ISO week, Monday 00:00 → Sunday 23:59, local time |
| LLM calls | ONE batched call per report, all projects in a single prompt |
| Hosting / auth / DB | None in v1 |

Claude (this assistant) writes the app. The app itself at runtime calls Groq. Two different
things — do not hardcode Anthropic anywhere in `coach.py`.

**Django, and why it earns its weight.** The course requires it, but it also pays for itself
here: the ORM is what the week-over-week comparison actually needs, the admin replaces
hand-editing goals in a TOML file, and stored weeks are what make a yearly view possible. The
terminal surface survives as a management command, so nothing is lost.

The domain logic in `portfolio/services/` imports no Django and no LLM. That rule is what let
this move from a Typer CLI to a Django app by rewriting a single file, and it is what keeps
`--no-llm` trivially correct.

Explicitly OUT of scope for v1: web dashboard, email/Slack push, multi-user, task-tracker
integrations, CI.

## 3b. Moment of use — Monday morning (decided)

The report is read **Monday morning, before choosing what to work on**. That is the ritual the
whole product is designed around, and it has one hard consequence:

**The report must end pointing forward, not backward.** It closes with a decision for the week
that is starting, not a summary of the week that ended. A retro nobody acts on is a diary.

## 4. Report format — a weekly RETROSPECTIVE

The report is a retro I run on myself. Four sections, in this order:

| Section | Question it answers | Fed by |
|---|---|---|
| **What went well** | Where did I actually ship? | momentum (L1) |
| **What went wrong** | What stalled, broke, or rotted? | momentum + health (L1+L3) |
| **What I'm doing** | What am I mid-flight on right now? | unmerged branches + open PRs (L1) |
| **This week's focus** | The one thing to do with the week starting today | coaching + goal drift (L2+L4) |

Rules that keep it a retro and not a dashboard:

- Every claim cites evidence — a project name and a number. "Went well: `powerbi-tools`,
  9 commits across 4 days, README finally written." Never a bare adjective.
- **"What went wrong" must never be empty.** If every project moved, the failure is spread —
  say so. A retro with no negative section is a status report, and useless.
- "This week's focus" is capped at **one item**, phrased as an action for the coming week.
  Three suggestions = zero changed behavior.
- The focus is about **behavior**, not code. "You opened a third project before finishing the
  first" — never "refactor the parser". The LLM does not know the codebase and must not
  pretend to.
- Tone is blunt, not encouraging. No praise padding.

### Evidence layers (internal, not report sections)

Four layers, built in phases:

1. **Progress + momentum** (deterministic, no LLM)
   - per project: commits this week, days active, lines +/-, files touched
   - streak, and weeks-since-last-commit for stalled projects
2. **Coaching / next step** (LLM)
   - reads the week's commit subjects + diffstat, outputs 1–3 sentences: what to do next,
     or an explicit "kill it or ship it" when a project is stalling
3. **Code quality signal** (deterministic checks per repo)
   - missing README, missing tests dir, no CI config, TODO/FIXME count delta,
     files over N lines, uncommitted working tree
4. **Goal drift check** (LLM + config)
   - each project declares a `goal:` once in config; LLM judges whether this week's commits
     moved toward it, and says so plainly
   - **stale goal detection** (deterministic): if a goal string is unchanged for 8+ weeks and
     the project shipped nothing in that window, flag the goal itself as fiction. Points at
     the goal, not at the effort.
5. **Week-over-week delta** (deterministic, reads last week's cache)
   - every number carries its previous value. "18 commits (last week: 4)". A retro with no
     memory is a horoscope.
6. **Rhythm, not volume** (deterministic)
   - 20 commits on one Tuesday is a panic sprint; 12 across 5 days is a habit. Report active
     days and their spread, and let rhythm outrank raw totals in the prose.
7. **New repos this week** (deterministic)
   - a repo created this week gets its own callout. A portfolio that starts a lot and finishes
     little must see the starts, not only the finishes.

## 4a. Data source — GitHub REST API (decided)

Read everything over the network from my personal GitHub account. No local clones.

Endpoints used per report:

| Need | Endpoint |
|---|---|
| Discover my repos | `GET /user/repos?affiliation=owner&sort=pushed` |
| Commits in the week | `GET /repos/{owner}/{repo}/commits?since=&until=&author=` |
| Diffstat per commit | `GET /repos/{owner}/{repo}/commits/{sha}` (only when needed) |
| Unmerged branches | `GET /repos/{owner}/{repo}/branches` + compare vs default |
| Open PRs | `GET /repos/{owner}/{repo}/pulls?state=open` |
| Health files | `GET /repos/{owner}/{repo}/git/trees/{default}?recursive=1` |

Auth: Personal Access Token, scope `repo`, read from env `GITHUB_TOKEN`. Never written to
config, never logged, never sent to the LLM.

Rate limit is 5.000 req/h authenticated; a 10-project report costs roughly 40. Fine.
Still: cache responses per week under `~/.weekly/cache/{week}/` so re-running a report
costs zero requests. `--refresh` busts the cache.

Consequences accepted:

- **No dirty working tree, no local WIP.** GitHub cannot see unpushed work. "What I'm doing"
  uses unmerged branches and open PRs instead — arguably a better stall signal anyway.
- Needs network. Offline = cached weeks only.
- Repo discovery is automatic; config only carries the per-project **goal**, not paths.

## 4a-bis. Project lifecycle — how a project ENDS

A retro needs an exit, not only an entrance. Without one, a dead project pollutes "what went
wrong" forever, I learn to skim that section, and the product dies.

**No final commit is required.** Parsing commit messages for intent is fragile, I would never
remember to write one, and "it's over" is a decision, not a code event.

**Constraint that overrides convenience: this GitHub account is my public portfolio.** No
lifecycle action may make my profile look worse to a recruiter. That rules archiving out as
the default "done" signal.

Fact check, so the design rests on the truth: archiving a repo does **not** hide it. It stays
public, stays on the profile, stays searchable, and gains a `Public archive` badge. Read-only
is the only real change. The things that actually hide a repo are making it **private** or
**deleting** it.

Three end states. "Shipped" is detected from any of three signals, in this order:

| State | How I signal it | What the tool does |
|---|---|---|
| **Shipped** | 1. `weekly ack <repo> --shipped` — local only, **zero GitHub footprint** (default)<br>2. a release / `v1.0` tag exists — positive portfolio signal, shows delivery discipline<br>3. `Status: Complete` line in the README — the health check already reads the tree | Drops out of the weekly retro, appears once under "shipped", counts in the yearly tally |
| **Paused on purpose** | `weekly ack <repo> --pause "back in November"` | Silenced in "what went wrong" until that date, then it starts nagging again |
| **Dropped** | `weekly ack <repo> --drop "no longer worth it"` | Gone from the retro for good. Records the drop date and how many silent weeks passed before I admitted it |

Archiving on GitHub stays **optional and never automatic** — useful only when I want the repo
locked against accidental commits. The tool reads `archived: true` as a shipped signal if it
finds it, but never sets it on its own.

`ack` state lives in `~/.weekly/state.toml`, separate from `config.toml` — config is intent I
write by hand, state is history the tool writes.

**Dropping is not failure.** Killing a project is the decision this retro exists to provoke.
The yearly summary prints shipped and dropped side by side, with no moral difference between
them. The only bad number is the one that stays silent for months without a decision.

## 4b. LLM call strategy — BATCHED (decided)

One call per report, not one per project. Reasons:

- **Cross-project reasoning is the whole point.** Only a batched prompt can say "you spread
  across 5 repos and finished none — pick two." Per-project calls physically cannot see that.
- **Groq free tier is rate-limited per minute.** 8 projects = 8 requests = throttling. One
  request never trips it.
- **Cheaper and faster** — one round trip, one system prompt, shared context.

Cost of batching, and the mitigation:

- Long prompt → send only commit subjects + diffstat numbers, never full diffs. Cap at
  ~40 commit subjects per project, truncate oldest.
- One malformed response ruins all projects → request strict JSON keyed by project name,
  validate per key, and fall back to "no coaching available" for any missing key rather than
  failing the whole report.

Ship the deterministic report first; the LLM layer is decoration on top of it.

## 5. Config

`~/.weekly/config.toml`

```toml
[me]
github = "luiz_"                     # personal GitHub account owning all repos
token_env = "GITHUB_TOKEN"           # PAT, scope `repo`. Never stored in this file.
emails = ["soutes@gmail.com"]        # commit authorship filter on shared repos

[llm]
provider = "groq"                    # openai-compatible
base_url = "https://api.groq.com/openai/v1"
model    = "llama-3.3-70b-versatile"
api_key_env = "GROQ_API_KEY"

[[project]]
repo = "ai_native_dev_zoomcamp"      # repo name on GitHub, not a local path
goal = "Finish the DataTalks AI dev tools course, one homework per week"

[[project]]
repo = "powerbi-tools"
goal = "..."
```

Repos are discovered automatically from the GitHub account. A `[[project]]` entry exists only
to attach a **goal** (and to opt a repo in when `track = "listed"`). Repos with no entry still
appear in momentum stats but get no goal-drift judgement.

## 6. CLI surface

```
weekly triage                       # ONE-TIME portfolio curation: showcase / hide / delete
weekly triage --apply               # make the HIDE pile private. Never deletes, never archives

weekly report                       # current ISO week (Mon-Sun), all tracked repos
weekly report --week 2026-W35
weekly report --repo X
weekly report --no-llm              # deterministic layers only, zero API cost
weekly report --last                # reprint last cached report, no network, no LLM
weekly report --refresh             # bust the cache, re-fetch from GitHub

weekly ack <repo> --pause "reason" [--until 2026-11-01]
weekly ack <repo> --drop  "reason"
weekly ack <repo> --shipped         # local only, zero GitHub footprint

weekly projects                     # tracked / paused / dropped / shipped
weekly year                         # yearly tally: shipped vs dropped vs silent
```

Report is markdown on stdout. `--out reports/2026-W36.md` optional later.

## 7. Architecture

```
weekly/
  cli.py          Typer commands
  config.py       load/validate config.toml
  state.py        read/write state.toml (paused, dropped, shipped, ack dates)
  github.py       GitHub REST client -> RepoWeek per repo (httpx + cache)
  cache.py        per-week response cache under ~/.weekly/cache/{week}/
  health.py       deterministic quality checks over the repo tree
  triage.py       one-time portfolio inventory + cleanup plan
  coach.py        ONE batched OpenAI-compatible call (Groq) -> per-repo JSON
  render.py       stats + coaching -> markdown (Rich for terminal)
  models.py       dataclasses: Repo, RepoWeek, HealthReport, Coaching, WeekReport
```

Key rules:

- `github`, `health` and `triage` never call the LLM.
- `coach` receives only structured data and never touches the network except its own endpoint.
- `render` works with `coaching = None` — that is exactly what `--no-llm` produces.

This keeps `--no-llm` trivially correct and the whole thing testable from fixtures.

## 8. Build phases

- **P0 — `weekly triage`.** One-time portfolio curation. Lists every repo with last-push age,
  commit count and README status; proposes showcase / hide / delete; `--apply` makes the hide
  pile private. Delivers value on day one, before any weekly ritual exists, and shrinks the
  portfolio the rest of the tool has to reason about.
- **P1** — config + github client + cache + markdown render. Deterministic momentum report.
  No LLM.
- **P2** — health checks (layer 3) + `ack` lifecycle commands.
- **P3** — week-over-week delta (layer 5) and rhythm (layer 6). Needs two cached weeks, so it
  lands naturally here.
- **P4** — coaching (layer 2) via Groq, guarded by `--no-llm`.
- **P5** — goal drift + stale goals (layer 4), reusing the same batched call.
- **P6** — `weekly year`, the shipped-vs-dropped tally.

Stop after each phase and ship something runnable.

## 8a. `weekly triage` — portfolio curation (P0)

Reality: the account holds a pile of repos from courses I started and abandoned. They must be
dealt with **before** the weekly ritual means anything — a retro reporting on 30 dead course
repos is noise, and I stop reading it in two weeks.

But the sorting question is **not** "alive or dead". This account is my portfolio, so it is:
**does this repo help me or hurt me in an interview?** A finished course repo with a good
README is an asset even after a year of silence. A 3-commit tutorial fork is not neutral — it
is noise that dilutes the good ones and makes a recruiter scroll past them.

```
$ weekly triage

34 repos · 4 active · 30 untouched for 90+ days

  SHOWCASE (13)   stays public — the portfolio
    ml-zoomcamp-2024        1y2m ago   62 commits · README · completed
    powerbi-tools              9d ago    7 commits · README
    ! missing description and topics — polish these
    ...

  HIDE (17)       make private — dead weight
    fastapi-tutorial        2y1m ago    3 commits · no README · fork
    ...

  DELETE (0)      suggested only, never automated
```

Classification is **deterministic**, no LLM: last push age, commit count, README present,
description present, releases/tags, is fork, is archived.

- SHOWCASE = README present AND commits >= N (evidence I finished something)
- HIDE = commits < N OR no README OR bare fork with no own commits

`--apply` does exactly two things:

1. **HIDE** → `PATCH /repos/{owner}/{repo}` with `private: true`. Reversible, code preserved,
   gone from the public profile.
2. Records every decision and its date in `state.toml`.

It **never deletes a repository**, and it **never archives one** — archiving does not hide
anything, so it solves nothing here. Deletion stays a manual decision in the GitHub UI.

Two warnings the command must print **before** `--apply` runs:

- Converting public → private **loses that repo's stars, forks and watchers**, permanently.
- Contributions from a private repo only stay on the public contribution graph if
  *Settings → Profile → Include private contributions on my profile* is enabled. Turn it on
  first, or the green squares from those repos disappear from public view.

After triage, the portfolio is small and the weekly retro starts clean. From then on the tool
governs **new** projects: the ones created from this point forward.

Config gets a baseline so history stays honest:

```toml
[report]
baseline = "2026-09-07"   # first Monday the ritual is real; triage covers everything before
```

## 8b. Report skeleton (target output)

```markdown
# Week 2026-W36 — retro
Monday 2026-09-07 · 5 tracked · 3 moved · 2 stalled · 41 commits (last week: 12)

⚠ 2 projects with no commit for 4+ weeks

## What went well
- **ai-native-dev-zoomcamp** — 18 commits, 5 active days. Homework 1 shipped.
- **powerbi-tools** — README + tests added, first CI config.

## What went wrong
- **oil-sales-dashboard** — 0 commits, 4th week silent. Goal was "ship the KPI page".
- **weekly** — 9 uncommitted files sitting dirty since Tuesday.

## What I'm doing
- **ai-native-dev-zoomcamp** — on branch `hw2-scraper`, 3 WIP commits, not merged.

## This week's focus
Close `oil-sales-dashboard` or run `weekly ack oil-sales-dashboard --drop`. Four silent
weeks is a decision you already made without saying it out loud. Decide it today, then
spend the week on the course.
```

Header stat line is deterministic. Section prose comes from the batched LLM call, and
degrades to plain bullet lists under `--no-llm`.

## 9. Definition of done

**P0 done:** `weekly triage` classified all my repos, I applied the plan, and my public profile
now shows only work I would point a recruiter at.

**v1 done:** on a Monday morning, `weekly report` prints the four retro sections, every claim
backed by a repo name and a number compared to last week, ending in one action for the week
that is starting — with no manual input from me during that week.

**Real done:** I run it three Mondays in a row without being reminded.

## 10. Open questions

- Groq model id may drift — keep it in config, never in code.
- Private repos: included (PAT has `repo` scope). Forks and archived repos: excluded by
  default.
- Commit subjects of **private** repos get sent to Groq. Accepted for a personal tool; if that
  ever changes, add `private = "stats_only"` per project.

## 11. Course constraint

This project follows the DataTalks "AI Dev Tools 2026" course pace
(https://courses.datatalks.club/ai-dev-tools-2026/). Do not jump ahead of the module being
taught, even when a later phase is technically easy. Phases above map roughly to weeks.
