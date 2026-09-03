# weekly

[![CI](https://github.com/soutes/course-ai-native-zoomcamp/actions/workflows/ci.yml/badge.svg)](https://github.com/soutes/course-ai-native-zoomcamp/actions/workflows/ci.yml)

> Projeto de avaliação dos projetos com base nos commits que eu fiz ao longo da semana.

A Monday-morning retrospective over my GitHub project portfolio.

I run several projects in parallel and lose track of which ones moved, which stalled, and
whether the work actually pushed toward the goal I set. `weekly` reads GitHub history — no
manual journaling — and produces a retro: what went well, what went wrong, what I'm mid-flight
on, and the one thing to focus on this week.

Built alongside the [DataTalks AI Dev Tools 2026](https://courses.datatalks.club/ai-dev-tools-2026/)
course, spec first, one backlog task at a time.

## The four features

1. **Portfolio triage** — sort every repo into showcase / hide / delete, and make the dead
   weight private, so the account reads as a portfolio instead of a graveyard of abandoned
   courses.
2. **Weekly retrospective** — four sections, built from GitHub history alone.
3. **Project lifecycle tracking** — shipped / paused / dropped, so ended work leaves the report.
4. **AI coaching** — one batched LLM call that names portfolio-wide behavior patterns.

[SPEC.md](SPEC.md) holds the reasoning, [FEATURES.md](FEATURES.md) the full inventory, and
[backlog.md](backlog.md) the groomed task list being worked in order.

## Privacy

[docs/privacy.md](docs/privacy.md) states exactly what leaves the machine when the AI coaching
feature is enabled, and where it goes.

## Status

Phase 0 (portfolio triage) is built and the Django project is up. The weekly report itself is
task 11 onward in the backlog.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- SQLite by default; PostgreSQL optional via `DATABASE_URL`

## Getting started

```bash
uv sync
cp .env.example .env
uv run manage.py migrate
uv run manage.py runserver
```

Configuration comes entirely from the environment — `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`,
`DATABASE_URL`, and the GitHub credentials. In development those are read from `.env`, which is
git-ignored. `SECRET_KEY` has no fallback when `DEBUG` is off: the app refuses to start rather
than run on a default key.

For the GitHub calls, create a Personal Access Token with the `repo` scope at
<https://github.com/settings/tokens> and put it in `.env`:

```
GITHUB_USER=your-username
GITHUB_TOKEN=ghp_your_token_here
```

Create an admin user to edit project goals at `/admin/`:

```bash
uv run manage.py createsuperuser
```

## Commands

| Command | What it does |
|---|---|
| `uv run manage.py runserver` | Start the development server at <http://127.0.0.1:8000/> |
| `uv run manage.py triage` | Print the portfolio curation plan. Changes nothing |
| `uv run manage.py triage --apply` | Make the HIDE pile private, after a confirmation |
| `uv run manage.py migrate` | Apply database migrations |
| `uv run pytest` | Run the tests |
| `uv run ruff check .` | Lint |
| `uv run ruff format .` | Format |

### `triage` options

| Flag | Effect |
|---|---|
| `--apply` | Execute the plan. Prompts before touching anything |
| `--refresh` | Ignore the cache and re-fetch from GitHub |
| `--min-commits N` | Override the portfolio threshold for this run |
| `--yes` | Skip the confirmation prompt |

Repos are sorted into:

- **SHOWCASE** — has a README and at least `TRIAGE_MIN_COMMITS` commits. Stays public.
- **HIDE** — too few commits, or no README. Candidate to make private.
- **DELETE** — a fork with no commits of my own. Suggested only, never automated.
- **SKIP** — already private.

### What `--apply` will never do

- It never deletes a repository. Deletion stays a manual decision in the GitHub UI.
- It never archives one. Archiving does **not** hide a repo — an archived repo stays public,
  stays on your profile, and stays searchable, so it solves nothing here.

### Two warnings before you apply

1. Making a public repo private **permanently loses its stars, forks and watchers.**
2. Contributions from private repos only stay on your public contribution graph if
   *Settings → Profile → Include private contributions on my profile* is enabled. Turn it on
   first, or those green squares disappear from public view.

## Layout

```
config/                 Django project: settings, root URLs
portfolio/              the app
  models.py             Project, TriageRun, TriageDecision
  views.py              the dashboard
  admin.py              where goals get edited
  services/             domain logic, no Django imports
    github.py           the only module that touches the network
    triage.py           the classification rules
    types.py            plain dataclasses
    cache.py            on-disk response cache
    render.py           terminal output
  management/commands/
    triage.py           manage.py triage
tests/                  fixtures-only, no network
```

`services/` holds the rules and knows nothing about Django or HTTP delivery. That separation is
why this started life as a Typer CLI and became a Django app by rewriting one file.

GitHub responses are cached under `.cache/`, so re-running the plan costs zero API requests.
