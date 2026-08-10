# Maintaining the macOS installer

Internal notes for whoever builds or changes the `.pkg`/`.dmg` — not needed to just install and run Argus Agent (see [README.md](./README.md) for that).

## Why this design

The `.pkg` carries no payload of its own — its `postinstall` script is the whole installer, and just opens a Terminal window that runs `scripts/install.sh` + `scripts/bootstrap.sh`, the exact same path a manual install would take. One install path to maintain; the `.pkg` only changes how it's *triggered*.

- **No admin password needed.** `distribution.xml` declares `enable_currentUserHome="true"` / `enable_localSystem="false"`, so Installer.app installs into the user's domain, not the system — no payload ever touches a root-owned path. Verified empirically: `installer -pkg ... -target CurrentUserHomeDirectory` (no `sudo`) runs the postinstall script as the console user, not root.
- **Root-safe anyway.** `scripts/postinstall` checks `id -u` and re-execs the real logic (`run-wizard.sh`) via `launchctl asuser <uid> sudo -u <user>` if it ever does end up running as root (Homebrew refuses to run as root, and GUI dialogs need the user's Aqua session either way) — belt and suspenders, since which of the two actually happens can depend on the macOS version.
- **No new install logic.** `run-wizard.sh` only launches a Terminal window; the actual work is 100% delegated to `scripts/install.sh`/`bootstrap.sh`, downloaded fresh from `main` each time — so this wizard doesn't need rebuilding on every app release, only when the wizard's own UX changes.

## Signing

Distributing the `.pkg`/`.dmg` via `curl`/`gh release download` instead of a browser avoids the `com.apple.quarantine` extended attribute that triggers Gatekeeper's check in the first place (Safari/Chrome/Mail set it; `curl` doesn't) — this is why CI-driven installs (`install.sh`) never hit the warning users get from a browser download.

If a paid Developer ID ever gets added, sign with `productsign` (for the `.pkg`) and notarize with `xcrun notarytool` before distributing.

## Building

CI builds and attaches `ArgusAgent-Installer.dmg` to every GitHub Release automatically (`.github/workflows/release.yml`, `installer` job — runs on `macos-latest`, since `pkgbuild`/`productbuild`/`hdiutil` are macOS-only). No manual step needed to publish it.

To build locally (for testing changes under `packaging/macos/`):

```bash
packaging/macos/build-pkg.sh [wizard-version]   # -> build/ArgusAgentInstaller.pkg
packaging/macos/build-dmg.sh                    # -> build/ArgusAgent-Installer.dmg
```

`wizard-version` (default `1.0`; CI passes the app's own version) is only metadata shown by `pkgutil --info` — it doesn't affect what the wizard downloads (always the latest release, resolved at install time).

## Testing

`installer -pkg build/ArgusAgentInstaller.pkg -target CurrentUserHomeDirectory` (no `sudo`) exercises the same no-admin path a double-click would, and is useful for checking the package structure — but it opens a **real** Terminal window on whoever's screen is running it and starts a real download/install. Prefer testing via an actual double-click on the `.dmg`/`.pkg` in Finder so you're the one watching it run.

First run also triggers a macOS Automation permission prompt ("Installer" or the shell wants to control "Terminal") — expected, part of how `run-wizard.sh` opens the Terminal window; approve it once.
