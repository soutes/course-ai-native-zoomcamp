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
