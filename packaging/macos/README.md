# Argus Agent — macOS Installer

A double-click alternative to running `scripts/install.sh` + `scripts/bootstrap.sh` by hand: opens a Terminal window and runs the same install scripts a manual install would use, visibly.

## Getting it

Download `ArgusAgent-Installer.dmg` from the [latest release](https://github.com/andersontizaias/argus-agent/releases/latest).

## What it can't do

Android Studio and Xcode are installed by Google's/Apple's own installers, which require interactive EULA acceptance — no third-party installer can automate that. The installer checks for them and tells you exactly what to do by hand instead of downloading multi-GB SDKs without asking.

## Signing

Not signed or notarized yet, so Gatekeeper may warn on first open. If it does: System Settings → Privacy & Security → "Open Anyway", or right-click the app → Open.

---

For build/design notes and how to test changes to the installer itself, see [MAINTAINING.md](./MAINTAINING.md).
