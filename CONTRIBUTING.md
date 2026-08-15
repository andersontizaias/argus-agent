# Contributing

## Branching model

- `main` — always releasable. Every merge into it triggers a release automatically (see below).
- `develop` — integration branch. All new work lands here first.
- Feature/fix branches — branch off `develop`, open a PR back into `develop`.

Both `main` and `develop` are protected: no direct pushes, PRs required, CI must pass before merging.

```
feature/x ──PR──▶ develop ──(CI green)──▶ auto-PR ──auto-merge──▶ main ──dispatch──▶ release
```

1. Branch off `develop`, make your changes, open a PR into `develop`.
2. CI (`ci.yml`) runs automatically; it must pass before the PR can be merged.
3. Once merged, if `develop` is ahead of `main`, CI opens a PR from `develop` into `main` and enables GitHub's native auto-merge on it — it reuses the status checks already reported for that commit (same SHA as `develop`), so it merges on its own within seconds, no manual click needed. This requires "Allow auto-merge" enabled in the repo Settings (General → Pull Requests); if it's off, the PR just sits there for a manual merge instead — same as before.
4. GitHub doesn't fire `on: push` workflows for commits made by `GITHUB_TOKEN` (loop-prevention), so the same CI job explicitly dispatches `release.yml` (`workflow_dispatch`) right after confirming the merge landed — merging into `main` doesn't trigger it by itself.
5. `release.yml` reads the version from `pyproject.toml`, tags it, and publishes the GitHub Release (tarball + installer) — only if that version doesn't have a tag yet. A merge without a version bump is a no-op, expected for docs/chore-only changes.

Want to review the develop→main PR before it ships? Disable "Allow auto-merge" in Settings, or just merge/close it manually before auto-merge catches up.

## Version bumps

Bump `version` in `pyproject.toml` as part of the PR that should ship a release. A merge to `main` without a version bump is a no-op for `release.yml`.
