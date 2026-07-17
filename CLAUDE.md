# ha-gsender — notes for Claude sessions

Unofficial Home Assistant custom integration (HACS) for gSender CNC software.
All integration code lives in `custom_components/gsender/`.

## Releasing a new version

Releases are fully automated by `.github/workflows/release.yml`. To publish:

1. Add a section to `CHANGELOG.md`: `## [X.Y.Z] - YYYY-MM-DD` (Keep a
   Changelog format). The workflow extracts this section as the release
   notes and **fails if it's missing** — write it first.
2. Bump `"version"` in `custom_components/gsender/manifest.json` to `X.Y.Z`.
3. Commit and push to `main`.

The workflow fires on any push to `main` that touches `manifest.json`,
creates tag `vX.Y.Z`, and publishes the GitHub release. It's idempotent —
if the release already exists it does nothing. Manual trigger:
`workflow_dispatch` on `release.yml` (useful when the version bump was
pushed before the workflow existed or in a commit that didn't touch the
manifest).

HACS installs from the **latest GitHub release** (not `main`), so a change
is not "published" to users until the release exists.

### Gotchas learned the hard way

- **Do not `git push` tags from a Claude Code remote session** — the git
  proxy rejects tag pushes with HTTP 403. That's exactly why the workflow
  creates the tag server-side. Branch pushes (including workflow files)
  work fine.
- The GitHub MCP toolset has no create-release tool; use the workflow
  (trigger via `actions_run_trigger` with `workflow_id: release.yml`,
  `ref: main`) and verify with `get_latest_release`.

## Testing

- `tests/smoke_test.py` is standalone — it stubs all `homeassistant.*`
  modules, no HA install needed:
  `pip install "python-socketio[asyncio_client]==5.11.0" voluptuous`
  then `python tests/smoke_test.py`. Keep it green and extend it when
  changing behavior.
- `tests/live_test.py` is a real-socket end-to-end check of the host-off
  startup recovery (same deps, takes ~5 s): it runs `async_setup_entry`
  with nothing listening, then starts a real gSender-like socket.io server
  and asserts the integration connects and attaches on its own. Run both
  tests before releasing behavior changes.

## Deliberate decisions & known unknowns

- The config flow still **rejects an unreachable host when adding or
  reconfiguring** the integration, even though setup tolerates a down
  host. That split is intentional (owner-confirmed): at add-time a
  failure almost always means a typo'd IP or Remote Mode disabled, and
  accepting it would create an entry stuck at `host_off` forever. Don't
  "fix" this for consistency.
- `elapsedTime`/`remainingTime` from `sender:status` are **assumed** to be
  milliseconds (never verified against a live job) — see the comment on
  `job_elapsed_seconds` in `__init__.py`. If real jobs show values 1000x
  off, fix it there only.
- gSender's `task:*` events are unused on purpose: their payload shapes
  are unverified. Job events derive from `workflow:state` transitions.
- The smoke test monkeypatches module globals (`HOST_PROBE_TIMEOUT`,
  `CONNECT_RETRY_INTERVAL`) to speed things up — keep timing constants
  module-level in `__init__.py` and read them at call time; never copy
  them into other modules via `from ... import`.
- `manifest.json` `"version"` is the single source of truth; the release
  tag is always `v<version>`. `hacs.json` pins minimum HA 2026.3.0 (keep
  it in sync with the README's Requirements section).
- Probe cadence (15 s) was questioned by the owner and deliberately kept
  flat instead of backing off: it's one bounded TCP SYN per interval, and
  backoff would delay noticing the CNC PC booting.

## Architecture invariants (do not break)

- The integration is **read-only**: it attaches via the `addclient` event
  and must never emit `open` on its own — that would fight gSender for the
  serial port. The one exception is the Connect button
  (`async_open_controller`), which only runs on explicit user press.
- `async_setup_entry` must **never** raise `ConfigEntryNotReady`: setup
  has to succeed with the CNC PC off (that was the v0.5.0 fix). The
  initial connection is made by `async_connect_retrying` in the
  background; after the first success, python-socketio's built-in
  reconnection owns the socket (its auto-reconnect does NOT work for a
  never-connected client — that's why the retry loop exists).
- Host probing (one bounded TCP connect per 15 s) runs **only while
  disconnected**; the watchdog skips probing while `_connect_task` is
  alive so probe traffic never doubles.
- socket.io event handlers must not block/await long — spawn tasks
  (see `_schedule_attach_check`).
- Entity availability: everything except `CNC Host Status` and
  `CNC Bridge Connected` is unavailable while the socket is down.
