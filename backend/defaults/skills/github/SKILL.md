---
name: github
description: Use the gh CLI for GitHub issues, PR status, CI runs, comments, reviews, releases, and API queries. Use when the user mentions a PR, issue, or repo on GitHub.
---

# GitHub

Use `gh` through `bash` for GitHub work. If a GitHub command fails for an
unclear reason, check `gh auth status`; auth drift is common.

> Adapted from openclaw/openclaw (MIT). See https://github.com/openclaw/openclaw

## When to use

- PR status, reviews, merge readiness
- CI/workflow status + logs
- Creating, closing, commenting on issues
- Creating or merging PRs
- API queries for repo data

## When **not** to use

- Local git ops (`commit`, `push`, `pull`, `branch`) — use `git` directly.
- Non-GitHub remotes (GitLab, Bitbucket, self-hosted).
- Cloning — `git clone` is fine.

## How to use it

Use the `gh` surface directly. A few patterns pay off here:

- Pass `--repo owner/repo` when you're not inside a clone, or pass the
  full URL: `gh pr view https://github.com/owner/repo/pull/55`.
- Prefer `--json <fields> --jq <filter>` over screen-scraping default
  output — it's structured and stable across `gh` versions.
- For repeated reads, `gh api --cache 1h ...` dodges rate limits.
- `gh run view <id> --log-failed` is the fast path to a failing CI step.
