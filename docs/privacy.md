# Privacy: what leaves the machine when the LLM layer is on

This document states plainly what `weekly` sends to an LLM provider, and where it goes. It
covers the AI coaching feature only, because that is the only feature that sends anything today.

## What is sent

Commit subjects and diffstat numbers — lines added, lines removed, files touched — for the
commits in the reporting window. Goal text (`Project.goal`), but only for a project that has
one set — sent as-is, never rewritten by the tool, and only when the LLM is enabled.

## What is never sent

Full diffs. File contents. Repo descriptions.

## Which repos

Commit subjects and diffstat numbers are sent for every tracked repo the report covers,
including private repos. This is not filtered by repo visibility.

## Call shape

Exactly one batched request per report run. Never one call per repo. A single request sees
commit subjects and diffstat numbers from the whole portfolio at once, which is what lets the
coaching name portfolio-wide behavior patterns rather than per-repo observations.

## Where it goes

The OpenAI-compatible endpoint configured via environment variables: base URL, model, and API
key all come from the environment. The default is Groq. No vendor is hardcoded — any
OpenAI-compatible endpoint can be configured instead by changing the environment variables.

## When nothing is sent

`manage.py report --no-llm` skips coaching entirely - no LLM request is made, and
`portfolio.coach` (the only module that talks to the LLM) is never even imported.

Without the flag, an unset `LLM_API_KEY` degrades the same way: the report still renders in
full, no request is made, and one warning line is printed explaining that coaching was
skipped. This holds whether or not `--no-llm` is passed - leaving the key unset guarantees
nothing is sent either way. On this path, no project's goal text is sent either.
