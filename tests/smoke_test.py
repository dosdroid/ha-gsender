"""Standalone smoke test for the gSender integration.

No Home Assistant install needed - homeassistant.* modules are stubbed
below. Drives the socket.io handlers in GSenderClient directly (no
network) and asserts on the resulting client/entity state and fired
bus events.

Run:
    pip install "python-socketio[asyncio_client]==5.11.0" voluptuous
    python tests/smoke_test.py
"""
from __future__ import annotations

import asyncio
import sys
import types
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------------
# homeassistant.* stubs
# ---------------------------------------------------------------------------


def _module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


ha = _module("homeassistant")

const = _module("homeassistant.const")
const.CONF_HOST = "host"
const.CONF_PORT = "port"


class Platform(str, Enum):
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"


class EntityCategory(str, Enum):
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"


class UnitOfTime(str, Enum):
    SECONDS = "s"
    MILLISECONDS = "ms"


const.Platform = Platform
const.EntityCategory = EntityCategory
const.UnitOfTime = UnitOfTime

exceptions = _module("homeassistant.exceptions")


class ConfigEntryNotReady(Exception):
    pass


class HomeAssistantError(Exception):
    pass


exceptions.ConfigEntryNotReady = ConfigEntryNotReady
exceptions.HomeAssistantError = HomeAssistantError

core = _module("homeassistant.core")


class _Bus:
    def __init__(self) -> None:
        self.fired: list[tuple[str, dict]] = []

    def async_fire(self, event: str, data: dict | None = None) -> None:
        self.fired.append((event, data or {}))


class HomeAssistant:
    def __init__(self) -> None:
        self.data: dict = {}
        self.bus = _Bus()
        self._tasks: list[asyncio.Task] = []

    def async_create_task(self, coro):
        task = asyncio.ensure_future(coro)
        self._tasks.append(task)
        return task


core.HomeAssistant = HomeAssistant
core.callback = lambda func: func

config_entries = _module("homeassistant.config_entries")


class ConfigEntry:
    def __init__(self, entry_id="test_entry", data=None):
        self.entry_id = entry_id
        self.data = data or {}

    def async_create_background_task(self, hass, coro, name=None):
        return hass.async_create_task(coro)


class ConfigFlowResult(dict):
    pass


class ConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        cls._domain = domain
        super().__init_subclass__(**kwargs)


config_entries.ConfigEntry = ConfigEntry
config_entries.ConfigFlowResult = ConfigFlowResult
config_entries.ConfigFlow = ConfigFlow

helpers = _module("homeassistant.helpers")

dispatcher = _module("homeassistant.helpers.dispatcher")
_LISTENERS: dict[str, list] = {}


def async_dispatcher_connect(hass, signal, target):
    _LISTENERS.setdefault(signal, []).append(target)
    return lambda: _LISTENERS[signal].remove(target)


def async_dispatcher_send(hass, signal, *args):
    for target in list(_LISTENERS.get(signal, [])):
        target(*args)


dispatcher.async_dispatcher_connect = async_dispatcher_connect
dispatcher.async_dispatcher_send = async_dispatcher_send

device_registry = _module("homeassistant.helpers.device_registry")


class DeviceInfo(dict):
    pass


device_registry.DeviceInfo = DeviceInfo

components = _module("homeassistant.components")

sensor_mod = _module("homeassistant.components.sensor")


class _EntityBase:
    hass = None

    def async_write_ha_state(self):
        pass

    def async_on_remove(self, fn):
        pass


class SensorDeviceClass(str, Enum):
    DURATION = "duration"


class SensorStateClass(str, Enum):
    MEASUREMENT = "measurement"


sensor_mod.SensorEntity = type("SensorEntity", (_EntityBase,), {})
sensor_mod.SensorDeviceClass = SensorDeviceClass
sensor_mod.SensorStateClass = SensorStateClass

button_mod = _module("homeassistant.components.button")
button_mod.ButtonEntity = type("ButtonEntity", (_EntityBase,), {})

binary_sensor_mod = _module("homeassistant.components.binary_sensor")


class BinarySensorDeviceClass(str, Enum):
    CONNECTIVITY = "connectivity"
    RUNNING = "running"


binary_sensor_mod.BinarySensorEntity = type("BinarySensorEntity", (_EntityBase,), {})
binary_sensor_mod.BinarySensorDeviceClass = BinarySensorDeviceClass

diagnostics_mod = _module("homeassistant.components.diagnostics")


def async_redact_data(data, to_redact):
    return {
        k: ("**REDACTED**" if k in to_redact else v) for k, v in data.items()
    }


diagnostics_mod.async_redact_data = async_redact_data

# ---------------------------------------------------------------------------
# import the integration
# ---------------------------------------------------------------------------

# repo layout keeps the package under custom_components/; the standalone
# delivery has it at the top level - support both
_root = Path(__file__).resolve().parent.parent
_pkg_dir = _root / "custom_components"
sys.path.insert(0, str(_pkg_dir if _pkg_dir.is_dir() else _root))

from gsender import GSenderClient  # noqa: E402
from gsender import config_flow  # noqa: E402,F401  (import check only)
from gsender import diagnostics  # noqa: E402
from gsender.button import GSenderConnectButton  # noqa: E402
from gsender.binary_sensor import (  # noqa: E402
    GSenderConnectedSensor,
    GSenderControllerAttachedSensor,
    GSenderJobRunningSensor,
)
from gsender.const import (  # noqa: E402
    EVENT_ALARM,
    EVENT_JOB_FINISHED,
    EVENT_JOB_PAUSED,
    EVENT_JOB_RESUMED,
    EVENT_JOB_STARTED,
)
from gsender.sensor import (  # noqa: E402
    GSenderHostStatusSensor,
    GSenderJobElapsedSensor,
    GSenderJobProgressSensor,
    GSenderJobRemainingSensor,
    GSenderMachineStateSensor,
)

PASSED = 0


def ok(condition: bool, label: str) -> None:
    global PASSED
    assert condition, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok - {label}")


async def main() -> None:
    hass = HomeAssistant()
    client = GSenderClient(hass, "127.0.0.1", 8000, "/dev/ttyUSB0")
    # keep the test hermetic: stops the disconnect handler from spawning
    # real network probes; direct _probe_host() calls still work
    client._shutting_down = True
    h = client.sio.handlers["/"]
    entry = ConfigEntry()
    events = hass.bus.fired

    print("connect / attach snapshot")
    await h["connect"]()
    ok(client.connected, "connected after connect handler")
    await h["controller:state"]("grblHAL", {"status": {"activeState": "Idle"}})
    ok(client.machine_state == "Idle", "machine_state from controller:state")
    ok(client.controller_attached, "controller_attached after state event")
    await h["workflow:state"]("idle")
    ok(events == [], "no bus event for first workflow state (snapshot)")

    print("job lifecycle events")
    await h["sender:status"]({"name": "part.gcode", "sent": 10, "total": 100,
                              "elapsedTime": 60000, "remainingTime": 540000})
    await h["workflow:state"]("running")
    ok(events[-1][0] == EVENT_JOB_STARTED, "idle->running fires job_started")
    ok(events[-1][1]["job_name"] == "part.gcode", "job_started carries job_name")
    await h["workflow:state"]("running")
    ok(len(events) == 1, "repeated same state fires nothing")
    await h["workflow:state"]("paused")
    ok(events[-1][0] == EVENT_JOB_PAUSED, "running->paused fires job_paused")
    await h["workflow:state"]("running")
    ok(events[-1][0] == EVENT_JOB_RESUMED, "paused->running fires job_resumed")

    print("progress / duration sensors")
    progress = GSenderJobProgressSensor(client, entry)
    elapsed = GSenderJobElapsedSensor(client, entry)
    remaining = GSenderJobRemainingSensor(client, entry)
    running = GSenderJobRunningSensor(client, entry)
    ok(progress.native_value == 10, "progress percent 10/100")
    ok(elapsed.native_value == 60, "elapsed ms->s conversion")
    ok(remaining.native_value == 540, "remaining ms->s conversion")
    ok(running.is_on, "job_running on while running")

    print("job end resets progress")
    await h["workflow:state"]("idle")
    ok(events[-1][0] == EVENT_JOB_FINISHED, "running->idle fires job_finished")
    ok(events[-1][1]["elapsed_time"] == 60000, "job_finished carries elapsed (pre-reset)")
    ok(progress.native_value == 0, "progress reset on idle")
    ok(remaining.native_value == 0, "remaining reset on idle")
    ok(not running.is_on, "job_running off after idle")

    print("alarm")
    await h["alarm"]({"message": "Hard limit"})
    ok(events[-1][0] == EVENT_ALARM, "alarm fires bus event")
    ok(events[-1][1]["message"] == "Hard limit", "alarm event carries message")
    ok(client.alarm_message == "Hard limit", "alarm_message stored")

    print("serialport:close handling")
    await h["serialport:close"]({"port": "/dev/ttyACM9"})
    ok(client.controller_attached, "other port close ignored")
    await h["serialport:close"]({"port": "/dev/ttyUSB0"})
    ok(not client.controller_attached, "own port close resets attachment")
    ok(client.machine_state is None, "machine_state cleared on close")

    print("entity availability")
    machine = GSenderMachineStateSensor(client, entry)
    bridge = GSenderConnectedSensor(client, entry)
    attached = GSenderControllerAttachedSensor(client, entry)
    ok(machine.native_value == "no_controller", "machine sensor no_controller")
    ok(machine.available, "machine sensor available while socket up")
    ok(not attached.is_on, "controller_attached sensor off")
    await h["disconnect"]()
    ok(not client.connected, "disconnected")
    ok(not machine.available, "machine sensor unavailable when socket down")
    ok(bridge.available and not bridge.is_on, "bridge sensor stays available, off")

    print("handler robustness (extra broadcast args)")
    await h["connect"]("extra")
    await h["controller:state"]("Grbl", {"status": {"activeState": "Run"}}, "x", 1)
    await h["workflow:state"]("running", {"junk": True})
    await h["sender:status"]({"sent": 1, "total": 2}, None)
    await h["serialport:list"]([], [], [], "tail")
    await h["alarm"]("plain string alarm", 42)
    ok(client.machine_state == "Run", "extra args tolerated everywhere")

    print("connect button")
    calls: list[tuple] = []

    async def fake_call(event, data=None, timeout=None):
        calls.append((event, data, timeout))
        return None  # gSender ack: null = success

    client.sio.call = fake_call
    button = GSenderConnectButton(client, entry)
    await h["disconnect"]()
    ok(not button.available, "button unavailable while socket down")
    try:
        await button.async_press()
        raised = False
    except HomeAssistantError:
        raised = True
    ok(raised, "press while socket down raises")
    await h["connect"]()
    ok(button.available, "button available when socket up")
    client.controller_attached = True
    await button.async_press()
    ok(calls == [], "press while attached is a no-op (no open emitted)")
    client.controller_attached = False
    await button.async_press()
    ok(len(calls) == 1 and calls[0][0] == "open", "press emits open with ack")
    port_arg, options = calls[0][1]
    ok(port_arg == "/dev/ttyUSB0", "open carries serial port")
    ok(options == {"baudrate": 115200, "rtscts": False, "network": False,
                   "defaultFirmware": "grblHAL"}, "open options match gSender UI shape")

    async def fake_call_error(event, data=None, timeout=None):
        return "Port not found"

    client.sio.call = fake_call_error
    try:
        await button.async_press()
        raised = False
    except HomeAssistantError as err:
        raised = "Port not found" in str(err)
    ok(raised, "gSender error ack surfaces as HomeAssistantError")

    print("host status probe")
    host_sensor = GSenderHostStatusSensor(client, entry)
    ok(host_sensor.available, "host status sensor always available")
    await h["connect"]()
    ok(host_sensor.native_value == "online", "online while socket up")
    await client._probe_host()
    ok(host_sensor.native_value == "online", "probe is a no-op while connected")

    real_open_connection = asyncio.open_connection

    async def refused(host, port):
        raise ConnectionRefusedError

    async def unreachable(host, port):
        raise OSError(65, "No route to host")

    async def hangs(host, port):
        await asyncio.sleep(30)

    client.connected = False  # simulate socket drop without handler side effects
    asyncio.open_connection = refused
    await client._probe_host()
    ok(host_sensor.native_value == "gsender_down", "refused -> gsender_down (PC on)")
    asyncio.open_connection = unreachable
    await client._probe_host()
    ok(host_sensor.native_value == "host_off", "no route -> host_off")
    asyncio.open_connection = hangs
    import gsender as gsender_module
    gsender_module.HOST_PROBE_TIMEOUT = 0.05
    await client._probe_host()
    ok(host_sensor.native_value == "host_off", "timeout -> host_off")
    asyncio.open_connection = real_open_connection
    await h["connect"]()
    ok(host_sensor.native_value == "online", "back online on reconnect")
    await h["disconnect"]()
    ok(host_sensor.native_value == "unknown", "unknown right after disconnect")

    print("diagnostics")
    hass.data.setdefault("gsender", {})[entry.entry_id] = client
    diag = await diagnostics.async_get_config_entry_diagnostics(
        hass, ConfigEntry(entry.entry_id, {"host": "1.2.3.4", "port": 8000})
    )
    ok(diag["entry_data"]["host"] == "**REDACTED**", "diagnostics redacts host")
    ok("machine_state" in diag["client"], "diagnostics includes client state")

    print(f"\nall {PASSED} checks passed")


if __name__ == "__main__":
    asyncio.run(main())
