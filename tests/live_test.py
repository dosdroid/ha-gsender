"""Live end-to-end check of host-off-at-startup recovery (v0.5.0 fix).

Real network sockets, real python-socketio client and server, no mocks of
the transport:
1. async_setup_entry runs while NOTHING listens on the port (the pre-fix
   code raised ConfigEntryNotReady here) -> must return True.
2. A real gSender-like socket.io server then starts on that port.
3. The integration must connect on its own (no reload), attach via
   'addclient', and process a controller:state broadcast.

Run (same deps as smoke_test.py - aiohttp ships with the socketio extra):
    pip install "python-socketio[asyncio_client]==5.11.0" voluptuous
    python tests/live_test.py
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_test  # noqa: F401,E402  installs homeassistant.* stubs on import

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402

import socketio  # noqa: E402
from aiohttp import web  # noqa: E402

import gsender  # noqa: E402

PORT = 18123


async def start_server():
    srv = socketio.AsyncServer(async_mode="aiohttp")
    app = web.Application()
    srv.attach(app)
    added_clients = []

    @srv.on("addclient")
    async def addclient(sid, port):
        added_clients.append(port)
        await srv.emit(
            "controller:state",
            ("grblHAL", {"status": {"activeState": "Idle"}}),
            to=sid,
        )

    @srv.on("list")
    async def list_ports(sid):
        await srv.emit(
            "serialport:list",
            ([{"port": "/dev/ttyUSB0", "inuse": True}], [], []),
            to=sid,
        )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    return runner, added_clients


async def main():
    gsender.CONNECT_RETRY_INTERVAL = 1

    hass = HomeAssistant()

    async def _forward(entry, platforms):
        pass

    hass.config_entries = types.SimpleNamespace(
        async_forward_entry_setups=_forward
    )
    entry = ConfigEntry(
        "live", {"host": "127.0.0.1", "port": PORT, "serial_port": "/dev/ttyUSB0"}
    )

    # Phase 1: server down (= CNC PC off) during HA startup
    result = await gsender.async_setup_entry(hass, entry)
    assert result is True, "setup must succeed with server down"
    print("PASS setup returned True with nothing listening")

    client = hass.data["gsender"]["live"]
    await asyncio.sleep(2.5)
    assert not client.connected, "must not be connected yet"
    # localhost refuses (RST) rather than timing out -> gsender_down
    assert client.host_status == "gsender_down", client.host_status
    print(f"PASS while down: connected={client.connected} "
          f"host_status={client.host_status} (still retrying, entry loaded)")

    # Phase 2: the "PC boots and gSender starts"
    runner, added_clients = await start_server()
    print("server started on port", PORT)

    for _ in range(150):
        await asyncio.sleep(0.1)
        if client.controller_attached:
            break
    assert client.connected, "client must auto-connect once server is up"
    assert client.host_status == "online", client.host_status
    assert added_clients == ["/dev/ttyUSB0"], added_clients
    assert client.controller_attached and client.machine_state == "Idle"
    assert client._connect_task.done(), "initial connect loop must have ended"
    print(f"PASS after server up: connected={client.connected} "
          f"host_status={client.host_status} attached={client.controller_attached} "
          f"machine_state={client.machine_state} addclient={added_clients}")

    await client.async_disconnect()
    await runner.cleanup()
    for t in hass._tasks:
        t.cancel()
    print("\nLIVE TEST PASSED: integration survives HA restart with host down "
          "and connects automatically when it comes up")


if __name__ == "__main__":
    asyncio.run(main())
