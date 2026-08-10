# Contributing

## Branching model

- `main` — always releasable. Every merge into it triggers a release automatically (see below).
- `develop` — integration branch. All new work lands here first.
- Feature/fix branches — branch off `develop`, open a PR back into `develop`.

Both `main` and `develop` are protected: no direct pushes, PRs required, CI must pass before merging.

```
feature/x ──PR──▶ develop ──(CI green)──▶ auto-PR ──merge──▶ main ──▶ release
```

1. Branch off `develop`, make your changes, open a PR into `develop`.
2. CI (`ci.yml`) runs automatically; it must pass before the PR can be merged.
3. Once merged, if `develop` is ahead of `main`, CI opens a PR from `develop` into `main` automatically.
4. Review and merge that PR whenever you're ready to ship.
5. Merging into `main` triggers `release.yml`, which reads the version from `pyproject.toml`, tags it, and publishes the GitHub Release (tarball + installer). If the merge didn't bump the version, nothing is published — that's expected for docs/chore-only changes.

## Version bumps

Bump `version` in `pyproject.toml` as part of the PR that should ship a release. A merge to `main` without a version bump is a no-op for `release.yml`.
