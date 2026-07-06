"""Binary sensor entities for the gSender integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import GSenderClient
from .const import DOMAIN, SIGNAL_GSENDER_UPDATE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    client: GSenderClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GSenderConnectedSensor(client, entry),
            GSenderControllerAttachedSensor(client, entry),
            GSenderJobRunningSensor(client, entry),
        ]
    )


class GSenderBaseBinarySensor(BinarySensorEntity):
    _attr_should_poll = False

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"gSender ({client.host})",
            manufacturer="Sienci Labs",
            model="gSender",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_GSENDER_UPDATE, self._handle_update)
        )

    @property
    def available(self) -> bool:
        return self._client.connected

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class GSenderConnectedSensor(GSenderBaseBinarySensor):
    """Whether the HA integration is connected to gSender's remote server.

    Always available - its whole purpose is to show 'off' when the
    connection is down.
    """

    _attr_name = "CNC Bridge Connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_connected"

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._client.connected


class GSenderControllerAttachedSensor(GSenderBaseBinarySensor):
    """Whether the CNC's serial port is actually open and we're attached
    to a live controller - not just connected to gSender's socket server.
    This is what actually tells you 'is the machine reachable', since the
    socket server can be up with no CNC plugged in / port not opened yet.
    """

    _attr_name = "CNC Controller Attached"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_controller_attached"

    @property
    def is_on(self) -> bool:
        return self._client.controller_attached

    @property
    def extra_state_attributes(self) -> dict:
        return {"port_reported_inuse": self._client.port_reported_inuse}


class GSenderJobRunningSensor(GSenderBaseBinarySensor):
    """Whether a job is actively running."""

    _attr_name = "CNC Job Running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{entry.entry_id}_job_running"

    @property
    def is_on(self) -> bool:
        return self._client.job_state == "running"
