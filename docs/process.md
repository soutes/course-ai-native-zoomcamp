- Tasks are GitHub issues, one at a time
- Commit regularly

Background

- `docs/decisions.md` - the calls already made, with reasons. Read it before
  grooming or implementing, and do not reopen a decision without changing it
  there first
- `docs/outdated/` holds superseded material. It is reference, not the
  backlog - where it disagrees with `decisions.md` or an issue, it loses

Roles

- PM - grooms a task before anyone implements it, follows `docs/team/pm.md`
- Engineer - implements one groomed task, follows `docs/team/software-engineer.md`
- QA - checks the result against the acceptance criteria, follows `docs/team/qa-engineer.md`

Orchestrator

The main session is the orchestrator. It launches the PM, the engineer
and QA as subagents. It does not groom, implement or test itself.

Lifecycle

The orchestrator runs one issue at a time. One run, one issue.

1. Take the issue number given to it, or the next open issue in
   backlog.md order if none was given
2. PM grooms it
3. Engineer implements it
4. QA verifies it
5. On FAIL, back to step 3 with the QA comment as input
6. On PASS, close the issue and tick the checkbox in backlog.md
7. Stop. Do not start another issue.

Rules

- Do not skip step 2
- Never start a second issue in the same run. The run ends when the
  current issue is closed or blocked.
- If the current issue is blocked, say why and stop. Do not skip ahead
  to an easier issue.
- The engineer does not close the issue
- QA does not fix the code, only outputs PASS or FAIL
- The orchestrator closes the issue only after QA outputs PASS
