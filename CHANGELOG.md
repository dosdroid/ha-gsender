# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Each release's notes are published automatically as a
[GitHub release](https://github.com/dosdroid/ha-gsender/releases), which is
what HACS installs.

## [0.5.0] - 2026-07-17

### Fixed

- Restarting Home Assistant while the CNC PC is off no longer leaves the
  integration stuck in "Retrying setup" with no entities. Setup now always
  succeeds: all entities are created immediately, the **CNC Host Status**
  sensor reports `host_off` / `gsender_down` right from boot, and the
  integration connects on its own (within ~15 s) as soon as gSender becomes
  reachable — no reload or restart needed. The initial connection is handled
  by a background retry loop using the same lightweight TCP probe the
  watchdog already used, so there is no extra network traffic.

### Added

- Release automation: bumping the version in `manifest.json` on `main`
  publishes a GitHub release with notes from this changelog, so HACS shows
  and installs proper versioned releases.
- `CHANGELOG.md` (this file).

## [0.4.0] - 2026-07-06

Initial public release.

- Read-only connection to gSender's Remote Mode socket.io server — attaches
  with `addclient`, never opens the CNC serial port on its own.
- Sensors: machine state, job state, job progress, job elapsed/remaining
  time, job file, last alarm, host status (`online` / `gsender_down` /
  `host_off`).
- Binary sensors: bridge connected, controller attached, job running.
- **CNC Connect Controller** button — equivalent to gSender's own Connect
  button, only ever acts on explicit user press.
- Home Assistant bus events for automations: `gsender_job_started`,
  `gsender_job_paused`, `gsender_job_resumed`, `gsender_job_finished`,
  `gsender_alarm`.
- Watchdog with re-attach and host-off TCP probe while disconnected.
- Config flow with reconfigure support (DHCP-friendly), diagnostics with
  redacted host.
