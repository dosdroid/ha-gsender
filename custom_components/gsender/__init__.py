"""The gSender CNC integration.

Connects to gSender's Remote Mode socket.io server (the same server the
gSender browser remote-control UI connects to) and exposes machine/job
state as Home Assistant entities.

IMPORTANT: This attaches as an additional read-only client via the
'addclient' event. It never emits 'open' - that would try to open the
serial port itself and conflict with the main gSender app holding it.
"""
from __future__ import annotations

import asyncio
import logging

import socketio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_BAUDRATE,
    CONF_FIRMWARE,
    CONF_SERIAL_PORT,
    DEFAULT_BAUDRATE,
    DEFAULT_FIRMWARE,
    DOMAIN,
    EVENT_ALARM,
    EVENT_JOB_FINISHED,
    EVENT_JOB_PAUSED,
    EVENT_JOB_RESUMED,
    EVENT_JOB_STARTED,
    HOST_STATUS_GSENDER_DOWN,
    HOST_STATUS_HOST_OFF,
    HOST_STATUS_ONLINE,
    HOST_STATUS_UNKNOWN,
    SIGNAL_GSENDER_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

# How long to wait for gSender's ack after asking it to open the port.
OPEN_ACK_TIMEOUT = 10
# TCP connect timeout for the host-off probe. A powered-on PC answers a SYN
# (accept or refuse) well within this; only an off/unreachable host times out.
HOST_PROBE_TIMEOUT = 3

# Retry attaching to the controller while the socket is connected but the
# CNC serial port isn't open on the gSender side yet.
ATTACH_RETRY_INTERVAL = 15
# Seconds between attempts to establish the INITIAL connection when the
# host is down at setup time (HA restarted while the CNC PC is off).
# python-socketio's built-in reconnection only takes over after the first
# successful connect.
CONNECT_RETRY_INTERVAL = 15
# How long after 'addclient' before concluding no controller responded.
ATTACH_TIMEOUT = 5


class GSenderClient:
    """Wraps the socket.io connection to gSender's remote server."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        serial_port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        firmware: str = DEFAULT_FIRMWARE,
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.firmware = firmware
        self.url = f"http://{host}:{port}"

        # Socket to gSender's remote server is up.
        self.connected: bool = False
        # online / gsender_down / host_off / unknown - see const.py.
        self.host_status: str = HOST_STATUS_UNKNOWN
        # Set during teardown so the disconnect handler doesn't spawn probes.
        self._shutting_down: bool = False
        # We are attached to a live controller (serial port open in gSender).
        self.controller_attached: bool = False
        # gSender's own port list says our serial port is in use.
        self.port_reported_inuse: bool | None = None

        self.machine_state: str | None = None
        self.job_state: str | None = None
        self.job_name: str | None = None
        self.job_sent: int = 0
        self.job_total: int = 0
        self.job_elapsed: float = 0
        self.job_remaining: float = 0
        self.alarm_message: str | None = None

        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_delay=2,
            reconnection_delay_max=30,
        )
        self._watchdog_task: asyncio.Task | None = None
        self._attach_check_task: asyncio.Task | None = None
        # Runs async_connect_retrying() until the first successful connect;
        # while it's alive the watchdog leaves host probing to it.
        self._connect_task: asyncio.Task | None = None
        self._register_handlers()

    # ------------------------------------------------------------------
    # socket.io event handlers
    # ------------------------------------------------------------------
    def _register_handlers(self) -> None:
        sio = self.sio

        @sio.event
        async def connect(*args):
            _LOGGER.info("Connected to gSender remote server at %s", self.url)
            self.connected = True
            self.host_status = HOST_STATUS_ONLINE
            self.controller_attached = False
            self._push_update()
            # Fire-and-forget: emitting + waiting must NOT block this
            # handler, otherwise incoming events (controller:state etc.)
            # can't be processed while we wait and the attach check would
            # always think it failed.
            self._schedule_attach_check()

        @sio.event
        async def disconnect(*args):
            _LOGGER.warning("Disconnected from gSender remote server")
            self.connected = False
            self.host_status = HOST_STATUS_UNKNOWN
            self._reset_controller_state()
            self._push_update()
            # Find out right away whether the whole PC went down or just
            # gSender; afterwards the watchdog re-probes every tick while
            # disconnected. Spawned task - handlers must not block.
            if not self._shutting_down:
                self.hass.async_create_task(self._probe_host())

        @sio.event
        async def connect_error(*args):
            _LOGGER.error("gSender connection error: %s", args[0] if args else "?")
            self.connected = False
            self._push_update()

        @sio.on("serialport:open")
        async def on_serialport_open(port=None, *args):
            if port in (None, self.serial_port):
                _LOGGER.info("gSender opened serial port %s - attaching", port)
                # Controller just came up; attach to it.
                self._schedule_attach_check()

        @sio.on("serialport:close")
        async def on_serialport_close(options=None, *args):
            closed_port = (
                options.get("port") if isinstance(options, dict) else options
            )
            if closed_port in (None, self.serial_port):
                _LOGGER.info("gSender closed serial port %s", closed_port)
                self._reset_controller_state()
                self._push_update()

        @sio.on("controller:state")
        async def on_controller_state(controller_type=None, state=None, *args):
            status = state.get("status", {}) if isinstance(state, dict) else {}
            active = status.get("activeState")
            if active is not None:
                self.machine_state = active
            self.controller_attached = True
            self._push_update()

        @sio.on("workflow:state")
        async def on_workflow_state(workflow_state=None, *args):
            previous = self.job_state
            self.job_state = workflow_state
            self.controller_attached = True
            # Fire bus events only on genuine transitions - gSender rebroadcasts
            # the current workflow state periodically, not just on change.
            if workflow_state != previous:
                self._fire_workflow_event(previous, workflow_state)
            if workflow_state == "idle":
                # Job over (finished or stopped) - clear stale progress.
                self.job_sent = 0
                self.job_total = 0
                self.job_remaining = 0
            self._push_update()

        @sio.on("sender:status")
        async def on_sender_status(status=None, *args):
            if not isinstance(status, dict):
                return
            self.job_name = status.get("name")
            self.job_sent = status.get("sent", 0)
            self.job_total = status.get("total", 0)
            self.job_elapsed = status.get("elapsedTime", 0)
            self.job_remaining = status.get("remainingTime", 0)
            self.controller_attached = True
            self._push_update()

        @sio.on("alarm")
        async def on_alarm(payload=None, *args):
            self.alarm_message = (
                payload.get("message") if isinstance(payload, dict) else str(payload)
            )
            self.controller_attached = True
            _LOGGER.warning("gSender ALARM: %s", self.alarm_message)
            self.hass.bus.async_fire(
                EVENT_ALARM,
                {**self._event_base(), "message": self.alarm_message},
            )
            self._push_update()

        @sio.on("status")
        async def on_status(payload=None, *args):
            if isinstance(payload, dict) and "activeState" in payload:
                self.machine_state = payload["activeState"]
                self.controller_attached = True
                self._push_update()

        @sio.on("serialport:list")
        async def on_serialport_list(recognized=None, unrecognized=None, network=None, *args):
            all_ports = []
            for group in (recognized, unrecognized, network):
                if isinstance(group, list):
                    all_ports.extend(p for p in group if isinstance(p, dict))
            match = next(
                (p for p in all_ports if p.get("port") == self.serial_port), None
            )
            self.port_reported_inuse = bool(match and match.get("inuse"))
            self._push_update()

    # ------------------------------------------------------------------
    # attach / watchdog
    # ------------------------------------------------------------------
    def _schedule_attach_check(self) -> None:
        """Run the attach sequence as a background task so socket.io event
        processing is never blocked."""
        if self._attach_check_task and not self._attach_check_task.done():
            return  # one in flight already
        self._attach_check_task = self.hass.async_create_task(
            self._attempt_attach()
        )

    async def _attempt_attach(self) -> None:
        # Do NOT gate on self.sio.connected here: when this runs as the
        # spawned task from the 'connect' handler, python-socketio hasn't
        # set that flag yet (it's only set after the connect handler
        # returns and _connect_event fires - verified against
        # python-socketio 5.11 AsyncClient.connect()/​_handle_connect()).
        # self.sio.namespaces IS already populated by that point though,
        # which is all emit() actually checks, so the emit below is safe;
        # genuine disconnects are caught by the except clause.
        try:
            await self.sio.emit("addclient", self.serial_port)
            await self.sio.emit("list")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("attach emit failed: %s", err)
            return
        await asyncio.sleep(ATTACH_TIMEOUT)
        if self.connected and not self.controller_attached:
            _LOGGER.info(
                "No controller on %s yet (gSender reports inuse=%s) - "
                "will keep retrying every %ss",
                self.serial_port,
                self.port_reported_inuse,
                ATTACH_RETRY_INTERVAL,
            )
        self._push_update()

    async def watchdog(self) -> None:
        """Periodic maintenance, one tick per ATTACH_RETRY_INTERVAL.

        - connected but unattached: re-attempt the controller attach
        - disconnected: probe whether the host PC itself is down

        Runs for the lifetime of the config entry as a background task.
        """
        while True:
            await asyncio.sleep(ATTACH_RETRY_INTERVAL)
            if self.connected and not self.controller_attached:
                self._schedule_attach_check()
            elif not self.connected:
                if self._connect_task and not self._connect_task.done():
                    # Initial connect loop is still running - it probes and
                    # classifies the host itself; don't double the traffic.
                    continue
                await self._probe_host()

    # Single-TCP-probe results - internal only.
    _PROBE_ACCEPTS = "accepts"
    _PROBE_REFUSED = "refused"
    _PROBE_UNREACHABLE = "unreachable"

    async def _probe_host_once(self) -> str:
        """One bounded TCP connect attempt to the port we normally talk to.

        - accepts: something is listening (gSender is up, or at least its port)
        - refused (RST): the PC is on but gSender/Remote Mode isn't listening
        - unreachable: timeout / no route - the PC is off or unreachable (a
          firewall that DROPs would look the same - acceptable ambiguity)
        """
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=HOST_PROBE_TIMEOUT,
            )
        except ConnectionRefusedError:
            return self._PROBE_REFUSED
        except (TimeoutError, OSError):
            return self._PROBE_UNREACHABLE
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return self._PROBE_ACCEPTS

    def _set_host_status(self, status: str) -> None:
        if status != self.host_status:
            _LOGGER.info("gSender host probe: %s", status)
            self.host_status = status
            self._push_update()

    async def _probe_host(self) -> None:
        """Classify why the bridge is down: gSender gone vs whole PC gone.

        Runs ONLY while disconnected (a connected socket already proves the
        host is up), so there is no probe traffic at all in normal operation.
        A port that accepts again also maps to gsender_down: it means the PC
        is up, and the reconnecting socket.io client will flip us to online
        shortly.
        """
        if self.connected:
            return
        if await self._probe_host_once() == self._PROBE_UNREACHABLE:
            self._set_host_status(HOST_STATUS_HOST_OFF)
        else:
            self._set_host_status(HOST_STATUS_GSENDER_DOWN)

    async def async_connect_retrying(self) -> None:
        """Establish the initial connection, retrying until it succeeds.

        python-socketio only auto-reconnects after a connection has succeeded
        once; a failed initial connect() just raises and stays dead. So when
        the CNC PC is off while HA (re)starts, this loop keeps trying in the
        background instead of failing the config entry setup. Each round
        starts with the cheap bounded TCP probe - it keeps the host status
        sensor truthful and avoids long socket.io connect hangs against a
        host that is off. After the first successful connect, the built-in
        reconnection logic owns the socket and this task ends.
        """
        while not self._shutting_down:
            result = await self._probe_host_once()
            if result == self._PROBE_ACCEPTS:
                try:
                    await self.async_connect()
                    return
                except (socketio.exceptions.ConnectionError, OSError) as err:
                    _LOGGER.debug(
                        "Initial connection to %s failed: %s", self.url, err
                    )
                    self._set_host_status(HOST_STATUS_GSENDER_DOWN)
            elif result == self._PROBE_REFUSED:
                self._set_host_status(HOST_STATUS_GSENDER_DOWN)
            else:
                self._set_host_status(HOST_STATUS_HOST_OFF)
            await asyncio.sleep(CONNECT_RETRY_INTERVAL)

    # ------------------------------------------------------------------
    # helpers / lifecycle
    # ------------------------------------------------------------------
    def _reset_controller_state(self) -> None:
        self.controller_attached = False
        self.machine_state = None
        self.job_state = None
        self.job_name = None
        self.job_sent = 0
        self.job_total = 0
        self.job_elapsed = 0
        self.job_remaining = 0
        self.port_reported_inuse = None

    def _event_base(self) -> dict:
        """Fields common to every event fired on the HA bus, so automations
        can filter when multiple gSender instances are configured."""
        return {"host": self.host, "serial_port": self.serial_port}

    def _fire_workflow_event(self, previous: str | None, current: str | None) -> None:
        """Translate a workflow:state transition into an HA bus event.

        Only called for real transitions. `previous is None` means this is
        the first workflow state we see after (re)attaching - that's a
        snapshot of existing state, not something happening now, so it must
        not fire (otherwise every HA restart during a job would fire
        'job started', and connecting to an idle machine would fire nothing
        but a reconnect during idle->idle would be fine anyway).
        """
        if previous is None:
            return
        data = {
            **self._event_base(),
            "job_name": self.job_name,
            "previous_state": previous,
        }
        if current == "running":
            event = EVENT_JOB_STARTED if previous == "idle" else EVENT_JOB_RESUMED
        elif current == "paused":
            event = EVENT_JOB_PAUSED
        elif current == "idle":
            # Completed or stopped by user - gSender doesn't distinguish here.
            event = EVENT_JOB_FINISHED
            data["elapsed_time"] = self.job_elapsed
            data["sent_lines"] = self.job_sent
            data["total_lines"] = self.job_total
        else:
            return
        self.hass.bus.async_fire(event, data)

    def _push_update(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_GSENDER_UPDATE)

    async def async_open_controller(self) -> None:
        """Ask gSender to open the serial port to the CNC controller.

        This is the ONE deliberate exception to the module-docstring rule
        about never emitting 'open': it exists precisely for the case where
        gSender is running but not connected, and only ever runs from an
        explicit user action (button press) - never automatically. It
        replicates what gSender's own UI Connect button sends:
        emit('open', port, {baudrate, rtscts, network, defaultFirmware}, ack).

        Raises HomeAssistantError with the gSender-reported reason if the
        port can't be opened (e.g. machine off / cable unplugged).
        """
        if not self.connected:
            raise HomeAssistantError("Not connected to gSender's remote server")
        if self.controller_attached:
            _LOGGER.info(
                "Controller on %s already attached - not sending open",
                self.serial_port,
            )
            return
        options = {
            "baudrate": self.baudrate,
            "rtscts": False,
            "network": False,
            "defaultFirmware": self.firmware,
        }
        _LOGGER.info("Asking gSender to open %s (%s)", self.serial_port, options)
        try:
            error = await self.sio.call(
                "open", (self.serial_port, options), timeout=OPEN_ACK_TIMEOUT
            )
        except socketio.exceptions.TimeoutError as err:
            raise HomeAssistantError(
                f"gSender did not acknowledge opening {self.serial_port} "
                f"within {OPEN_ACK_TIMEOUT}s"
            ) from err
        if error:
            raise HomeAssistantError(
                f"gSender could not open {self.serial_port}: {error}"
            )
        # Success: gSender broadcasts serialport:open, which triggers our
        # attach flow automatically - nothing more to do here.

    async def async_connect(self) -> None:
        await self.sio.connect(self.url, transports=["websocket", "polling"])

    async def async_disconnect(self) -> None:
        self._shutting_down = True
        if self._attach_check_task and not self._attach_check_task.done():
            self._attach_check_task.cancel()
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
        try:
            if self.sio.connected:
                await self.sio.disconnect()
        except Exception:  # noqa: BLE001
            pass

    @property
    def job_progress_percent(self) -> int:
        if self.job_total > 0:
            return round((self.job_sent / self.job_total) * 100)
        return 0

    # ASSUMPTION (unverified live - only ever observed 0 with no job
    # running): elapsedTime/remainingTime are milliseconds, per gSender's
    # CNCjs heritage (Sender.js accumulates Date.now() deltas). If a real
    # job shows values 1000x off, fix it HERE only - sensors use these.
    @property
    def job_elapsed_seconds(self) -> int:
        return round(self.job_elapsed / 1000)

    @property
    def job_remaining_seconds(self) -> int:
        return round(self.job_remaining / 1000)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up gSender from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    serial_port = entry.data[CONF_SERIAL_PORT]
    # .get() fallbacks: entries created before these fields existed.
    baudrate = entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
    firmware = entry.data.get(CONF_FIRMWARE, DEFAULT_FIRMWARE)

    client = GSenderClient(hass, host, port, serial_port, baudrate, firmware)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client

    # Setup must succeed even when the CNC PC is off - an HA restart while
    # the machine was down used to leave the entry stuck in setup-retry with
    # no entities at all. Instead, connect in the background: entities start
    # unavailable (host status shows host_off/gsender_down) and come alive
    # on their own the moment gSender is reachable.
    client._connect_task = entry.async_create_background_task(
        hass, client.async_connect_retrying(), name="gsender_connect"
    )

    # Watchdog is tied to the entry lifecycle: HA cancels it on unload.
    entry.async_create_background_task(hass, client.watchdog(), name="gsender_watchdog")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        client: GSenderClient = hass.data[DOMAIN].pop(entry.entry_id)
        await client.async_disconnect()
    return unload_ok
