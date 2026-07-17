> [!CAUTION]
> Integration has not been fully tested. Any feedback is welcomed.

<br>

<p align="center">
  <img src="custom_components/gsender/brand/icon.png" alt="gSender integration icon" width="128">
</p>

<h1 align="center">gSender for Home Assistant</h1>

<p align="center">
  Unofficial Home Assistant integration for
  <a href="https://sienci.com/gsender/">gSender</a> — monitor your CNC machine
  and get automation-friendly events, over your local network, with no extra
  infrastructure.
</p>

---

> **Unofficial.** This project is not affiliated with, endorsed by, or
> supported by Sienci Labs. gSender is a product of
> [Sienci Labs](https://sienci.com/). Please report issues with this
> integration [here](https://github.com/dosdroid/ha-gsender/issues), **not**
> to Sienci.

## What it does

The integration connects to the socket.io server that gSender's **Remote Mode**
exposes (the same one the built-in browser remote UI uses) and attaches as a
read-only listener next to your running gSender app. No MQTT broker, no Docker
sidecar, no polling — state is pushed to Home Assistant the moment gSender
broadcasts it.

It never opens the CNC serial port on its own and never interferes with a
running job. The single control it offers — a **Connect** button — does
exactly what clicking Connect in gSender's own UI does, and only when you
press it.

### Entities

| Entity | Type | Description |
|---|---|---|
| CNC Machine State | sensor | GRBL/grblHAL state: `Idle`, `Run`, `Hold`, `Jog`, `Alarm`, `Door`, `Check`, `Home`, `Sleep` — or `no_controller` when gSender isn't connected to the machine |
| CNC Job State | sensor | Workflow state: `idle` / `running` / `paused` |
| CNC Job Progress | sensor | Percent of G-code lines sent (sent/total lines and raw times as attributes) |
| CNC Job Elapsed Time | sensor | Duration of the current job (seconds) |
| CNC Job Remaining Time | sensor | Estimated time remaining (seconds) |
| CNC Job File | sensor | Name of the loaded G-code file |
| CNC Last Alarm | sensor | Most recent alarm/error message |
| CNC Host Status | sensor | `online` / `gsender_down` (PC on, gSender not running) / `host_off` (PC unreachable) — see below |
| CNC Bridge Connected | binary sensor | Socket to gSender's remote server is up |
| CNC Controller Attached | binary sensor | gSender is actually talking to the CNC controller (serial port open) |
| CNC Job Running | binary sensor | A job is actively running |
| CNC Connect Controller | button | Ask gSender to connect to the machine (no-op if already connected) |

### Events (for automations)

Fired on the Home Assistant event bus on real state transitions only —
gSender's periodic rebroadcasts are deduplicated, and the snapshot received on
(re)connect never fires a stale event:

| Event | When |
|---|---|
| `gsender_job_started` | workflow went `idle` → `running` |
| `gsender_job_paused` | job paused |
| `gsender_job_resumed` | job resumed |
| `gsender_job_finished` | job ended (completed **or** stopped — gSender doesn't distinguish); payload includes `job_name`, `elapsed_time`, `sent_lines`, `total_lines` |
| `gsender_alarm` | controller alarm; payload includes `message` |

All events carry `host` and `serial_port` so multi-machine setups can filter.

Example — announce when a job finishes:

```yaml
automation:
  - alias: "CNC job finished"
    triggers:
      - trigger: event
        event_type: gsender_job_finished
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: >
            CNC finished {{ trigger.event.data.job_name }}
            after {{ (trigger.event.data.elapsed_time / 60000) | round(1) }} min.
```

### Host status — knowing *why* it's offline

When the connection to gSender drops, the integration runs a lightweight TCP
probe (one connection attempt per 15 s, only while disconnected — zero probe
traffic during normal operation) to tell apart:

- `gsender_down` — the PC answered but nothing is listening: gSender is
  closed or Remote Mode is off
- `host_off` — the PC didn't answer at all: it's powered off or unreachable

Perfect for automations like "the CNC PC is off, stop the workshop dashboard"
vs "PC is on, remind me to launch gSender".

## Requirements

- gSender with **Remote Mode enabled** (gSender → Config → Remote Mode) on the
  computer driving your CNC
- Home Assistant **2026.3** or newer
- The Home Assistant instance must be able to reach the gSender machine's
  IP/port on your network

## Installation

### HACS (custom repository)

1. In Home Assistant, open **HACS**
2. Menu (⋮) → **Custom repositories**
3. Repository: `https://github.com/dosdroid/ha-gsender`, type: **Integration**
4. Click **Add**, then find **gSender** in HACS and install it
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/gsender` folder from this repository into your
   Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. **Settings → Devices & Services → Add Integration → gSender**
2. Fill in:
   - **Host / IP** and **port** — shown in gSender under Config → Remote Mode
     (default port `8000`)
   - **Serial port path** — must exactly match the port gSender uses for your
     machine, e.g. `/dev/ttyUSB0` (Linux) or `COM3` (Windows)
   - **Baud rate** and **firmware** (`Grbl` / `grblHAL`) — only used by the
     Connect button; defaults suit most machines
3. Everything can be changed later via **Reconfigure** on the integration
   entry (handy when the gSender PC gets a new DHCP address) but it is recommended to put CNC PC on static address.

## How it works (technical)

- Attaches to gSender's socket.io server with the `addclient` event — the
  read-only listener mechanism gSender provides for its own remote UI — and
  never emits `open` on its own, so it cannot fight over the serial port
- Push-based (`iot_class: local_push`): entities update from
  `controller:state`, `workflow:state`, `sender:status`, `serialport:*` and
  `alarm` broadcasts
- A watchdog re-attaches automatically after gSender restarts, the port
  reopens, or the connection drops
- Home Assistant can start (or restart) while the CNC PC is off: the
  integration loads anyway, shows `host_off`, and connects on its own as
  soon as gSender becomes reachable — no reload needed
- If gSender's Remote Mode isn't connected to the controller yet, entities
  show `no_controller` until the port opens (or you press Connect)

## Known limitations

- **"Idle" does not mean the machine is powered.** Most hobby CNC control
  boards are powered by USB alone, so the controller can report `Idle` while
  the machine's PSU is off. Check your spindle power before trusting a green
  dashboard.
- `gsender_job_finished` fires for both completed and user-stopped jobs —
  gSender's workflow state doesn't distinguish them.
- Elapsed/remaining times are reported by gSender's sender module and are
  only as accurate as its own estimates.
- If a firewall silently drops traffic to the gSender PC, `host_off` cannot
  be distinguished from the PC being off.

## Credits

- [Sienci Labs](https://sienci.com/) for gSender (GPL-3.0) — this integration
  talks to its Remote Mode API but shares no code with it
- Everyone in the
  [Sienci forum thread](https://forum.sienci.com/t/comms-in-out-for-external-monitoring-and-control-thread/6347)
  who asked for CNC monitoring in Home Assistant and explored earlier
  approaches

## License

[MIT](LICENSE)
