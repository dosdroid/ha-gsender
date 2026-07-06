"""Button entities for the gSender integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import GSenderClient
from .const import DOMAIN, SIGNAL_GSENDER_UPDATE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    client: GSenderClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GSenderConnectButton(client, entry)])


class GSenderConnectButton(ButtonEntity):
    """Ask gSender to open the serial port to the CNC controller.

    The only control surface this integration exposes. Equivalent to
    pressing Connect in gSender's own UI; a no-op when already connected.
    """

    _attr_should_poll = False
    _attr_name = "CNC Connect Controller"
    _attr_icon = "mdi:connection"

    def __init__(self, client: GSenderClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connect_controller"
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

    async def async_press(self) -> None:
        await self._client.async_open_controller()
