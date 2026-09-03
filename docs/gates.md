# Gates

The order this project is built in. One gate at a time, no overlap. A gate is
finished when its exit condition is true, not when the work "looks done".

The exit conditions are written so a loop can check them. `/goal <exit
condition>` is a valid way to run a gate.

Background on why the roles and the lifecycle exist is in
[process.md](process.md). The calls already made are in
[decisions.md](decisions.md).

---

## Gate 0 - The process agrees with itself

No code. Make the documents an agent reads consistent, so nothing downstream
inherits a contradiction.

- `process.md` Roles points at `docs/team/software-engineer.md` and
  `docs/team/qa-engineer.md`, not `_docs/`
- `process.md` Lifecycle runs one issue per run and says so
- `AGENTS.md` and `process.md` agree on who closes an issue
- `docs/outdated/` holds the superseded material, and `process.md` says it
  loses to an issue or to `decisions.md`

Exit: `git grep -n '_docs/' -- ':!docs/gates.md'` returns nothing (this file
names the old path as an example, so it is excluded from its own check), and
the working tree is committed.

## Gate 1 - Scope is a label, not an opinion

Two labels on GitHub, applied to every open issue. Nothing is deleted from the
backlog - work that is not in the MVP is deferred, in writing, where the
orchestrator can see it.

- `mvp` - green, "Part of the MVP scope"
- `post-mvp` - purple, "Deferred until after the MVP ships"
- MVP is Phase 0 and Phase 1: issues 7, 11-17, 33, 36
- Everything else open is `post-mvp`
- `process.md` gains a Scope section stating the rule and the MVP boundary
- The orchestrator never picks up a `post-mvp` issue, even when it is next

Why the line falls there: `render` must work with `coaching = None`, so the
app is useful before the LLM layer exists. That is the MVP.

Exit: `gh issue list --state open --json number,labels` shows every open issue
carrying exactly one of the two labels.

## Gate 2 - The MVP is groomed, and the loose ends are written down

The PM rewrites each `mvp` issue against `docs/task_template.md`. Grooming
surfaces questions the spec left open; those become entries in
`docs/decisions.md` rather than being answered again inside each issue.

- Every `mvp` issue has Goal, Acceptance criteria, Out of scope, Constraints
- Anything moved out of scope is a new issue labelled `post-mvp`, linked from
  the parent
- `docs/decisions.md` exists, one entry per call, each with a reason and the
  cost accepted where there is one
- `process.md` Background says to read `decisions.md` before grooming or
  implementing, and not to reopen a decision without changing it there first

Exit: no `mvp` issue is missing one of the four sections.

## Gate 3 - Calibration run: issue 7

Issue 7 is half-implemented and is the pilot. Run the full lifecycle on it,
watched, and correct the role documents from what actually goes wrong. One
issue, one run.

- The current state of `--apply` is read before anything is written
- PM grooms, engineer implements, QA posts PASS or FAIL
- On PASS the orchestrator closes it and ticks the box in `backlog.md`
- Whatever the run exposed about the roles is fixed in `docs/team/*.md`

Exit: issue 7 is closed with a QA PASS comment on it.

## Gate 4 - A safety net the loop can lean on

Small, and worth having before the loop runs wide. Both are new tasks, filed
as issues and worked through the normal lifecycle.

- **CI** - GitHub Actions runs `uv run pytest` and `uv run ruff check .` on
  push and on pull request. Green on main.
- **`seed_demo`** - `manage.py seed_demo` creates a realistic portfolio with
  several projects, a mix of active and stalled, so every screen and command
  can be exercised without a GitHub token and without the network. It is what
  makes review possible by hand.

Exit: CI is green on main, and `manage.py seed_demo` followed by
`manage.py runserver` shows a populated dashboard on a fresh database.

## Gate 5 - The MVP loop

The remaining `mvp` issues, in `backlog.md` order, one per run. The run ends
when the issue is closed or blocked - never by starting the next one.

- 11 ISO week window, 12 fetch a week of commits, 13 momentum stats,
  14 stalled detection, 15 mid-flight work, 33 new repos this week,
  16 `report` command, 17 retro page, 36 current-week dashboard
- A blocked issue stops the run and says why. The loop does not skip to an
  easier one.

Exit: every `mvp` issue is closed, and `manage.py report` prints a
retrospective for the current week against seeded data.

## Gate 6 - What QA found becomes the backlog

QA and review turn up real defects that are not in any issue. They are filed,
not fixed in place, so nothing is smuggled into an unrelated change.

- Every QA FAIL that is not a criterion failure becomes its own issue
- Findings are labelled `post-mvp` unless they break an `mvp` acceptance
  criterion, in which case they are `mvp` and block the gate
- Two known candidates to file: the app has no `403`/`404`/`500` templates,
  and nothing yet documents what leaves the machine when the LLM layer is
  turned on

Exit: no known defect exists only in a comment or in a chat log.

## Gate 7 - Post-MVP

Only opens when Gate 5 and Gate 6 are closed. Phases 2 to 6 of `backlog.md`
plus whatever Gate 6 filed, re-prioritised against what the MVP taught. The
coaching layer (24-28) lands here, behind `--no-llm`.

Before it starts: a privacy note stating exactly what is sent to the LLM -
commit subjects and diffstat numbers, never diffs - and where it goes. The
rule is already in `AGENTS.md`; this makes it visible to whoever runs the app.

Exit: decided at the time, not now.

---

## Rules that hold across every gate

- One gate at a time. A later gate is not started because it looks easy.
- One issue per run. The run ends when that issue is closed or blocked.
- The engineer never closes an issue. Only the orchestrator closes one, and
  only after QA posts PASS.
- Nothing is deleted - not branches, not databases, not temporary files. A
  destructive command stops the run waiting for a human, and a stalled run
  costs more than a stale file. If something has to go, say so and let the
  owner run it.
- Wait for a slow command inside the command. An agent that stops is not woken
  by anything, so "I will report when it finishes" is where the work ends.
- Push `main` as soon as it moves. A local commit is invisible, and there is
  no way to tell a working session from a stalled one from the outside.
- A finding is only real once it is an issue.
