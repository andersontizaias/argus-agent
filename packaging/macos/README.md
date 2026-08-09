# Argus Agent — macOS installer wizard (.pkg / .dmg)

A visual, double-click alternative to running `scripts/install.sh` +
`scripts/bootstrap.sh` by hand. It doesn't replace them — it wraps them: the
`.pkg` carries no payload of its own, and its `postinstall` script is the
whole installer. Clicking through the wizard:

1. Opens a Terminal window and runs the exact same `scripts/install.sh` and
   `scripts/bootstrap.sh` a manual install would use — one install path to
   maintain, the `.pkg` only changes how it's *triggered*.

## Why this design

- **No admin password needed.** `distribution.xml` declares
  `enable_currentUserHome="true"` / `enable_localSystem="false"`, so
  Installer.app installs into the user's domain, not the system — no
  payload ever touches a root-owned path. Verified empirically: `installer
  -pkg ... -target CurrentUserHomeDirectory` (no `sudo`) runs the
  postinstall script as the console user, not root.
- **Root-safe anyway.** `scripts/postinstall` checks `id -u` and re-execs
  the real logic (`run-wizard.sh`) via `launchctl asuser <uid> sudo -u
  <user>` if it ever does end up running as root (Homebrew refuses to run
  as root, and GUI dialogs need the user's Aqua session either way) —
  belt and suspenders, since which of the two actually happens can depend
  on the macOS version.
- **No new install logic.** `run-wizard.sh` only launches a Terminal
  window; the actual work is 100% delegated to `scripts/install.sh`/
  `bootstrap.sh`, downloaded fresh from `main` each time — so this wizard
  doesn't need rebuilding on every app release, only when the wizard's own
  UX changes.

## What it can't do

Android Studio and Xcode are installed by Google's/Apple's own installers,
which require interactive EULA acceptance — no third-party installer can
automate that. `bootstrap.sh` (which this wizard runs) checks for them and
tells you exactly what to do by hand instead of downloading multi-GB SDKs
without asking.

## Signing

**Not signed or notarized** (no paid Apple Developer account). Gatekeeper
may warn on first open. Two mitigations:

- Distributing the `.pkg`/`.dmg` via `curl`/`gh release download` instead
  of a browser avoids the `com.apple.quarantine` extended attribute that
  triggers Gatekeeper's check in the first place (Safari/Chrome/Mail set
  it; `curl` doesn't).
- If it does warn: System Settings → Privacy & Security → "Open Anyway",
  or right-click → Open.

If a paid Developer ID ever gets added, sign with `productsign` (for the
`.pkg`) and notarize with `xcrun notarytool` before distributing.

## Building

CI builds and attaches `ArgusAgent-Installer.dmg` to every GitHub Release
automatically (`.github/workflows/release.yml`, `installer` job — runs on
`macos-latest`, since `pkgbuild`/`productbuild`/`hdiutil` are macOS-only).
No manual step needed to publish it.

To build locally (for testing changes under `packaging/macos/`):

```bash
packaging/macos/build-pkg.sh [wizard-version]   # -> build/ArgusAgentInstaller.pkg
packaging/macos/build-dmg.sh                    # -> build/ArgusAgent-Installer.dmg
```

`wizard-version` (default `1.0`; CI passes the app's own version) is only
metadata shown by `pkgutil --info` — it doesn't affect what the wizard
downloads (always the latest release, resolved at install time).

## Testing

`installer -pkg build/ArgusAgentInstaller.pkg -target
CurrentUserHomeDirectory` (no `sudo`) exercises the same no-admin path a
double-click would, and is useful for checking the package structure — but
it opens a **real** Terminal window on whoever's screen is running it and
starts a real download/install. Prefer testing via an actual double-click
on the `.dmg`/`.pkg` in Finder so you're the one watching it run.

First run also triggers a macOS Automation permission prompt ("Installer"
or the shell wants to control "Terminal") — expected, part of how
`run-wizard.sh` opens the Terminal window; approve it once.
